"""SQLite-backed job store — survives server restarts."""
import sqlite3
import threading
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).parent.parent
_DB_PATH = _PROJECT_ROOT / "output" / ".jobs.db"

_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Return a per-thread connection (sqlite3 connections are not thread-safe)."""
    if not hasattr(_local, "conn"):
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn


def init_db() -> None:
    _conn().execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id       TEXT PRIMARY KEY,
            engine       TEXT,
            gpu_sku      TEXT,
            status       TEXT,
            created_at   REAL,
            started_at   REAL,
            finished_at  REAL,
            output_dir   TEXT,
            error        TEXT,
            image_count  INTEGER
        )
        """
    )
    _conn().commit()


def upsert_job(job: dict) -> None:
    _conn().execute(
        """
        INSERT INTO jobs
            (job_id, engine, gpu_sku, status, created_at, started_at,
             finished_at, output_dir, error, image_count)
        VALUES
            (:job_id, :engine, :gpu_sku, :status, :created_at, :started_at,
             :finished_at, :output_dir, :error, :image_count)
        ON CONFLICT(job_id) DO UPDATE SET
            engine      = excluded.engine,
            gpu_sku     = excluded.gpu_sku,
            status      = excluded.status,
            created_at  = excluded.created_at,
            started_at  = excluded.started_at,
            finished_at = excluded.finished_at,
            output_dir  = excluded.output_dir,
            error       = excluded.error,
            image_count = excluded.image_count
        """,
        {
            "job_id": job.get("job_id"),
            "engine": job.get("engine"),
            "gpu_sku": job.get("gpu_sku"),
            "status": job.get("status"),
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "output_dir": job.get("output_dir"),
            "error": job.get("error"),
            "image_count": job.get("image_count"),
        },
    )
    _conn().commit()


def get_job(job_id: str) -> Optional[dict]:
    row = _conn().execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 100) -> list[dict]:
    rows = (
        _conn()
        .execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        .fetchall()
    )
    return [dict(r) for r in rows]


def delete_job(job_id: str) -> None:
    _conn().execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    _conn().commit()
