# Docker / Container Build Reference

This pipeline builds runtime images on **GitHub Actions** and pushes them to your Azure Container Registry. No local Docker daemon required. Use this reference when changing engine code or runtime dependencies.

> **Why not `az acr build`?** It's restricted on free / trial / $200-credit subscriptions (`TasksOperationsNotAllowed`). GitHub Actions are free and unrestricted. See [docs/github-actions-setup.md](docs/github-actions-setup.md) for the one-time setup.

## Trigger a build

Two ways:

**Automatic** — any push to `main` that touches `docker/**`, `engines/**`, `utils/**`, `main.py`, `config.yaml`, or `requirements-runtime.txt` fires the workflow.

**Manual** — GitHub repo → **Actions → Build runtime images → Run workflow**. You can choose which image(s) to build.

Build time: ~25–40 minutes the first time (downloads CUDA + PyTorch); ~5–10 minutes on subsequent runs (buildcache stored in ACR).

## If `az acr build` *is* available on your subscription

You can still use it directly — the Dockerfiles are unchanged:

```bash
az acr build --registry acr3dfigurinelabdev \
  --image 3dfigurine-trellis:latest \
  -f docker/Dockerfile.trellis .
```

If this works for you, the GitHub Actions workflow is just a redundant safety net.

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
