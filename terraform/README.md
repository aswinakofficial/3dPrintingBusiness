# Terraform Deployment Guide - 3D Figurine Lab

This Terraform module provisions the shared Azure infrastructure for the 3D Figurine Lab batch pipeline. It does not create persistent compute. Processing jobs are submitted separately as Azure Container Instances (ACI) from the repository root with `scripts/aci_job_runner.py`.

## What Terraform Creates

- Resource group
- Storage account
- Blob containers: `input`, `output`, `logs`
- Azure Container Registry (ACR)
- Key Vault
- Log Analytics workspace
- Application Insights when monitoring is enabled

## Prerequisites

- Terraform 1.0+
- Azure CLI authenticated with a subscription that can create the required Azure resources
- Python 3.8+ if you plan to submit ACI jobs with `scripts/aci_job_runner.py`

Optional local dependencies for the helper script:

```bash
python3 -m venv venv
source venv/bin/activate
pip install azure-identity azure-mgmt-containerinstance azure-storage-blob
```

## File Layout

```text
terraform/
├── providers.tf
├── variables.tf
├── main.tf
├── outputs.tf
├── terraform.tfvars
├── dev.tfvars
├── staging.tfvars
├── deploy.sh
└── README.md
```

## Supported Variables

The current module supports these operator-facing inputs:

```hcl
project_name           = "3dfigurine-lab"
environment            = "prod"            # dev, staging, prod
location               = "eastus"
storage_access_tier    = "Hot"             # Hot, Cool
storage_sku            = "Premium_LRS"
container_registry_sku = "Premium"         # Basic, Standard, Premium
enable_monitoring      = true
log_retention_days     = 30

container_images = {
  trellis  = "myregistry.azurecr.io/3dfigurine-trellis:latest"
  meshroom = "myregistry.azurecr.io/3dfigurine-meshroom:latest"
}

tags = {
  Project     = "3D Figurine Lab"
  Environment = "prod"
  ManagedBy   = "Terraform"
  CostCenter  = "Engineering"
}
```

## Deploy Shared Infrastructure

Run Terraform from the `terraform/` directory:

```bash
cd /home/aswinak/Projects/3dPrintingBusiness/terraform

terraform init
terraform plan -var-file="dev.tfvars"
terraform apply -var-file="dev.tfvars"
```

Use `staging.tfvars` or `terraform.tfvars` for the other environments.

Typical deployment time is around 5-10 minutes because this module creates only shared platform resources.

## Useful Outputs

```bash
terraform output deployment_summary
terraform output resource_group_name
terraform output container_registry_login_server
terraform output storage_account_name
terraform output key_vault_name
```

The sensitive outputs include the storage connection string and ACR admin password.

## Build and Push Container Images

Run image builds from the repository root, not from `terraform/`.

```bash
cd /home/aswinak/Projects/3dPrintingBusiness

docker build -f docker/Dockerfile.meshroom -t 3dfigurine-meshroom:latest .
az acr build --registry acr3dfigurinelabdev --image 3dfigurine-meshroom:latest -f docker/Dockerfile.meshroom .

docker build -f docker/Dockerfile.trellis -t 3dfigurine-trellis:latest .
az acr build --registry acr3dfigurinelabdev --image 3dfigurine-trellis:latest -f docker/Dockerfile.trellis .
```

If you deploy a different environment, replace the registry name with the Terraform output for that environment.

## Submit ACI Jobs

After infrastructure and images are ready, submit jobs from the repository root:

```bash
cd /home/aswinak/Projects/3dPrintingBusiness

python3 scripts/aci_job_runner.py \
  --job-type meshroom \
  --input-dir /path/to/images
```

See `../ACI_DEPLOYMENT.md` for the end-to-end ACI workflow.

## Verification

Check the Terraform state:

```bash
terraform state list
terraform output deployment_summary
```

Check Azure resources:

```bash
RG=$(terraform output -raw resource_group_name)
az resource list --resource-group "$RG" --output table
```

Check running ACI jobs after submission:

```bash
az container list --resource-group "$RG" --output table
```

## State Management

By default, state is stored locally in `terraform.tfstate`. Do not commit this file.

For team use, switch to a remote Azure Storage backend in `providers.tf` and then run:

```bash
terraform init
```

## Troubleshooting

### Global name collision

Storage accounts and ACR names must be globally unique. If creation fails, change `project_name` and apply again.

### Provider authentication issues

Run:

```bash
az login
az account show
```

### Stale plan file

If `tfplan` no longer matches the configuration, delete it and re-run `terraform plan`.

### Missing image in ACR

Make sure you ran the image build from the repository root and passed the correct Dockerfile path:

```bash
az acr build --registry <REGISTRY_NAME> --image 3dfigurine-meshroom:latest -f docker/Dockerfile.meshroom .
```

## Cleanup

Preview a full destroy:

```bash
terraform plan -destroy -var-file="dev.tfvars"
```

Destroy all Terraform-managed resources:

```bash
terraform destroy -var-file="dev.tfvars"
```
