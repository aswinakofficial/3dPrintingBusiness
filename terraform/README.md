# Terraform Deployment Guide - 3D Figurine Lab

Complete guide for deploying to Azure using Terraform Infrastructure-as-Code.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [File Structure](#file-structure)
4. [Configuration](#configuration)
5. [Deployment Steps](#deployment-steps)
6. [Verification](#verification)
7. [State Management](#state-management)
8. [Troubleshooting](#troubleshooting)
9. [Cleanup](#cleanup)

## Prerequisites

### Required Tools
```bash
# Terraform (v1.0+)
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo apt-key add -
sudo apt-add-repository "deb [arch=amd64] https://apt.releases.hashicorp.com $(lsb_release -cs) main"
sudo apt-get update && sudo apt-get install terraform

# Verify installation
terraform --version
# Expected: Terraform v1.0.0+

# Azure CLI (v2.40+)
curl -sL https://aka.ms/InstallAzureCLIDeb | bash

# Verify
az --version
```

### Azure Setup
- Active Azure subscription with GPU quota
- Azure CLI authenticated: `az login`
- SSH key pair: `ssh-keygen -t rsa -b 4096 -f ~/.ssh/azure_3dfigurine -N ""`

## Quick Start

```bash
# Navigate to terraform directory
cd terraform/

# Initialize Terraform (download providers)
terraform init

# Review what will be deployed (production environment)
terraform plan -var-file="terraform.tfvars"

# Deploy (requires approval)
terraform apply -var-file="terraform.tfvars"

# Get outputs (connection details)
terraform output deployment_summary
terraform output vm_ssh_command
```

## File Structure

```
terraform/
├── providers.tf         ← Azure provider configuration
├── variables.tf         ← Input variables with validation
├── main.tf              ← Resource definitions
├── outputs.tf           ← Output values
├── terraform.tfvars     ← Production defaults
├── dev.tfvars          ← Development environment
├── staging.tfvars      ← Staging environment
├── .gitignore          ← Git ignore patterns
└── README.md           ← This file

# After deployment:
├── .terraform/         ← Provider cache (auto-generated)
├── terraform.tfstate   ← Local state file (if using local backend)
└── terraform.tfstate.backup ← State backup
```

## Configuration

### Available Variables

Edit `terraform.tfvars` to customize:

```hcl
project_name            = "3dfigurine-lab"    # Resource naming prefix
environment             = "prod"               # dev, staging, prod
location                = "eastus"             # Azure region
vm_size                 = "Standard_NC24ads_A100_v4"  # GPU VM size
container_registry_sku  = "Premium"            # Basic, Standard, Premium
storage_sku             = "Premium_LRS"        # Storage tier
enable_monitoring       = true                 # Enable AppInsights
log_retention_days      = 30                   # 7-730 days
enable_auto_scaling     = false                # Scale VMs
allowed_ssh_ips         = ["0.0.0.0/0"]       # Restrict SSH to specific IPs
```

### Environment-Specific Configurations

For different environments:

```bash
# Development (cheaper resources, shorter logs)
terraform apply -var-file="dev.tfvars"

# Staging (production-grade, test before prod)
terraform apply -var-file="staging.tfvars"

# Production (full features, max reliability)
terraform apply -var-file="terraform.tfvars"
```

## Deployment Steps

### Step 1: Initialize Terraform

```bash
cd terraform/

terraform init

# Expected output:
# Initializing the backend...
# Initializing provider plugins...
# Terraform has been successfully initialized!
```

This downloads the Azure provider (hashicorp/azurerm).

### Step 2: Review Resources

```bash
# Show execution plan (what will be created)
terraform plan -var-file="terraform.tfvars"

# Save plan to file for review
terraform plan -var-file="terraform.tfvars" -out="tfplan"

# Review saved plan
terraform show tfplan
```

### Step 3: Apply Configuration

```bash
# Deploy all resources
terraform apply -var-file="terraform.tfvars"

# Or apply from saved plan
terraform apply tfplan

# Type "yes" when prompted to confirm deployment
```

**Typical Deployment Time:** 15-20 minutes

### Step 4: Retrieve Outputs

```bash
# Get all outputs in table format
terraform output

# Get specific outputs
terraform output resource_group_name
terraform output vm_ssh_command
terraform output deployment_summary

# Export outputs to file
terraform output -json > outputs.json
```

## Verification

### Verify Deployed Resources

```bash
# Show all resources managed by Terraform
terraform state list

# Show specific resource details
terraform state show azurerm_linux_virtual_machine.main

# Show resource group in Azure
terraform state show azurerm_resource_group.main
```

### Verify in Azure Portal

```bash
# Get resource group name
RG=$(terraform output -raw resource_group_name)

# List all resources
az resource list --resource-group $RG --output table

# Check VM status
az vm get-instance-view \
  --resource-group $RG \
  --name "vm-3dfigurine-prod" \
  --query "instanceView.statuses"
```

### Test VM Access

```bash
# Get SSH command from Terraform
SSH_CMD=$(terraform output -raw vm_ssh_command)

# Connect to VM
$SSH_CMD

# Expected: Linux prompt
# azureuser@vm-3dfigurine-prod:~$
```

## State Management

### Local State (Default)

Terraform stores state locally in `terraform.tfstate`:

```bash
# State file location
ls -la terraform.tfstate
ls -la terraform.tfstate.backup

# WARNING: Never commit tfstate to git!
# It contains sensitive information (connection strings, passwords)
```

### Remote State (Production Recommended)

For team environments, use Azure Storage for remote state:

1. Create storage account for Terraform state:
```bash
az storage account create \
  --name stterraformstate \
  --resource-group rg-terraform-state \
  --location eastus \
  --sku Standard_LRS

az storage container create \
  --name tfstate \
  --account-name stterraformstate
```

2. Configure backend in `providers.tf`:
```hcl
backend "azurerm" {
  resource_group_name  = "rg-terraform-state"
  storage_account_name = "stterraformstate"
  container_name       = "tfstate"
  key                  = "3dfigurine.tfstate"
}
```

3. Re-initialize:
```bash
terraform init
# Migrate state to Azure Storage
```

## Common Operations

### Scale VM Size

```bash
# Update variable
terraform apply -var="vm_size=Standard_NC24s_v3" -var-file="terraform.tfvars"

# Or edit terraform.tfvars and apply
terraform apply -var-file="terraform.tfvars"
```

### Enable/Disable Monitoring

```bash
# Disable Application Insights to save costs
terraform apply -var="enable_monitoring=false" -var-file="terraform.tfvars"

# Re-enable
terraform apply -var="enable_monitoring=true" -var-file="terraform.tfvars"
```

### Restrict SSH Access

```bash
# Change allowed_ssh_ips for security
terraform apply \
  -var='allowed_ssh_ips=["YOUR_IP/32"]' \
  -var-file="terraform.tfvars"
```

### Update VM Configuration

```bash
# Recreate VM with new settings
terraform apply -replace="azurerm_linux_virtual_machine.main" \
  -var-file="terraform.tfvars"
```

## Troubleshooting

### Error: "InvalidTemplateDeployment"

```bash
# Problem: Resource name already exists globally
# Solution: Change project_name to unique value
terraform apply -var="project_name=3dfigurine-lab-unique" \
  -var-file="terraform.tfvars"
```

### Error: "Insufficient quota"

```bash
# Problem: Azure quota exceeded (GPU cores, vCPUs)
# Solution: Request quota increase via Azure Portal
# OR use smaller VM: Standard_NC24s_v3 instead of Standard_NC24ads_A100_v4
terraform apply -var="vm_size=Standard_NC24s_v3" \
  -var-file="terraform.tfvars"
```

### Error: "Can't read state"

```bash
# Problem: State file corrupted or missing
# Solution: Check file permissions
ls -la terraform.tfstate

# Or use remote state with redundancy
# See State Management section above
```

### SSH Key Not Found

```bash
# Problem: "SSH public key not found"
# Solution: Generate key or update path
ssh-keygen -t rsa -b 4096 -f ~/.ssh/azure_3dfigurine -N ""

# Update variable in terraform.tfvars
ssh_public_key_path = "~/.ssh/azure_3dfigurine.pub"

terraform apply -var-file="terraform.tfvars"
```

## Cleanup

### Destroy Specific Resources

```bash
# Destroy only monitoring (save costs)
terraform destroy -target="azurerm_application_insights.main" \
  -var-file="terraform.tfvars"

# Destroy only VM (keep storage)
terraform destroy -target="azurerm_linux_virtual_machine.main" \
  -var-file="terraform.tfvars"
```

### Destroy Everything

```bash
# Show what will be deleted
terraform plan -destroy -var-file="terraform.tfvars"

# Delete all resources
terraform destroy -var-file="terraform.tfvars"

# Confirm by typing "yes"

# Verify deletion
az group list --query "[?name=='rg-3dfigurine-prod-eastus']"
# Expected: Empty list
```

### Clean Local Files

```bash
# Remove Terraform state files (CAREFUL!)
rm -f terraform.tfstate* .terraform.lock.hcl

# Remove provider cache
rm -rf .terraform/

# Re-run init if needed later
terraform init
```

## Comparison: Terraform vs ARM Templates

| Feature | Terraform | ARM Template |
|---------|-----------|--------------|
| Syntax | HCL (readable) | JSON (verbose) |
| Multi-cloud | ✅ Yes | ❌ Azure only |
| State mgt | ✅ Built-in | ❌ Manual |
| Learning curve | Medium | Steep |
| Community support | Excellent | Good |
| Team collaboration | Excellent | Good |
|Modularity|✅ Modules|🟡Linked templates|

## Terraform Advantages for This Project

1. **Readability:** HCL is much more human-readable than JSON
2. **DRY Principle:** Less repetition with variables and locals
3. **Interpolation:** Easy variable substitution and logic
4. **Plan/Apply:** Safe preview before deployment
5. **Modularity:** Can split into reusable modules
6. **State Tracking:** Clear view of infrastructure state
7. **Drift Detection:** Identify manual Azure Portal changes
8. **Team-Friendly:** Better for multi-person projects

## Next Steps

### Phase 1: Immediate Deployment
1. Run `terraform init` to initialize
2. Run `terraform plan` to review changes
3. Run `terraform apply` to deploy

### Phase 2: Production Hardening
1. [x] Move state to Azure Storage (remote backend)
2. [ ] Add authentication to restrict SSH
3. [ ] Setup automated backups
4. [ ] Configure cost alerts

### Phase 3: Advanced Features
1. [ ] Create Terraform modules for reusability
2. [ ] Add data sources for existing resources
3. [ ] Implement auto-scaling policies
4. [ ] Add private endpoint for storage

### Phase 4: Team Collaboration
1. [ ] Setup Terraform Cloud for state sharing
2. [ ] Configure CI/CD pipeline (GitHub Actions)
3. [ ] Add policy as code (Sentinel)
4. [ ] Document team workflows

## Resources

- [Terraform Azure Provider Docs](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
- [Azure Terraform Best Practices](https://learn.microsoft.com/en-us/azure/developer/terraform/)
- [Terraform Language Docs](https://www.terraform.io/language)
- [Azure Architecture Patterns](https://docs.microsoft.com/azure/architecture/patterns)

## Support

For issues or questions:
1. Check Terraform logs: `TF_LOG=DEBUG terraform apply`
2. Review Azure Portal for resource creation status
3. Check Azure CLI: `az ... --debug`
4. See [PHASE_6_PROGRESS.md](../PHASE_6_PROGRESS.md) for architecture details

---

**Terraform Version:** 1.0+
**Azure Provider Version:** 3.0+
**Last Updated:** 2024
