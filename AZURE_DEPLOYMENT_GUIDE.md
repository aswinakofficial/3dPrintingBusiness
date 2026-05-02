# Azure Deployment Guide - 3D Figurine Lab

Complete step-by-step guide for deploying the 3D Figurine Lab to Azure using Infrastructure-as-Code.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start (5 minutes)](#quick-start-5-minutes)
3. [Detailed Deployment](#detailed-deployment)
4. [Verification](#verification)
5. [Accessing Your Deployment](#accessing-your-deployment)
6. [Monitoring and Troubleshooting](#monitoring-and-troubleshooting)
7. [Cleanup](#cleanup)

## Prerequisites

### Azure Account
- Active Azure subscription with sufficient quota:
  - GPU quota: 2x NVIDIA A100 (80GB each)
  - vCPU quota: 40+ cores
  - Storage: 256GB+ available
- Default quota may be insufficient; request increase via Azure Portal if needed

### Local Tools (Required)
```bash
# Azure CLI (v2.40+)
curl -sL https://aka.ms/InstallAzureCLIDeb | bash

# Verify installation
az --version
# Expected: azure-cli 2.40.0+

# JSON processor (jq) - optional but recommended
sudo apt-get install -y jq
```

### SSH Key Pair (For VM Access)
```bash
# Generate SSH key if not present
ssh-keygen -t rsa -b 4096 -f ~/.ssh/azure_3dfigurine -N ""

# Verify
ls -la ~/.ssh/azure_3dfigurine*
```

### Docker (Optional, Only if Building Images)
```bash
# Install Docker for building container images
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
rm get-docker.sh

# Verify
docker --version
```

### Repository Files
Ensure these files exist in workspace:
```
azure/
├── template.json       ✅
├── parameters.json     ✅
├── deploy.sh          ✅
└── vm-setup.sh        ✅

docker/
├── Dockerfile.trellis ✅
└── Dockerfile.meshroom ✅
```

## Quick Start (5 minutes)

For experienced Azure users deploying with pre-built images:

```bash
cd /home/aswinak/Projects/3dPrintingBusiness

# Make deploy script executable
chmod +x azure/deploy.sh

# Run deployment (no image building)
./azure/deploy.sh

# At prompts:
# - Select subscription
# - Skip image building (use pre-built)
# - Select VM configuration
```

**Expected result:** VM deployed, SSH connection details will be displayed

## Detailed Deployment

### Step 1: Authenticate with Azure

```bash
# Login to Azure
az login

# List available subscriptions
az account list --output table

# Select target subscription (if multiple)
az account set --subscription "<subscription-id>"

# Verify authentication
az account show --output table
```

**Expected output:**
```
CloudName    HomeTenantId                      Id                                    IsDefault    Name                State    User
-----------  ----------------                 --                                    ----------   ----                -----    ----
AzureCloud   12345678-1234-1234-1234-...      87654321-4321-4321-4321-...          True         My Subscription     Enabled  user@example.com
```

### Step 2: Prepare Parameters File

Edit `azure/parameters.json` for your deployment:

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "projectName": {
      "value": "3dfigurine-lab"          // Unique name for resources
    },
    "environment": {
      "value": "prod"                     // dev, staging, or prod
    },
    "location": {
      "value": "eastus"                   // Azure region (eastus, westus, etc.)
    },
    "vmSize": {
      "value": "Standard_NC24ads_A100_v4" // GPU-enabled VM size
    },
    "containerImages": {
      "value": {
        "trellis": "myregistry.azurecr.io/3dfigurine-trellis:v1.0",
        "meshroom": "myregistry.azurecr.io/3dfigurine-meshroom:v1.0"
      }
    }
  }
}
```

**Custom Parameters:**

| Parameter | Example Values | Notes |
|-----------|----------------|-------|
| projectName | 3dfigurine-lab, myproj | Must be globally unique for ACR |
| environment | dev, staging, prod | Controls resource naming and monitoring |
| location | eastus, westus2, northeurope | Must have GPU quota available |
| vmSize | NC24ads_A100_v4, Standard_NC24s_v3 | A100=faster, V100=cheaper |

### Step 3: Run Deployment Script

```bash
# Navigate to project directory
cd /home/aswinak/Projects/3dPrintingBusiness

# Make script executable
chmod +x azure/deploy.sh

# Run with no arguments (interactive mode)
./azure/deploy.sh

# Or specify values as arguments
./azure/deploy.sh --resource-group "my-rg" --location "eastus"
```

**Interactive Prompts:**

```
=== 3D Figurine Lab - Azure Deployment ===

Checking prerequisites...
✓ Azure CLI found
✓ jq found
✓ Docker found

Enter subscription ID (or press Enter for default): [Enter]

Select environment (dev/staging/prod) [prod]: [Enter]

Select VM size [Standard_NC24ads_A100_v4]: [Enter]

Build and push Docker images to ACR? (y/n): [y or n]
  - If YES: Builds both containers and pushes to ACR (~15-20 min)
  - If NO: Skips build, uses pre-existing images in ACR

Configure VM with Docker and containers? (y/n): [y or n]
  - If YES: Runs vm-setup.sh on VM (~10-15 min)
  - If NO: VM created but Docker not configured
```

### Step 4: Monitor Deployment Progress

**In Azure Portal:**
1. Go to Azure Portal → Resource Groups
2. Find your resource group (e.g., "rg-3dfigurine-prod-eastus")
3. Click to open
4. Click "Deployments" tab
5. Watch "Microsoft.Template" deployment progress (typically 10-15 minutes)

**In Terminal:**
```bash
# Check current deployment status
az deployment group list \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --query "[].{name:name, state:properties.provisioningState}"

# Expected States:
# - Creating (deployment in progress)
# - Succeeded (deployment complete)
# - Failed (check error details in portal)
```

**Typical Timeline:**
- 0-2 min: Initial deployment starting
- 2-8 min: Storage, networking, VM resources created
- 8-12 min: VM provisioning and extensions running
- 12-15 min: VM setup script execution
- 15+ min: Complete, ready for use

### Step 5: Get Deployment Outputs

After successful deployment, retrieve access details:

```bash
# List all resources created
az resource list \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --output table

# Get VM public IP
az vm show \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --name "vm-3dfigurine-prod" \
  --show-details \
  --query "publicIps"

# Get Storage account connection string
az storage account show-connection-string \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --name "st3dfigurineprod<random>" \
  --query connectionString -o tsv

# Get Container Registry login server
az acr show \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --name "acr3dfigurineprod" \
  --query loginServer -o tsv
```

## Verification

### Verify Azure Resources

```bash
# Check resource group exists
az group show --name "rg-3dfigurine-prod-eastus"

# List all resources in group
az resource list \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --output table

# Expected resources:
# - Storage account (type: storageAccounts)
# - Container registry (type: registries)
# - Key Vault (type: vaults)
# - Virtual machine (type: virtualMachines)
# - Virtual network (type: virtualNetworks)
# - Public IP (type: publicIPAddresses)
# - Log Analytics workspace (type: workspaces)
```

### Verify VM Connectivity

```bash
# Get VM details
VM_IP=$(az vm show \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --name "vm-3dfigurine-prod" \
  --show-details \
  --query publicIps -o tsv)

# Test SSH connection
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP "echo 'SSH connection successful!'"

# Expected output:
# SSH connection successful!
```

### Verify Docker Installation

```bash
# Connect to VM
SSH_HOST="azureuser@$VM_IP"

# Check Docker status
ssh -i ~/.ssh/azure_3dfigurine $SSH_HOST "docker --version"
# Expected: Docker version 24.0.0+

# Test Docker functionality
ssh -i ~/.ssh/azure_3dfigurine $SSH_HOST "docker run --rm hello-world"
# Expected: "Hello from Docker!" message

# Verify NVIDIA Docker runtime
ssh -i ~/.ssh/azure_3dfigurine $SSH_HOST "docker run --rm --gpus all nvidia/cuda:12.4.1-base nvidia-smi"
# Expected: GPU details with CUDA version, memory, and device list
```

### Verify Container Images

```bash
# List pulled images
ssh -i ~/.ssh/azure_3dfigurine $SSH_HOST "docker images"

# Expected images:
# - nvidia/cuda:12.4.1-base
# - 3dfigurine-trellis:latest
# - 3dfigurine-meshroom:latest

# Check ACR access
ACR_LOGIN_SERVER=$(az acr show \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --name "acr3dfigurineprod" \
  --query loginServer -o tsv)

ssh -i ~/.ssh/azure_3dfigurine $SSH_HOST "docker pull $ACR_LOGIN_SERVER/3dfigurine-trellis:latest"
```

## Accessing Your Deployment

### SSH Access to VM

```bash
# Get public IP
VM_IP=$(az vm show \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --name "vm-3dfigurine-prod" \
  --show-details \
  --query publicIps -o tsv)

# Connect via SSH
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP

# Expected: Linux prompt
# azureuser@vm-3dfigurine-prod:~$
```

### Upload Input Images

```bash
# Create input directory locally
mkdir -p /tmp/3dfigurine-input
# Copy your images to this directory

# Upload to VM storage
scp -i ~/.ssh/azure_3dfigurine \
  -r /tmp/3dfigurine-input/* \
  azureuser@$VM_IP:/opt/3dfigurine/input/

# Verify upload
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP \
  "ls -la /opt/3dfigurine/input/"
```

### Access Storage Account

```bash
# Get storage account name
STORAGE_ACCOUNT=$(az storage account list \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --query "[0].name" -o tsv)

# Get storage account key
STORAGE_KEY=$(az storage account keys list \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --account-name $STORAGE_ACCOUNT \
  --query "[0].value" -o tsv)

# Access blob storage (example: list input container)
az storage blob list \
  --account-name $STORAGE_ACCOUNT \
  --container-name "input" \
  --account-key $STORAGE_KEY \
  --output table
```

### Monitor Container Logs

```bash
# Check Docker container status
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP "docker ps -a"

# View TRELLIS.2 container logs
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP \
  "docker logs 3dfigurine-trellis"

# Follow live logs
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP \
  "docker logs -f 3dfigurine-trellis"

# Check systemd service status
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP \
  "systemctl status 3dfigurine-trellis"

# View system logs
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP \
  "journalctl -u 3dfigurine-trellis -n 50 -f"
```

## Monitoring and Troubleshooting

### Azure Monitor Metrics

```bash
# CPU utilization over last 24 hours
az monitor metrics list \
  --resource "/subscriptions/<sub-id>/resourceGroups/rg-3dfigurine-prod-eastus/providers/Microsoft.Compute/virtualMachines/vm-3dfigurine-prod" \
  --metric "Percentage CPU" \
  --start-time "2024-01-01T00:00:00Z" \
  --interval PT1H

# Memory utilization (requires guest metrics agent)
az monitor metrics list \
  --resource "/subscriptions/<sub-id>/resourceGroups/rg-3dfigurine-prod-eastus/providers/Microsoft.Compute/virtualMachines/vm-3dfigurine-prod" \
  --metric "Available Memory Bytes" \
  --start-time "2024-01-01T00:00:00Z" \
  --interval PT1H
```

### Common Issues and Solutions

#### Issue: SSH Connection Refused
```bash
# Problem: Cannot connect to VM
# Solution 1: Wait 2-3 minutes for VM startup
sleep 180 && ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP

# Solution 2: Check NSG allows SSH
az network nsg rule list \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --nsg-name "nsg-3dfigurine-prod" \
  --query "[?name=='Allow-SSH']"

# Solution 3: Reset VM if completely unresponsive
az vm restart \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --name "vm-3dfigurine-prod"
```

#### Issue: Docker Not Found
```bash
# Problem: "docker: command not found"
# Solution: vm-setup.sh may not have completed
# Check via SSH:
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP "tail -n 50 /var/log/cloud-init-output.log"

# Re-run setup if needed
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP "bash ./vm-setup.sh"
```

#### Issue: GPU Not Available
```bash
# Problem: "could not select device driver"
# Solution: NVIDIA Docker runtime not initialized
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP \
  "sudo systemctl restart docker && sudo systemctl status docker"

# Verify runtime
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP \
  "docker run --rm --gpus all nvidia/cuda:12.4.1-base nvidia-smi"
```

#### Issue: Out of Storage
```bash
# Problem: "No space left on device"
# Solution: Check disk usage
ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP "df -h"

# Solutions:
# 1. Compress old models: gzip /opt/3dfigurine/output/*.obj
# 2. Archive to blob: az storage blob upload ...
# 3. Delete old Docker images: docker image prune -a
```

### View Application Logs in Azure

```bash
# Query Log Analytics for application logs
az monitor log-analytics query \
  --workspace "<workspace-name>" \
  --analytics-query "ContainerInstanceLog_CL | where ContainerName == '3dfigurine-trellis'"

# View Application Insights events
az monitor app-insights metrics show \
  --resource "ai-3dfigurine-prod" \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --metric "requests/count"
```

## Cleanup

### Stop Deployment (Keep Resources)

```bash
# Stop VM (pause billing while keeping disks)
az vm deallocate \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --name "vm-3dfigurine-prod" \
  --no-wait

# List deallocated VMs
az vm list --resource-group "rg-3dfigurine-prod-eastus" \
  --query "[?powerState=='VM deallocated']"
```

### Delete Deployment (Remove All Resources)

```bash
# Delete entire resource group (ALL resources)
az group delete \
  --resource-group "rg-3dfigurine-prod-eastus" \
  --yes \
  --no-wait

# Verify deletion
az group exists --name "rg-3dfigurine-prod-eastus"
# Expected: false
```

### Export Data Before Deletion

```bash
# Backup storage account data
STORAGE_ACCOUNT="<your-storage-account-name>"
STORAGE_KEY="<your-storage-key>"

# Download all containers
az storage blob download-batch \
  --account-name $STORAGE_ACCOUNT \
  --account-key $STORAGE_KEY \
  --source "output" \
  --destination "/tmp/3dfigurine-backup/output"

# Verify backup
ls -la /tmp/3dfigurine-backup/output/
```

## Cost Estimation

### Monthly Costs (Approximate)

| Resource | Size | Cost |
|----------|------|------|
| VM (A100) | 40 vCPU, 96GB, 2xA100 | $5,000-6,000 |
| Storage Account | 1TB Premium LRS | $150-200 |
| Container Registry | Premium SKU | $200 |
| Log Analytics | 1GB/day ingestion | $0-50 |
| Application Insights | Standard | $0-100 |
| **TOTAL** | | **~$5,350-6,550/month** |

### Cost Optimization Tips

1. **Use Spot VMs:** Save 70-80% on compute ($1,000-1,500/month)
2. **Scale Down:** Use NC24s_v3 instead of A100 ($2,000-2,500/month)
3. **Scheduled Shutdown:** Stop VM during non-business hours ($3,000-4,000/month)
4. **Reserved Instances:** 1-3 year commitment saves 40-50%
5. **Archive Storage:** Move old outputs to cool/archive tier (save $100+/month)

## Getting Help

### Azure Documentation
- [Azure CLI Reference](https://docs.microsoft.com/cli/azure/)
- [ARM Template Reference](https://docs.microsoft.com/azure/azure-resource-manager/templates/)
- [Virtual Machines Pricing](https://azure.microsoft.com/pricing/details/virtual-machines/)

### Docker Documentation
- [Docker Documentation](https://docs.docker.com/)
- [NVIDIA Docker](https://github.com/NVIDIA/nvidia-docker)

### Project Documentation
- See [PHASE_6_PROGRESS.md](PHASE_6_PROGRESS.md) for architecture details
- See [docker-compose.yml](docker-compose.yml) for container orchestration
- See [main.py](main.py) for CLI usage instructions

## Next Steps

After successful deployment:

1. **Pull Container Images**
   ```bash
   ACR=$(az acr show --resource-group "rg-3dfigurine-prod-eastus" --name "acr3dfigurineprod" --query loginServer -o tsv)
   docker pull $ACR/3dfigurine-trellis:latest
   docker pull $ACR/3dfigurine-meshroom:latest
   ```

2. **Start Processing**
   ```bash
   docker-compose up -d
   docker-compose ps
   ```

3. **Monitor Performance**
   - View logs: `docker-compose logs -f`
   - Check GPU: `nvidia-smi`
   - Track metrics: Azure Portal → Resource Group → Monitoring

4. **Scale Up Production**
   - Enable auto-scaling for multiple VMs
   - Configure load balancer for distributed processing
   - Setup API endpoints for remote submission

---

**Deployment Status**: Ready for production use
**Estimated Deployment Time**: 20-25 minutes
**Support Resources**: See documentation links above
