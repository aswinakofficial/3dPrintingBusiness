"""Output file serving and metadata endpoints."""
import json
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter()


def _job_output_dir(job_id: str) -> Path:
    d = _PROJECT_ROOT / "output" / job_id
    if not d.exists():
        raise HTTPException(404, f"No output directory for job: {job_id}")
    return d


@router.get("/outputs/{job_id}/mesh")
def serve_mesh(job_id: str):
    job_dir = _job_output_dir(job_id)
    glb = next(job_dir.rglob("final_mesh.glb"), None)
    if not glb:
        raise HTTPException(404, f"No GLB found for job: {job_id}")
    return FileResponse(str(glb), media_type="model/gltf-binary", filename="model.glb")


@router.get("/outputs/{job_id}/metadata")
def serve_metadata(job_id: str):
    job_dir = _job_output_dir(job_id)
    meta_file = next(job_dir.rglob("metadata.json"), None)
    if not meta_file:
        raise HTTPException(404, f"No metadata.json for job: {job_id}")
    return json.loads(meta_file.read_text())


@router.get("/outputs/{job_id}/preprocessed")
def list_preprocessed(job_id: str):
    job_dir = _job_output_dir(job_id)
    images = sorted(job_dir.rglob("preprocessed_*.png"))
    return [f"/outputs/{job_id}/image/{img.name}" for img in images]


@router.get("/outputs/{job_id}/image/{filename}")
def serve_image(job_id: str, filename: str):
    job_dir = _job_output_dir(job_id)
    img = next(job_dir.rglob(filename), None)
    if not img:
        raise HTTPException(404, f"Image not found: {filename}")
    return FileResponse(str(img), media_type="image/png")
