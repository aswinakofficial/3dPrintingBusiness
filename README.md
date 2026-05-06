# 3D Figurine Lab — Production Pipeline

Convert customer photos to print-ready 3D figurine STL files using two AI engines (TRELLIS.2 + Meshroom). Cloud-only, on-demand: a thin CLI runs on your laptop and submits jobs to Azure Container Instances (ACI). No persistent compute — you pay only while a job runs.

## Quick Start

You don't need a GPU, CUDA, or Docker installed locally. The CLI client is a small Python package; all heavy work happens inside ACI.

### Prerequisites
- Python 3.10+
- Azure CLI (`az login` against a subscription with ACI quota)
- Terraform 1.0+ (only for the one-time infra setup)

### Install the client
```bash
git clone https://github.com/yourusername/3dPrintingBusiness.git
cd 3dPrintingBusiness
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-client.txt
```

### One-time infrastructure
```bash
cd terraform
terraform init
terraform apply -var-file="dev.tfvars"
cd ..

# Cloud-side build of the runtime images (no local Docker required)
az acr build --registry acr3dfigurinelabdev --image 3dfigurine-trellis:latest -f docker/Dockerfile.trellis .
az acr build --registry acr3dfigurinelabdev --image 3dfigurine-meshroom:latest -f docker/Dockerfile.meshroom .
```

### Run a job
```bash
# Single image with TRELLIS.2 (fast, 1–4 images)
python scripts/run_job.py --engine trellis --input ./photo.jpg

# Photogrammetry with Meshroom (10–50 overlapping images)
python scripts/run_job.py --engine meshroom --input ./photos/

# Cheaper GPU when iterating
python scripts/run_job.py --engine trellis --input ./photo.jpg --gpu-sku T4
```

The CLI uploads inputs to blob storage, spins up an ACI container with GPU, streams progress, downloads the STL into `./output/`, and (with `--cleanup`) deletes the container group when done.

## Output

Each job produces:
- `output/<job-id>/final_mesh.glb` — the generated mesh
- `output/<job-id>/final_mesh.stl` — print-ready STL (binary)
- `output/<job-id>/metadata.json` — engine, mesh stats, post-processing settings
- `logs/pipeline_*.log` — JSON-structured logs

## Configuration

Edit `config.yaml` to customize what runs **inside the container**:
- Engine settings (resolution, max images, model IDs)
- Mesh repair (hole size, manifold validation)
- Hollowing parameters (wall thickness, voxel resolution)
- Support generation (overhang angle, diameter)
- Print profiles (figurine sizes)

The CLI client (`scripts/run_job.py`) does not read `config.yaml`; it only orchestrates. Per-run knobs live as CLI flags (`--gpu-sku`, `--cleanup`, etc.).

## Repository layout

```
3dPrintingBusiness/
├── scripts/
│   └── run_job.py              # ⭐ User-facing CLI — what you run
├── main.py                     # Pipeline orchestrator (runs INSIDE the container)
├── config.yaml                 # Container-side configuration
├── requirements-client.txt     # Lightweight CLI client deps (this is what you install)
├── requirements-runtime.txt    # Heavy ML deps — only installed inside the Docker images
├── requirements-dev.txt        # Dev tooling and tests
│
├── engines/
│   ├── base_engine.py          # Abstract engine interface
│   ├── trellis_v2.py           # TRELLIS.2 implementation
│   ├── meshroom_sfm.py         # Meshroom Structure-from-Motion
│   └── multiview_generator.py  # Zero123++ novel-view synthesis
│
├── utils/
│   ├── logger.py               # Structured JSON logger
│   ├── pre_processor.py        # Image validation & background removal
│   └── post_processor.py       # Mesh repair, hollowing, supports
│
├── docker/
│   ├── Dockerfile.trellis      # TRELLIS.2 runtime image
│   ├── Dockerfile.meshroom     # Meshroom runtime image
│   └── shared/Dockerfile.base  # Shared CUDA base
│
├── terraform/                  # Azure infrastructure (storage, ACR, key vault)
│
├── input/  output/  logs/      # Local working dirs (gitignored)
└── tests/                      # CPU-only unit tests
```

## Engine choice

| Aspect | TRELLIS.2 | Meshroom |
|---|---|---|
| **Inputs** | 1–4 images | 10–50 overlapping images |
| **Speed** | seconds | 10–35 minutes |
| **Style** | Stylized, clean, textured | Photorealistic geometry |
| **GPU memory** | 24 GB+ (V100) | 8–16 GB (V100 or T4) |
| **Best for** | Single product shots, character refs | Real-world scans, busts |

The `--gpu-sku` flag (default `V100`) accepts `V100` or `T4`. T4 is roughly 1/6 the cost of V100; use it for iteration and Meshroom jobs.

## Cost notes

- Storage account, ACR, Key Vault, Log Analytics: persistent, ~$1–2/month.
- ACI: pay-per-second only while a job runs. V100 ≈ $3/hour, T4 ≈ $0.50/hour.
- Containers in `Failed`/`Succeeded` state don't bill but linger in the resource group — pass `--cleanup` to delete them automatically, or run `python scripts/cleanup_old_jobs.py` periodically.

A budget alert is provisioned by Terraform; tune the cap in `terraform/dev.tfvars`.

## Container internals (for contributors)

The runtime images are built by `az acr build` from `docker/Dockerfile.{trellis,meshroom}`. Inside, `main.py` is the orchestrator: validation → preprocessing → engine inference → mesh post-processing → STL export.

To iterate on engine code, push to ACR and submit a smoke-test job:
```bash
az acr build --registry acr3dfigurinelabdev --image 3dfigurine-trellis:latest -f docker/Dockerfile.trellis .
python scripts/run_job.py --engine trellis --input ./input/test.jpg --gpu-sku T4 --cleanup
```

## Development

```bash
# CPU-only tests (no GPU required)
pip install -r requirements-dev.txt
pytest tests/ -v

# Style
black .
flake8 .

# Install pre-commit hooks (runs black/flake8/terraform-fmt and a
# tfstate-leak guard before every commit)
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

CI (GitHub Actions) runs lint, the trigger-script import check, the CPU test suite, and `terraform validate` on every PR. CI is your primary pre-flight gate before paying for an ACI run.

## License

Proprietary — 3D Printing Business.

## Support

For issues or feature requests, contact: support@3dprintingbusiness.com
