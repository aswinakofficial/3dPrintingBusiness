"""FastAPI app — 3D Figurine Lab web UI."""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure project root is importable (for scripts.run_job)
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ui.routers import jobs, outputs  # noqa: E402

app = FastAPI(title="3D Figurine Lab", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:7860"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(outputs.router)

# Serve static frontend files; this must come last so API routes win
app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "ui.app:app", host="127.0.0.1", port=7860, reload=True, app_dir=str(_ROOT)
    )
