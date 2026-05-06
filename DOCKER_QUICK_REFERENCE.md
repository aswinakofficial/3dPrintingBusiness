# Docker / Container Build Reference

This pipeline builds runtime images **in Azure Container Registry (ACR)** via `az acr build` — no local Docker daemon is required. Use this reference when changing engine code or runtime dependencies.

## Build images in ACR

From the repo root:

```bash
# TRELLIS.2 (single-image / multi-view 3D)
az acr build --registry acr3dfigurinelabdev \
  --image 3dfigurine-trellis:latest \
  -f docker/Dockerfile.trellis .

# Meshroom (photogrammetry from 10–50 images)
az acr build --registry acr3dfigurinelabdev \
  --image 3dfigurine-meshroom:latest \
  -f docker/Dockerfile.meshroom .
```

Build time on the ACR side is ~5–10 minutes for a clean build, ~1–2 minutes when only the application layers change.

## Tagging a release

```bash
az acr build --registry acr3dfigurinelabdev \
  --image 3dfigurine-trellis:v1.0 \
  --image 3dfigurine-trellis:latest \
  -f docker/Dockerfile.trellis .
```

Pin a specific tag in `scripts/run_job.py` `CONTAINER_BASE_CONFIG` if you want jobs to use a versioned image rather than `:latest`.

## What lives where

| File | Purpose |
|---|---|
| `docker/Dockerfile.trellis` | TRELLIS.2 runtime image |
| `docker/Dockerfile.meshroom` | Meshroom runtime image |
| `docker/shared/Dockerfile.base` | Shared CUDA base |
| `requirements-runtime.txt` | Heavy ML/3D deps installed in the images |
| `main.py` | Entry point that runs inside the container |
| `config.yaml` | Read by `main.py` at runtime |

## Running a built image

You don't run images locally — submit them via ACI:

```bash
python scripts/run_job.py --engine trellis --input ./photo.jpg
```

`run_job.py` reads `AZURE_CONTAINER_REGISTRY` (default `acr3dfigurinelabdev.azurecr.io`) to construct the image reference.

## Cache notes

- ACR caches layers between builds, so editing `main.py` rebuilds only the application layer (~30 seconds).
- Editing `requirements-runtime.txt` invalidates the dependency layer (~5–10 minutes).
- Editing the base CUDA stage invalidates everything (~10–15 minutes).

## Troubleshooting

**Build fails with `manifest unknown`** — the registry name in `--registry` doesn't match what Terraform created. Run `terraform output container_registry_name` to confirm.

**Build hangs on `Sending build context`** — a large file is being uploaded. Check `.dockerignore` excludes `input/`, `output/`, `venv/`, `logs/`.

**Image too large** — runtime images should be 8–12 GB. If yours is larger, check that `pip` cache and `apt` lists are cleaned (`rm -rf /var/lib/apt/lists/*`, `pip install --no-cache-dir`).
