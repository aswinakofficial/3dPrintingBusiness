"""FastAPI app — 3D Figurine Lab web UI."""
import asyncio
import sys
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ui import db  # noqa: E402
from ui.routers import jobs, outputs  # noqa: E402

app = FastAPI(title="3D Figurine Lab", version="0.1.0")

# ---------- Upload size limit (500 MB) ----------
_MAX_UPLOAD = 500 * 1024 * 1024


@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    if request.method == "POST":
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_UPLOAD:
            return JSONResponse(
                status_code=413,
                content={"detail": "Upload too large (max 500 MB)"},
            )
    return await call_next(request)


# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:7860"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(outputs.router)

app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)


# ---------- Startup ----------
@app.on_event("startup")
async def on_startup():
    db.init_db()
    asyncio.create_task(_cleanup_old_outputs(max_age_days=30))


# ---------- 30-day output cleanup ----------
async def _cleanup_old_outputs(max_age_days: int = 30) -> None:
    output_root = _ROOT / "output"
    cutoff = time.time() - max_age_days * 86400
    if not output_root.exists():
        return
    for job_dir in output_root.iterdir():
        if job_dir.name.startswith(".") or not job_dir.is_dir():
            continue
        if job_dir.stat().st_mtime < cutoff:
            import shutil
            try:
                shutil.rmtree(job_dir)
            except Exception:
                pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "ui.app:app", host="127.0.0.1", port=7860, reload=True, app_dir=str(_ROOT)
    )
