# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Terraform Module Does

This module provisions the **shared Azure infrastructure** for the 3D Figurine Lab batch pipeline. It creates no persistent compute — batch processing runs on on-demand Azure Container Instances submitted separately via `../scripts/run_job.py`.

Resources created:
- Resource Group, Storage Account (Standard + Premium Files), Blob containers (`input`/`output`/`logs`), Azure Files share
- Azure Container Registry (ACR)
- Key Vault, Log Analytics Workspace, Application Insights (optional), Monitor Action Group
- Azure Container Apps Environment (for Container Apps job execution)

## Common Commands

```bash
# Initialize (only needed once or after provider changes)
terraform init

# Plan against a specific environment
terraform plan -var-file="dev.tfvars"
terraform plan -var-file="staging.tfvars"
terraform plan -var-file="terraform.tfvars"   # production

# Apply
terraform apply -var-file="dev.tfvars"

# Interactive deployment script (handles auth check + env selection)
./deploy.sh

# Inspect outputs after apply
terraform output deployment_summary
terraform output -raw container_registry_login_server
terraform output -raw resource_group_name

# Validate / format
terraform validate
terraform fmt -recursive

# Destroy (preview first)
terraform plan -destroy -var-file="dev.tfvars"
terraform destroy -var-file="dev.tfvars"
```

## Environments and tfvars Files

| File | Environment | Location | ACR SKU | Storage SKU |
|------|-------------|----------|---------|-------------|
| `dev.tfvars` | dev | westus | Basic | Standard_LRS |
| `staging.tfvars` | staging | eastus | Premium | Premium_LRS |
| `terraform.tfvars` | prod | eastus | Premium | Premium_LRS |

## Resource Naming Convention

All names are derived from `project_name` + `environment`:
- Resource Group: `rg-{project_name}-{environment}-{location}`
- Storage Account: `st{project_name_no_dashes}{environment}` (globally unique — no hyphens)
- ACR: `acr{project_name_no_dashes}{environment}` (globally unique)
- Key Vault: `kv-{project_name}-{environment}`
- Log Analytics: `law-{project_name}-{environment}`
- Container Apps Env: `cae-{project_name}-{environment}`

If `terraform apply` fails on storage or ACR creation, the name likely collides with an existing global resource. Change `project_name` in the relevant tfvars file.

## Architecture: Terraform vs ACI Job Runner

Terraform provisions shared platform infrastructure only. Batch jobs are **not** managed by Terraform:

```
Terraform (this directory)          scripts/run_job.py (repo root)
─────────────────────────           ──────────────────────────────────────
Storage Account + Containers   →    Upload inputs, download outputs
Container Registry             →    Pull container images
Container Apps Environment     →    Not used by ACI runner (future path)
Key Vault + Monitoring         →    Available to containers at runtime
                                    Create/monitor/delete ACI container groups
```

To submit a batch job after infrastructure is deployed:
```bash
cd ..   # repo root
python3 scripts/run_job.py --engine meshroom --input /path/to/images
python3 scripts/run_job.py --engine trellis --input model.obj --cleanup
```

Per-engine container configs (CPU, memory, image repo) live in `scripts/run_job.py` under `CONTAINER_BASE_CONFIG`. The GPU SKU is per-call via the `--gpu-sku {V100,T4}` flag.

## State Management

State is stored locally in `terraform.tfstate` by default. **Do not commit this file.**

To switch to remote state (required for team use), uncomment the `backend "azurerm"` block in `providers.tf` and run `terraform init`.

## Building and Pushing Container Images

Image builds run from the **repository root**, not from `terraform/`:
```bash
cd ..
az acr build --registry <ACR_NAME> --image 3dfigurine-meshroom:latest -f docker/Dockerfile.meshroom .
az acr build --registry <ACR_NAME> --image 3dfigurine-trellis:latest  -f docker/Dockerfile.trellis  .
```

Get `<ACR_NAME>` from `terraform output -raw container_registry_name`.

## Key Provider Behavior

- `azurerm ~> 3.0` — do not upgrade to 4.x without testing; resource schema differs
- `skip_provider_registration = true` — assumes the subscription already has required resource providers registered
- `prevent_deletion_if_contains_resources = false` — resource group can be deleted even when non-empty; safe for dev teardown
