"""Job submission and status tracking endpoints."""
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile

# Add project root to path so scripts.run_job is importable
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.run_job import ENGINE_IMAGE_LIMITS, submit_job  # noqa: E402

router = APIRouter()

# In-memory job registry: job_id → state dict
_jobs: dict[str, dict] = {}

ENGINE_META = {
    "trellis": {
        "label": "TRELLIS.2",
        "min_images": 1,
        "max_images": 4,
        "desc": "Microsoft single-view DiT. Fast, clean geometry.",
        "color": "blue",
    },
    "meshroom": {
        "label": "Meshroom",
        "min_images": 10,
        "max_images": 50,
        "desc": "Photogrammetry SfM. Best for real scanned objects.",
        "color": "green",
    },
    "hunyuan3d": {
        "label": "Hunyuan3D",
        "min_images": 1,
        "max_images": 6,
        "desc": "Tencent multi-view DiT with PBR textures. Most realistic.",
        "color": "purple",
    },
    "triposg": {
        "label": "TripoSG",
        "min_images": 1,
        "max_images": 1,
        "desc": "VAST-AI Flow-Matching DiT. Best single-image quality — closest to Meshy.ai.",
        "color": "orange",
    },
    "sf3d": {
        "label": "SF3D",
        "min_images": 1,
        "max_images": 1,
        "desc": "Stability AI Stable Fast 3D. Sub-second inference, UV-unwrapped PBR textures. Sharpest colours.",
        "color": "teal",
    },
}


@router.get("/engines")
def list_engines():
    return ENGINE_META


@router.post("/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    engine: str = Form(...),
    gpu_sku: str = Form("A100"),
    max_runtime_minutes: int = Form(45),
    generate_views: str = Form("false"),
    images: list[UploadFile] = Form(...),
):
    if engine not in ENGINE_META:
        raise HTTPException(400, f"Unknown engine: {engine}")

    meta = ENGINE_META[engine]
    if not (meta["min_images"] <= len(images) <= meta["max_images"]):
        raise HTTPException(
            400,
            f"{engine} needs {meta['min_images']}–{meta['max_images']} images, "
            f"got {len(images)}",
        )

    job_id = f"{engine}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    input_dir = _PROJECT_ROOT / "input" / job_id
    input_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded images
    for i, upload in enumerate(images, 1):
        suffix = Path(upload.filename).suffix.lower() or ".jpg"
        dest = input_dir / f"{i}{suffix}"
        content = await upload.read()
        dest.write_bytes(content)

    _jobs[job_id] = {
        "job_id": job_id,
        "engine": engine,
        "gpu_sku": gpu_sku,
        "status": "queued",
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "output_dir": None,
        "error": None,
        "image_count": len(images),
    }

    use_generate_views = generate_views.lower() in ("true", "1", "yes")
    background_tasks.add_task(_run_job, job_id, engine, input_dir, gpu_sku, max_runtime_minutes, use_generate_views)

    return {"job_id": job_id, "status": "queued"}


def _run_job(
    job_id: str,
    engine: str,
    input_dir: Path,
    gpu_sku: str,
    max_runtime_minutes: int,
    generate_views: bool = False,
) -> None:
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["started_at"] = time.time()
    try:
        result = submit_job(
            engine=engine,
            input_path=input_dir,
            job_id=job_id,
            gpu_sku=gpu_sku,
            output_dir=_PROJECT_ROOT / "output",
            max_runtime_minutes=max_runtime_minutes,
            generate_views=generate_views,
        )
        _jobs[job_id]["status"] = "succeeded" if result.success else "failed"
        _jobs[job_id]["output_dir"] = str(result.output_dir) if result.output_dir else None
    except Exception as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)
    finally:
        _jobs[job_id]["finished_at"] = time.time()


@router.get("/jobs")
def list_jobs(limit: int = 100):
    """Return in-memory jobs merged with completed jobs scanned from output/."""
    output_root = _PROJECT_ROOT / "output"
    seen = set(_jobs.keys())
    merged = list(_jobs.values())

    if output_root.exists():
        for job_dir in sorted(output_root.iterdir(), reverse=True):
            if job_dir.name in seen or not job_dir.is_dir():
                continue
            # Infer engine from directory name prefix
            engine = job_dir.name.split("-")[0] if "-" in job_dir.name else "unknown"
            glb = next(job_dir.rglob("final_mesh.glb"), None)
            meta_file = next(job_dir.rglob("metadata.json"), None)
            created_ts = job_dir.stat().st_mtime
            merged.append(
                {
                    "job_id": job_dir.name,
                    "engine": engine,
                    "status": "succeeded" if glb else "failed",
                    "created_at": created_ts,
                    "started_at": None,
                    "finished_at": created_ts,
                    "output_dir": str(job_dir),
                    "has_mesh": glb is not None,
                    "has_metadata": meta_file is not None,
                    "image_count": None,
                    "gpu_sku": None,
                    "error": None,
                }
            )
            seen.add(job_dir.name)

    # Annotate in-memory jobs with mesh availability
    for j in merged:
        if "has_mesh" not in j:
            out = j.get("output_dir")
            if out:
                j["has_mesh"] = bool(list(Path(out).rglob("final_mesh.glb")))
            else:
                j["has_mesh"] = False

    merged.sort(key=lambda j: j.get("created_at") or 0, reverse=True)
    return merged[:limit]


@router.get("/jobs/{job_id}/status")
def job_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        # Try to infer from output directory
        output_root = _PROJECT_ROOT / "output" / job_id
        if output_root.exists():
            glb = next(output_root.rglob("final_mesh.glb"), None)
            return {
                "job_id": job_id,
                "status": "succeeded" if glb else "failed",
                "elapsed_s": None,
            }
        raise HTTPException(404, f"Job not found: {job_id}")

    elapsed = None
    if job.get("started_at"):
        end = job.get("finished_at") or time.time()
        elapsed = int(end - job["started_at"])

    return {
        "job_id": job_id,
        "status": job["status"],
        "elapsed_s": elapsed,
        "error": job.get("error"),
    }
