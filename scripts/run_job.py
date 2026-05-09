#!/usr/bin/env python3
"""
3D Figurine Lab — Azure Container Instances job runner.

User-facing CLI: uploads input images to blob storage, spins up an ACI
container with GPU, monitors execution, and downloads the resulting STL.

The core logic is exposed as `submit_job()` so the same pipeline can later
be wrapped in an Azure Function, Container Apps Job, or webhook handler
without rewriting.

Usage:
    python scripts/run_job.py --engine trellis --input photo.jpg
    python scripts/run_job.py --engine meshroom --input ./photos/ --gpu-sku T4

Environment:
    AZURE_SUBSCRIPTION_ID      Azure subscription (else discovered via `az account show`)
    AZURE_RESOURCE_GROUP       Resource group (default: rg-3dfigurine-lab-dev-eastus)
    AZURE_STORAGE_ACCOUNT      Storage account (default: st3dfigurinelabdev)
    AZURE_CONTAINER_REGISTRY   ACR login server (default: acr3dfigurinelabdev.azurecr.io)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from azure.identity import DefaultAzureCredential
from azure.mgmt.containerinstance import ContainerInstanceManagementClient
from azure.mgmt.containerinstance.models import (
    Container,
    ContainerGroup,
    EnvironmentVariable,
    GpuResource,
    ResourceRequests,
    ResourceRequirements,
)
from azure.storage.blob import BlobServiceClient

# Project structured logger (JSON output, matches utils/logger.py format).
# sys.path tweak lets the script run from any cwd via `python scripts/run_job.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.logger import get_logger, setup_logger  # noqa: E402

logger = get_logger()


# ---------- Configuration ----------

# ACI's valid GPU SKUs are K80 (deprecated), P100, V100. T4/A100 are NOT
# available on classic ACI -- they're only on AKS or newer compute.
#
# On free / pay-as-you-go-with-credit subscriptions, Azure's default quota
# is V100=0, P100=0, K80=6 in every region. K80 still works for existing
# customers; we keep it as the smoke-test default until quota is bumped.
SUPPORTED_GPU_SKUS = ("V100", "P100", "K80")
DEFAULT_GPU_SKU = "V100"
SUPPORTED_ENGINES = ("trellis", "meshroom")

CONTAINER_BASE_CONFIG = {
    "meshroom": {"image_repo": "3dfigurine-meshroom", "cpu": 4.0, "memory_gb": 16.0},
    "trellis": {"image_repo": "3dfigurine-trellis", "cpu": 4.0, "memory_gb": 16.0},
}


_DEFAULT_RESOURCE_GROUP = "rg-3dfigurine-lab-dev-westus"
_DEFAULT_STORAGE_ACCOUNT = "st3dfigurinelabdev"
_DEFAULT_CONTAINER_REGISTRY = "acr3dfigurinelabdev.azurecr.io"
_DEFAULT_LOCATION = "westus"


@dataclass(frozen=True)
class AzureConfig:
    """Resolved Azure resource references for the deployment environment."""

    subscription_id: str
    resource_group: str = _DEFAULT_RESOURCE_GROUP
    storage_account: str = _DEFAULT_STORAGE_ACCOUNT
    container_registry: str = _DEFAULT_CONTAINER_REGISTRY
    location: str = _DEFAULT_LOCATION

    @classmethod
    def from_env(
        cls,
        subscription_id: Optional[str] = None,
        resource_group: Optional[str] = None,
        storage_account: Optional[str] = None,
        container_registry: Optional[str] = None,
        location: Optional[str] = None,
    ) -> "AzureConfig":
        """Resolve config: explicit args > env vars > defaults."""
        return cls(
            subscription_id=(
                subscription_id
                or os.getenv("AZURE_SUBSCRIPTION_ID")
                or _discover_subscription_id()
            ),
            resource_group=(
                resource_group
                or os.getenv("AZURE_RESOURCE_GROUP", _DEFAULT_RESOURCE_GROUP)
            ),
            storage_account=(
                storage_account
                or os.getenv("AZURE_STORAGE_ACCOUNT", _DEFAULT_STORAGE_ACCOUNT)
            ),
            container_registry=(
                container_registry
                or os.getenv("AZURE_CONTAINER_REGISTRY", _DEFAULT_CONTAINER_REGISTRY)
            ),
            location=(
                location
                or os.getenv("AZURE_LOCATION", _DEFAULT_LOCATION)
            ),
        )


@dataclass
class JobResult:
    """Outcome of a submit_job call."""

    job_id: str
    success: bool
    exit_code: Optional[int]
    output_dir: Optional[Path]


# ---------- Public API (used by CLI today, HTTP wrapper tomorrow) ----------


# Per-engine input requirements, used by validate_input().
ENGINE_IMAGE_LIMITS = {
    "trellis": (1, 4),
    "meshroom": (10, 50),
}
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def validate_input(input_path: Path, engine: str) -> list[Path]:
    """Validate inputs locally with PIL. No Azure calls.

    Raises ValueError / FileNotFoundError on issues so the CLI can exit
    before paying for an ACI run. Returns the list of valid image paths.
    """
    from PIL import Image, UnidentifiedImageError  # lazy import

    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    if input_path.is_file():
        candidates = [input_path]
    else:
        candidates = sorted(
            p
            for p in input_path.rglob("*")
            if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
        )
    if not candidates:
        raise ValueError(f"No supported images found under {input_path}")

    valid: list[Path] = []
    for path in candidates:
        if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image extension: {path}")
        try:
            with Image.open(path) as im:
                im.verify()
        except (UnidentifiedImageError, OSError) as e:
            raise ValueError(f"Could not open as image: {path} ({e})") from e
        valid.append(path)

    lo, hi = ENGINE_IMAGE_LIMITS[engine]
    if len(valid) < lo or len(valid) > hi:
        raise ValueError(
            f"Engine {engine!r} expects between {lo} and {hi} images; got {len(valid)}"
        )
    logger.info(f"Validated {len(valid)} image(s) for engine={engine}")
    return valid


def submit_job(
    *,
    engine: str,
    input_path: Path,
    job_id: Optional[str] = None,
    gpu_sku: str = DEFAULT_GPU_SKU,
    output_dir: Path = Path("output"),
    skip_download: bool = False,
    cleanup: bool = False,
    max_runtime_minutes: int = 30,
    azure: Optional[AzureConfig] = None,
) -> JobResult:
    """Upload, run, and (optionally) download a 3D-processing job on Azure ACI.

    Reusable core. The CLI wraps it; future HTTP/event triggers (Azure
    Function, Container Apps Job) can call it directly without rewriting.

    `max_runtime_minutes` caps how long the job is allowed to run. If exceeded,
    the container group is force-deleted and the call returns success=False.
    """
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"Unknown engine: {engine}. Choose from {SUPPORTED_ENGINES}")
    if gpu_sku not in SUPPORTED_GPU_SKUS:
        raise ValueError(
            f"Unsupported GPU SKU: {gpu_sku}. Choose from {SUPPORTED_GPU_SKUS}"
        )
    if max_runtime_minutes <= 0:
        raise ValueError("max_runtime_minutes must be positive")

    # Local validation before paying for an ACI run.
    validate_input(input_path, engine)

    azure = azure or AzureConfig.from_env()
    runner = ACIJobRunner(azure)
    job_id = job_id or f"{engine}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    logger.info(f"Starting job: {job_id} (max runtime {max_runtime_minutes} min)")
    runner.upload_files(input_path)
    runner.create_job(job_id, engine, gpu_sku=gpu_sku)
    success = runner.monitor_job(job_id, max_wait=max_runtime_minutes * 60)

    exit_code = 0 if success else 1
    out_dir: Optional[Path] = None
    if success and not skip_download:
        out_dir = runner.download_output(output_dir)

    # On failure, capture container logs locally before the container group
    # gets deleted -- otherwise the failure reason is gone forever.
    if not success:
        runner.dump_logs(job_id, output_dir / job_id / "container.log")

    # Cleanup: always tear down on explicit --cleanup, and additionally tear
    # down on failure to avoid clutter (logs are already saved above).
    if cleanup or not success:
        runner.cleanup(job_id)

    return JobResult(
        job_id=job_id, success=success, exit_code=exit_code, output_dir=out_dir
    )


# ---------- Implementation ----------


def _discover_subscription_id() -> str:
    """Discover the subscription via `az account show` when env var unset."""
    try:
        result = subprocess.run(
            ["az", "account", "show", "--query", "id", "-o", "tsv"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception as e:
        raise RuntimeError(
            "Could not determine subscription ID. "
            "Run `az login` or set AZURE_SUBSCRIPTION_ID."
        ) from e


class ACIJobRunner:
    """Submits, monitors, and tears down ACI jobs."""

    def __init__(self, azure: AzureConfig):
        self.azure = azure
        self.credential = DefaultAzureCredential()
        self.aci_client = ContainerInstanceManagementClient(
            self.credential, azure.subscription_id
        )
        self.blob_client = BlobServiceClient(
            account_url=f"https://{azure.storage_account}.blob.core.windows.net",
            credential=self.credential,
        )
        logger.info(f"ACI runner initialised (rg={azure.resource_group})")

    def upload_files(self, source: Path, container: str = "input") -> None:
        client = self.blob_client.get_container_client(container)
        if source.is_file():
            with open(source, "rb") as fh:
                client.upload_blob(source.name, fh, overwrite=True)
            logger.info(f"Uploaded file: {source.name}")
        elif source.is_dir():
            for path in source.rglob("*"):
                if path.is_file():
                    blob_name = str(path.relative_to(source))
                    with open(path, "rb") as fh:
                        client.upload_blob(blob_name, fh, overwrite=True)
                    logger.info(f"Uploaded: {blob_name}")
        else:
            raise FileNotFoundError(f"Path does not exist: {source}")

    def create_job(self, job_id: str, engine: str, gpu_sku: str) -> None:
        if engine not in CONTAINER_BASE_CONFIG:
            raise ValueError(f"Unknown engine: {engine}")
        cfg = CONTAINER_BASE_CONFIG[engine]
        image = f"{self.azure.container_registry}/{cfg['image_repo']}:latest"

        logger.info(
            f"Creating ACI job: {job_id} (engine={engine}, gpu={gpu_sku})"
        )
        container = Container(
            name=job_id,
            image=image,
            resources=ResourceRequirements(
                requests=ResourceRequests(
                    cpu=cfg["cpu"],
                    memory_in_gb=cfg["memory_gb"],
                    gpu=GpuResource(count=1, sku=gpu_sku),
                ),
            ),
            environment_variables=[
                EnvironmentVariable(name="INPUT_DIR", value="/input"),
                EnvironmentVariable(name="OUTPUT_DIR", value="/output"),
                EnvironmentVariable(name="JOB_ID", value=job_id),
            ],
        )
        group = ContainerGroup(
            location=self.azure.location,
            containers=[container],
            os_type="Linux",
            restart_policy="Never",
        )
        self.aci_client.container_groups.begin_create_or_update(
            self.azure.resource_group, job_id, group
        ).wait()
        logger.info(f"ACI job created: {job_id}")

    def monitor_job(
        self, job_id: str, poll_interval: int = 10, max_wait: int = 1800
    ) -> bool:
        """Poll until the container reaches a terminal state or max_wait
        elapses. Returns True on exit_code == 0, False otherwise."""
        start = time.time()
        while time.time() - start < max_wait:
            try:
                grp = self.aci_client.container_groups.get(
                    self.azure.resource_group, job_id
                )
                state = grp.containers[0].instance_view.current_state.state
                elapsed = int(time.time() - start)
                logger.info(f"Job {job_id} state: {state} ({elapsed}s elapsed)")
                if state == "Terminated":
                    code = grp.containers[0].instance_view.current_state.exit_code
                    logger.info(f"Job {job_id} exited with code {code}")
                    return code == 0
                time.sleep(poll_interval)
            except Exception as e:
                logger.warning(f"Monitor error: {e}")
                time.sleep(poll_interval)
        logger.error(
            f"Job {job_id} exceeded {max_wait}s runtime cap; container will be deleted"
        )
        return False

    def download_output(
        self, output_dir: Path, container: str = "output"
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        client = self.blob_client.get_container_client(container)
        for blob in client.list_blobs():
            data = client.download_blob(blob.name).readall()
            target = output_dir / blob.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            logger.info(f"Downloaded: {target}")
        return output_dir

    def cleanup(self, job_id: str) -> None:
        logger.info(f"Cleaning up job: {job_id}")
        try:
            self.aci_client.container_groups.begin_delete(
                self.azure.resource_group, job_id
            ).wait()
            logger.info(f"Deleted job: {job_id}")
        except Exception as e:
            logger.warning(f"Could not delete job {job_id}: {e}")

    def dump_logs(self, job_id: str, target: Path) -> None:
        """Save the container's stdout/stderr to a local file. Best-effort:
        if the container is gone or unreachable, log a warning and continue."""
        try:
            log_obj = self.aci_client.containers.list_logs(
                self.azure.resource_group, job_id, job_id
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(log_obj.content or "")
            logger.info(f"Saved container logs to {target}")
        except Exception as e:
            logger.warning(f"Could not fetch logs for {job_id}: {e}")


# ---------- CLI ----------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Submit 3D processing jobs to Azure Container Instances",
    )
    p.add_argument(
        "--engine",
        required=True,
        choices=SUPPORTED_ENGINES,
        help="3D engine to run",
    )
    p.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Image file or directory of images",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Local directory for downloaded results (default: ./output)",
    )
    p.add_argument(
        "--job-id",
        help="Custom job ID (auto-generated if not provided)",
    )
    p.add_argument(
        "--gpu-sku",
        choices=SUPPORTED_GPU_SKUS,
        default=DEFAULT_GPU_SKU,
        help=f"GPU SKU (default: {DEFAULT_GPU_SKU}). T4 is cheaper, V100 is faster.",
    )
    p.add_argument(
        "--skip-download",
        action="store_true",
        help="Don't download results after job completes",
    )
    p.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete container group after job completes",
    )
    p.add_argument(
        "--max-runtime-minutes",
        type=int,
        default=30,
        help="Hard cap on job runtime (default: 30). Container is force-deleted on overrun.",
    )
    p.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "Sanity-check run: forces --gpu-sku T4, --max-runtime-minutes 5, "
            "--cleanup. Use this to verify a code change cheaply before "
            "submitting a full job."
        ),
    )
    p.add_argument(
        "--validate-only",
        action="store_true",
        help=(
            "Run client-side input validation (PIL, image counts) and exit "
            "without contacting Azure. Useful before paying for an ACI run."
        ),
    )
    p.add_argument("--resource-group", help="Override AZURE_RESOURCE_GROUP")
    p.add_argument("--storage-account", help="Override AZURE_STORAGE_ACCOUNT")
    p.add_argument("--registry", help="Override AZURE_CONTAINER_REGISTRY")
    p.add_argument("--subscription", help="Override AZURE_SUBSCRIPTION_ID")
    p.add_argument(
        "--location",
        help="Azure region for the ACI container group (default: westus, override via AZURE_LOCATION).",
    )
    return p


def main() -> int:
    setup_logger(log_dir="./logs", level="INFO")
    global logger
    logger = get_logger()

    args = _build_parser().parse_args()

    # --validate-only: client-side checks only, no Azure interaction.
    if args.validate_only:
        try:
            validate_input(args.input, args.engine)
        except (FileNotFoundError, ValueError) as e:
            print(f"Validation failed: {e}", file=sys.stderr)
            return 2
        logger.info("Validation passed; no ACI job submitted (--validate-only).")
        return 0

    # --smoke-test: cheapest-possible run with hard guardrails.
    gpu_sku = args.gpu_sku
    max_runtime = args.max_runtime_minutes
    cleanup = args.cleanup
    if args.smoke_test:
        # K80 is the only GPU SKU available on default credit subscriptions
        # (V100/P100 quota is 0 until you file a quota increase). Use it
        # for smoke tests; override to V100 once quota is granted.
        gpu_sku = os.getenv("SMOKE_TEST_GPU", "K80")
        max_runtime = min(args.max_runtime_minutes, 5)
        cleanup = True
        logger.info(
            f"Smoke-test mode: gpu={gpu_sku}, max_runtime={max_runtime}min, cleanup=True"
        )

    azure = AzureConfig.from_env(
        subscription_id=args.subscription,
        resource_group=args.resource_group,
        storage_account=args.storage_account,
        container_registry=args.registry,
        location=args.location,
    )

    try:
        result = submit_job(
            engine=args.engine,
            input_path=args.input,
            job_id=args.job_id,
            gpu_sku=gpu_sku,
            output_dir=args.output,
            skip_download=args.skip_download,
            cleanup=cleanup,
            max_runtime_minutes=max_runtime,
            azure=azure,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        logger.error(f"Job submission failed: {e}")
        return 1

    if not result.success:
        logger.error(f"Job {result.job_id} failed (exit code {result.exit_code})")
        return result.exit_code or 1

    logger.info(f"Job {result.job_id} completed successfully")
    if result.output_dir:
        logger.info(f"Outputs available in {result.output_dir}")
    elif not args.cleanup:
        logger.info(
            f"To cleanup: az container delete --resource-group {azure.resource_group} "
            f"--name {result.job_id}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
