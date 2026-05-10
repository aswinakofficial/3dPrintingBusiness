#!/usr/bin/env python3
"""
3D Figurine Lab — Azure Container Apps job runner.

User-facing CLI: uploads input images to Azure Files, spins up a Container
Apps Job with GPU, monitors execution, and downloads the resulting STL.

Why Container Apps Jobs (not ACI):
ACI's GpuSku enum (V100/P100/K80) has zero quota on free trial / $200-credit
subscriptions. Container Apps' `Consumption-GPU-NC8as-T4` workload profile
is available on the same subscriptions and is per-second billed.

The core logic is exposed as `submit_job()` so the same pipeline can later
be wrapped in an Azure Function or webhook handler without rewriting.

Usage:
    python scripts/run_job.py --engine trellis --input photo.jpg
    python scripts/run_job.py --engine meshroom --input ./photos/ --smoke-test

Environment overrides (defaults match the dev terraform deployment):
    AZURE_SUBSCRIPTION_ID            (else discovered via `az account show`)
    AZURE_RESOURCE_GROUP             (default: rg-3dfigurine-lab-dev-westus)
    AZURE_LOCATION                   (default: westus)
    AZURE_CONTAINER_APPS_ENV         (default: cae-3dfigurine-lab-dev)
    AZURE_FILE_STORAGE_ACCOUNT       (default: st3dfigurinelabfilesdev)
    AZURE_FILE_SHARE                 (default: jobdata)
    AZURE_FILE_STORAGE_NAME          (default: jobdata, the env-level storage)
    AZURE_CONTAINER_REGISTRY         (default: acr3dfigurinelabdev.azurecr.io)
    AZURE_WORKLOAD_PROFILE           (default: gpu-t4)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from azure.identity import DefaultAzureCredential
from azure.mgmt.appcontainers import ContainerAppsAPIClient
from azure.mgmt.appcontainers.models import (
    Container,
    ContainerResources,
    EnvironmentVar,
    Job,
    JobConfiguration,
    JobConfigurationManualTriggerConfig,
    JobTemplate,
    RegistryCredentials,
    Secret,
    Volume,
    VolumeMount,
)
from azure.storage.fileshare import ShareDirectoryClient, ShareFileClient

# Project structured logger.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.logger import get_logger, setup_logger  # noqa: E402

logger = get_logger()


# ---------- Configuration ----------

# Container Apps' GPU offerings. Quota is per workload-profile-name and
# generally available on free-trial subs (unlike ACI's V100/P100/K80).
# A100 is also available (Consumption-GPU-NC24-A100) for heavier jobs.
SUPPORTED_GPU_SKUS = ("T4", "A100")
DEFAULT_GPU_SKU = "T4"

# Map our short SKU name to the Azure workload-profile-type and the workload
# profile we provisioned in the env. Adding A100 requires also adding the
# corresponding workload profile via az / terraform.
GPU_SKU_TO_PROFILE = {
    "T4": "gpu-t4",
    "A100": "gpu-a100",
}

SUPPORTED_ENGINES = ("trellis", "meshroom")

# Resource sizing per engine. Container Apps T4 profile gives 8 vCPU / 56 GiB,
# A100 gives 24 / 220 GiB. We request a fraction of that.
CONTAINER_BASE_CONFIG = {
    "meshroom": {"image_repo": "3dfigurine-meshroom", "cpu": 4.0, "memory": "16Gi"},
    "trellis": {"image_repo": "3dfigurine-trellis", "cpu": 8.0, "memory": "56Gi"},
}


_DEFAULT_RESOURCE_GROUP = "rg-3dfigurine-lab-dev-westus"
_DEFAULT_LOCATION = "westus"
_DEFAULT_CONTAINER_APPS_ENV = "cae-3dfigurine-lab-dev"
_DEFAULT_FILE_STORAGE_ACCOUNT = "st3dfigurinelabfilesdev"
_DEFAULT_FILE_SHARE = "jobdata"
_DEFAULT_FILE_STORAGE_NAME = "jobdata"  # name registered in the env
_DEFAULT_CONTAINER_REGISTRY = "acr3dfigurinelabdev.azurecr.io"
_DEFAULT_WORKLOAD_PROFILE = "gpu-t4"


@dataclass(frozen=True)
class AzureConfig:
    """Resolved Azure resource references for the deployment environment."""

    subscription_id: str
    resource_group: str = _DEFAULT_RESOURCE_GROUP
    location: str = _DEFAULT_LOCATION
    container_apps_env: str = _DEFAULT_CONTAINER_APPS_ENV
    file_storage_account: str = _DEFAULT_FILE_STORAGE_ACCOUNT
    file_share: str = _DEFAULT_FILE_SHARE
    file_storage_name: str = _DEFAULT_FILE_STORAGE_NAME
    container_registry: str = _DEFAULT_CONTAINER_REGISTRY
    workload_profile: str = _DEFAULT_WORKLOAD_PROFILE

    @classmethod
    def from_env(
        cls,
        subscription_id: Optional[str] = None,
        resource_group: Optional[str] = None,
        location: Optional[str] = None,
        container_apps_env: Optional[str] = None,
        file_storage_account: Optional[str] = None,
        file_share: Optional[str] = None,
        container_registry: Optional[str] = None,
        workload_profile: Optional[str] = None,
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
            location=(
                location or os.getenv("AZURE_LOCATION", _DEFAULT_LOCATION)
            ),
            container_apps_env=(
                container_apps_env
                or os.getenv("AZURE_CONTAINER_APPS_ENV", _DEFAULT_CONTAINER_APPS_ENV)
            ),
            file_storage_account=(
                file_storage_account
                or os.getenv("AZURE_FILE_STORAGE_ACCOUNT", _DEFAULT_FILE_STORAGE_ACCOUNT)
            ),
            file_share=(
                file_share
                or os.getenv("AZURE_FILE_SHARE", _DEFAULT_FILE_SHARE)
            ),
            file_storage_name=(
                os.getenv("AZURE_FILE_STORAGE_NAME", _DEFAULT_FILE_STORAGE_NAME)
            ),
            container_registry=(
                container_registry
                or os.getenv("AZURE_CONTAINER_REGISTRY", _DEFAULT_CONTAINER_REGISTRY)
            ),
            workload_profile=(
                workload_profile
                or os.getenv("AZURE_WORKLOAD_PROFILE", _DEFAULT_WORKLOAD_PROFILE)
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
    """Validate inputs locally with PIL. No Azure calls."""
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
    """Upload, run, and (optionally) download a 3D-processing job on Container Apps.

    Reusable core. The CLI wraps it; future HTTP/event triggers can call it
    directly without rewriting.
    """
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"Unknown engine: {engine}. Choose from {SUPPORTED_ENGINES}")
    if gpu_sku not in SUPPORTED_GPU_SKUS:
        raise ValueError(
            f"Unsupported GPU SKU: {gpu_sku}. Choose from {SUPPORTED_GPU_SKUS}"
        )
    if max_runtime_minutes <= 0:
        raise ValueError("max_runtime_minutes must be positive")

    validate_input(input_path, engine)

    azure = azure or AzureConfig.from_env()
    runner = JobsRunner(azure)
    job_id = job_id or f"{engine}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    logger.info(f"Starting job: {job_id} (max runtime {max_runtime_minutes} min)")
    runner.upload_files(input_path, job_id)
    runner.create_or_update_job(
        job_id=job_id,
        engine=engine,
        gpu_sku=gpu_sku,
        max_runtime_minutes=max_runtime_minutes,
    )
    execution_name = runner.start_execution(job_id)
    success = runner.monitor_execution(
        job_id, execution_name, max_wait=max_runtime_minutes * 60
    )

    exit_code = 0 if success else 1
    out_dir: Optional[Path] = None
    if success and not skip_download:
        out_dir = runner.download_output(job_id, output_dir / job_id)

    if not success:
        runner.dump_logs(job_id, execution_name, output_dir / job_id / "container.log")

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


def _az_json(args: list[str]) -> dict:
    """Run `az` and return parsed JSON output."""
    proc = subprocess.run(
        ["az", *args, "-o", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


class JobsRunner:
    """Manages Container Apps Jobs with Azure Files I/O."""

    def __init__(self, azure: AzureConfig):
        self.azure = azure
        self.credential = DefaultAzureCredential()
        self.aca_client = ContainerAppsAPIClient(self.credential, azure.subscription_id)

        # Storage account key for the file share. The Azure Files data plane
        # doesn't fully support OAuth, so we use the account key.
        self._file_key = self._fetch_file_storage_key()

        # Cached lookups (filled on demand)
        self._env_id: Optional[str] = None
        self._acr_creds: Optional[tuple[str, str]] = None

        logger.info(
            f"Container Apps Jobs runner initialised "
            f"(env={azure.container_apps_env}, profile={azure.workload_profile})"
        )

    def _fetch_file_storage_key(self) -> str:
        """Fetch the Azure Files account's primary key via the management plane."""
        result = _az_json([
            "storage", "account", "keys", "list",
            "--resource-group", self.azure.resource_group,
            "--account-name", self.azure.file_storage_account,
        ])
        return result[0]["value"]

    def _get_env_id(self) -> str:
        if self._env_id is None:
            env = self.aca_client.managed_environments.get(
                self.azure.resource_group, self.azure.container_apps_env
            )
            self._env_id = env.id
        return self._env_id

    def _get_acr_credentials(self) -> tuple[str, str]:
        """Get ACR admin user/password (admin_enabled=true on the registry)."""
        if self._acr_creds is None:
            acr_name = self.azure.container_registry.split(".")[0]
            creds = _az_json([
                "acr", "credential", "show", "--name", acr_name,
            ])
            user = creds["username"]
            pwd = creds["passwords"][0]["value"]
            self._acr_creds = (user, pwd)
        return self._acr_creds

    # ---------- File share I/O ----------

    def _share_dir(self, dir_path: str) -> ShareDirectoryClient:
        return ShareDirectoryClient(
            account_url=f"https://{self.azure.file_storage_account}.file.core.windows.net",
            share_name=self.azure.file_share,
            directory_path=dir_path,
            credential=self._file_key,
        )

    def _share_file(self, file_path: str) -> ShareFileClient:
        return ShareFileClient(
            account_url=f"https://{self.azure.file_storage_account}.file.core.windows.net",
            share_name=self.azure.file_share,
            file_path=file_path,
            credential=self._file_key,
        )

    def _ensure_directory(self, dir_path: str) -> None:
        """Create the directory tree (and parents) idempotently."""
        from azure.core.exceptions import ResourceExistsError
        parts = [p for p in dir_path.split("/") if p]
        cumulative = ""
        for part in parts:
            cumulative = f"{cumulative}/{part}" if cumulative else part
            try:
                self._share_dir(cumulative).create_directory()
            except ResourceExistsError:
                pass

    def upload_files(self, source: Path, job_id: str) -> None:
        """Upload input files to inputs/<job-id>/ on the file share."""
        target_prefix = f"inputs/{job_id}"
        self._ensure_directory(target_prefix)
        # Make sure the outputs dir exists so the container can write into it.
        self._ensure_directory(f"outputs/{job_id}")

        if source.is_file():
            self._upload_one(source, f"{target_prefix}/{source.name}")
        elif source.is_dir():
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(source)
                    # Flatten subdirectories for the container's --directory mode
                    # (main.py recurses anyway).
                    self._ensure_directory(str(Path(target_prefix) / rel.parent))
                    self._upload_one(path, f"{target_prefix}/{rel.as_posix()}")
        else:
            raise FileNotFoundError(f"Path does not exist: {source}")

    def _upload_one(self, local: Path, remote_path: str) -> None:
        with open(local, "rb") as fh:
            self._share_file(remote_path).upload_file(fh)
        logger.info(f"Uploaded: {remote_path}")

    # ---------- Job submission ----------

    def create_or_update_job(
        self,
        job_id: str,
        engine: str,
        gpu_sku: str,
        max_runtime_minutes: int,
    ) -> None:
        if engine not in CONTAINER_BASE_CONFIG:
            raise ValueError(f"Unknown engine: {engine}")
        cfg = CONTAINER_BASE_CONFIG[engine]
        image = f"{self.azure.container_registry}/{cfg['image_repo']}:latest"
        workload_profile = GPU_SKU_TO_PROFILE.get(gpu_sku, self.azure.workload_profile)

        acr_user, acr_pwd = self._get_acr_credentials()
        env_id = self._get_env_id()

        logger.info(
            f"Creating Container Apps Job: {job_id} "
            f"(engine={engine}, profile={workload_profile})"
        )

        job = Job(
            location=self.azure.location,
            environment_id=env_id,
            workload_profile_name=workload_profile,
            configuration=JobConfiguration(
                trigger_type="Manual",
                replica_timeout=max_runtime_minutes * 60,
                replica_retry_limit=0,
                manual_trigger_config=JobConfigurationManualTriggerConfig(
                    replica_completion_count=1,
                    parallelism=1,
                ),
                registries=[
                    RegistryCredentials(
                        server=self.azure.container_registry,
                        username=acr_user,
                        password_secret_ref="acr-pwd",
                    ),
                ],
                secrets=[Secret(name="acr-pwd", value=acr_pwd)],
            ),
            template=JobTemplate(
                containers=[
                    Container(
                        name=engine,
                        image=image,
                        resources=ContainerResources(
                            cpu=cfg["cpu"],
                            memory=cfg["memory"],
                        ),
                        env=[
                            EnvironmentVar(name="JOB_ID", value=job_id),
                            EnvironmentVar(name="ENGINE", value=engine),
                            EnvironmentVar(
                                name="HF_HOME",
                                value="/workspace/.cache/huggingface",
                            ),
                            EnvironmentVar(
                                name="TRANSFORMERS_CACHE",
                                value="/workspace/.cache/huggingface",
                            ),
                            EnvironmentVar(
                                name="HF_TOKEN",
                                value=os.getenv("HF_TOKEN", ""),
                            ),
                        ],
                        # Override the Dockerfile's CMD so the entrypoint
                        # script runs main.py with our --directory and --output.
                        # (Both Dockerfiles ENTRYPOINT to entrypoint.sh which
                        # exec's whatever we pass as args.)
                        args=[
                            "python3",
                            "main.py",
                            "--engine",
                            engine,
                            "--directory",
                            f"/workspace/inputs/{job_id}",
                            "--output",
                            f"/workspace/outputs/{job_id}",
                        ],
                        volume_mounts=[
                            VolumeMount(
                                volume_name="jobdata",
                                mount_path="/workspace",
                            ),
                        ],
                    ),
                ],
                volumes=[
                    Volume(
                        name="jobdata",
                        storage_type="AzureFile",
                        storage_name=self.azure.file_storage_name,
                    ),
                ],
            ),
        )

        poller = self.aca_client.jobs.begin_create_or_update(
            self.azure.resource_group, job_id, job
        )
        poller.result()
        logger.info(f"Job spec ready: {job_id}")

    def start_execution(self, job_id: str) -> str:
        poller = self.aca_client.jobs.begin_start(self.azure.resource_group, job_id)
        execution = poller.result()
        logger.info(f"Started execution: {execution.name}")
        return execution.name

    def monitor_execution(
        self,
        job_id: str,
        execution_name: str,
        poll_interval: int = 10,
        max_wait: int = 1800,
    ) -> bool:
        """Poll the execution until terminal state or max_wait elapses."""
        start = time.time()
        last_state = None
        while time.time() - start < max_wait:
            try:
                execution = self.aca_client.job_execution(
                    self.azure.resource_group, job_id, execution_name
                )
                state = (
                    execution.properties.status
                    if hasattr(execution, "properties") and execution.properties
                    else getattr(execution, "status", None)
                )
                if state != last_state:
                    elapsed = int(time.time() - start)
                    logger.info(
                        f"Execution {execution_name}: {state} ({elapsed}s elapsed)"
                    )
                    last_state = state
                if state in ("Succeeded", "Failed", "Stopped", "Degraded"):
                    return state == "Succeeded"
                time.sleep(poll_interval)
            except Exception as e:
                logger.warning(f"Monitor error: {e}")
                time.sleep(poll_interval)
        logger.error(
            f"Execution {execution_name} exceeded {max_wait}s runtime cap"
        )
        return False

    def download_output(self, job_id: str, target: Path) -> Path:
        """Download outputs/<job-id>/* from the share into `target`."""
        target.mkdir(parents=True, exist_ok=True)
        remote_prefix = f"outputs/{job_id}"
        self._download_dir_recursive(remote_prefix, target)
        return target

    def _download_dir_recursive(self, remote_dir: str, local_dir: Path) -> None:
        local_dir.mkdir(parents=True, exist_ok=True)
        dir_client = self._share_dir(remote_dir)
        for entry in dir_client.list_directories_and_files():
            rel_name = entry["name"]
            remote_path = f"{remote_dir}/{rel_name}"
            local_path = local_dir / rel_name
            if entry.get("is_directory"):
                self._download_dir_recursive(remote_path, local_path)
            else:
                data = self._share_file(remote_path).download_file().readall()
                local_path.write_bytes(data)
                logger.info(f"Downloaded: {local_path}")

    def cleanup(self, job_id: str) -> None:
        """Delete the Job resource. Doesn't touch the file share content
        (kept for inspection)."""
        logger.info(f"Cleaning up job spec: {job_id}")
        try:
            self.aca_client.jobs.begin_delete(
                self.azure.resource_group, job_id
            ).result()
            logger.info(f"Deleted job: {job_id}")
        except Exception as e:
            logger.warning(f"Could not delete job {job_id}: {e}")

    def dump_logs(self, job_id: str, execution_name: str, target: Path) -> None:
        """Best-effort: pull the container logs via az CLI (Log Analytics)."""
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [
                    "az", "containerapp", "job", "logs", "show",
                    "--name", job_id,
                    "--resource-group", self.azure.resource_group,
                    "--container", job_id.split("-")[0],  # 'trellis' / 'meshroom'
                    "--follow", "false",
                    "-o", "tsv",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            target.write_text(result.stdout or result.stderr)
            logger.info(f"Saved container logs to {target}")
        except Exception as e:
            logger.warning(f"Could not fetch logs for {job_id}: {e}")


# ---------- CLI ----------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Submit 3D processing jobs to Azure Container Apps Jobs",
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
        help=f"GPU type (default: {DEFAULT_GPU_SKU}). T4=cheap, A100=fast/big.",
    )
    p.add_argument(
        "--skip-download",
        action="store_true",
        help="Don't download results after job completes",
    )
    p.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete the Job resource after completion",
    )
    p.add_argument(
        "--max-runtime-minutes",
        type=int,
        default=30,
        help="Hard cap on job runtime (default: 30).",
    )
    p.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "Cheap sanity-check run: forces --gpu-sku T4, "
            "--max-runtime-minutes 10, --cleanup."
        ),
    )
    p.add_argument(
        "--validate-only",
        action="store_true",
        help="Run client-side input validation and exit (no Azure calls).",
    )
    p.add_argument("--resource-group", help="Override AZURE_RESOURCE_GROUP")
    p.add_argument("--registry", help="Override AZURE_CONTAINER_REGISTRY")
    p.add_argument("--subscription", help="Override AZURE_SUBSCRIPTION_ID")
    p.add_argument("--location", help="Override AZURE_LOCATION")
    p.add_argument(
        "--workload-profile",
        help="Override AZURE_WORKLOAD_PROFILE (default: gpu-t4).",
    )
    return p


def main() -> int:
    setup_logger(log_dir="./logs", level="INFO")
    global logger
    logger = get_logger()

    args = _build_parser().parse_args()

    if args.validate_only:
        try:
            validate_input(args.input, args.engine)
        except (FileNotFoundError, ValueError) as e:
            print(f"Validation failed: {e}", file=sys.stderr)
            return 2
        logger.info("Validation passed; no job submitted (--validate-only).")
        return 0

    gpu_sku = args.gpu_sku
    max_runtime = args.max_runtime_minutes
    cleanup = args.cleanup
    if args.smoke_test:
        # T4 is the cheap GPU on Container Apps. Bump the timeout to 10 min
        # so first-time HuggingFace model downloads have a chance.
        gpu_sku = "T4"
        max_runtime = min(args.max_runtime_minutes, 10)
        cleanup = True
        logger.info(
            f"Smoke-test mode: gpu={gpu_sku}, max_runtime={max_runtime}min, cleanup=True"
        )

    azure = AzureConfig.from_env(
        subscription_id=args.subscription,
        resource_group=args.resource_group,
        location=args.location,
        container_registry=args.registry,
        workload_profile=args.workload_profile,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
