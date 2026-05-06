# Azure Container Instances (ACI) Deployment Guide

This guide explains how to use Azure Container Instances for batch 3D processing instead of persistent VMs.

## Architecture Overview

The deployment uses:
- **Azure Storage Account** - Input/Output/Logs blob containers
- **Azure Container Registry** - Private Docker image repository
- **Azure Container Instances** - On-demand batch processing containers (GPU-enabled)
- **Key Vault** - Secret storage
- **Log Analytics + Application Insights** - Monitoring

No persistent VM infrastructure is required for batch processing jobs.

## Prerequisites

1. **Azure CLI** authenticated:
   ```bash
   az login
   az account set --subscription <SUBSCRIPTION_ID>
   ```

2. **Terraform** `~> 1.0`:
   ```bash
   terraform --version
   ```

3. **Python 3.10+** with the client dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements-client.txt
   ```

## Deployment

### 1. Deploy Infrastructure

```bash
cd terraform/
terraform init
terraform apply -var-file="dev.tfvars"
```

This creates:
- Resource Group: `rg-3dfigurine-lab-dev-eastus`
- Storage Account: `st3dfigurinelabdev`
- Container Registry: `acr3dfigurinelabdev`
- Key Vault: `kv-3dfigurine-lab-dev`
- Log Analytics Workspace: `law-3dfigurine-lab-dev`

### 2. Build runtime images in ACR

`az acr build` builds the image inside Azure — no local Docker daemon
required, so this works from any laptop:

```bash
az acr build --registry acr3dfigurinelabdev \
  --image 3dfigurine-meshroom:latest \
  -f docker/Dockerfile.meshroom .

az acr build --registry acr3dfigurinelabdev \
  --image 3dfigurine-trellis:latest \
  -f docker/Dockerfile.trellis .
```

## Submitting Jobs

### Using the ACI Job Runner

```bash
# Single file processing
python3 scripts/run_job.py \
  --engine meshroom \
  --input /path/to/model.obj

# Directory processing  
python3 scripts/run_job.py \
  --engine meshroom \
  --input /path/to/image/directory

# Custom job ID
python3 scripts/run_job.py \
  --engine trellis \
  --input model.obj \
  --job-id my-custom-job-id

# Skip automatic output download
python3 scripts/run_job.py \
  --engine meshroom \
  --input images/ \
  --skip-download

# Auto-cleanup container after completion
python3 scripts/run_job.py \
  --engine meshroom \
  --input images/ \
  --cleanup
```

### Job Output

Processing results are automatically downloaded to `output/` directory after completion.

To manually download outputs:
```bash
az storage blob download-batch \
  --account-name st3dfigurinelabdev \
  --source output \
  --destination ./output/
```

## Managing Jobs

### List Running Jobs
```bash
az container list --resource-group rg-3dfigurine-lab-dev-eastus --output table
```

### View Logs
```bash
az container logs --resource-group rg-3dfigurine-lab-dev-eastus --name <JOB_ID>
```

### Stop/Delete a Job
```bash
az container delete \
  --resource-group rg-3dfigurine-lab-dev-eastus \
  --name <JOB_ID>
```

## Configuration

### Supported Job Types

| Type | Image | CPU | Memory | GPU (default) |
|------|-------|-----|--------|---------------|
| `meshroom` | 3dfigurine-meshroom | 4 | 16 GB | V100 |
| `trellis` | 3dfigurine-trellis | 4 | 16 GB | V100 |

Override the GPU per-run with `--gpu-sku V100` (faster) or `--gpu-sku T4`
(cheaper). The previous K80 SKU was retired by Azure in 2023.

Customize defaults in `scripts/run_job.py` under `CONTAINER_BASE_CONFIG`.

### Storage Containers

- **input** - Upload source files here
- **output** - Download processed results  
- **logs** - Job execution logs

## Troubleshooting

### "Job stuck in 'Creating' state"
```bash
# Check container group status
az container show \
  --resource-group rg-3dfigurine-lab-dev-eastus \
  --name <JOB_ID> \
  --query "containers[0].instanceView"
```

### "Operation could not be completed (403 error)"
This is usually a transient Azure authentication issue. Retry the command.

### "Could not find image in registry"
Push your Docker images to ACR first:
```bash
cd /home/aswinak/Projects/3dPrintingBusiness
az acr build --registry acr3dfigurinelabdev --image <IMAGE_NAME>:latest -f docker/Dockerfile.meshroom .
```

## Cost Optimization

ACI pricing is based on:
- **vCPU-seconds** - 4 vCPUs per job
- **Memory-seconds** - 16 GB per job
- **GPU-hours** - V100 (default) or T4 allocation

V100 is roughly $3/hour; T4 is roughly $0.50/hour. A typical 30-minute
job costs $0.25–$1.50. Use `--gpu-sku T4` for iteration and
non-time-critical work.

To reduce costs:
- Use smaller job configurations for less demanding tasks
- Process multiple files per job
- Delete completed jobs with `--cleanup` flag

## Scaling

Run up to 10+ parallel jobs by submitting multiple instances:

```bash
for dir in images/batch_*; do
  python3 scripts/run_job.py \
    --engine meshroom \
    --input "$dir" &
done
wait  # Wait for all jobs to complete
```

## Integration with CI/CD

Example GitHub Actions workflow:

```yaml
name: Process Figurines

on: [workflow_dispatch]

jobs:
  process:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Azure Login
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Submit Job
        run: |
          python3 scripts/run_job.py \
            --engine meshroom \
            --input images/

      - name: Download Results
        uses: actions/upload-artifact@v2
        with:
          name: processed-output
          path: output/
```

## Further Reading

- [Azure Container Instances Documentation](https://docs.microsoft.com/en-us/azure/container-instances/)
- [Azure Storage Blobs](https://docs.microsoft.com/en-us/azure/storage/blobs/)
- [Azure Container Registry](https://docs.microsoft.com/en-us/azure/container-registry/)
