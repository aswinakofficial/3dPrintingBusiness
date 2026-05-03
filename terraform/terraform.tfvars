# Terraform Variables for 3D Figurine Lab
# This file sets production environment defaults

project_name = "3dfigurine-lab"
environment  = "prod"
location     = "eastus"
vm_size      = "Standard_NC24ads_A100_v4"

# Container Registry Configuration
container_registry_sku = "Premium"

# Storage Configuration
storage_sku        = "Premium_LRS"
storage_access_tier = "Hot"

# Monitoring Configuration
enable_monitoring   = true
log_retention_days  = 30

# Auto-scaling (disabled by default for cost control)
enable_auto_scaling = false

# Container Images (replace with your ACR URLs)
container_images = {
  trellis   = "myregistry.azurecr.io/3dfigurine-trellis:latest"
  meshroom  = "myregistry.azurecr.io/3dfigurine-meshroom:latest"
}

# VM Configuration
admin_username  = "azureuser"
ssh_public_key_path = "~/.ssh/azure_3dfigurine.pub"

# Network Configuration
vnet_address_space       = ["10.0.0.0/16"]
subnet_address_prefixes  = ["10.0.1.0/24"]

# Security: Restrict SSH to specific IPs
# Change to ["YOUR_IP/32"] for production
allowed_ssh_ips = ["0.0.0.0/0"]

# Tags for resource organization
tags = {
  Project     = "3D Figurine Lab"
  Environment = "prod"
  ManagedBy   = "Terraform"
  CostCenter  = "Engineering"
}
