# Terraform Variables for 3D Figurine Lab - Production Environment
#This file sets production environment defaults for ACI batch processing

project_name = "3dfigurine-lab"
environment  = "prod"
location     = "eastus"

# Container Registry Configuration
container_registry_sku = "Premium"

# Storage Configuration
storage_sku         = "Premium_LRS"
storage_access_tier = "Hot"

# Monitoring Configuration
enable_monitoring  = true
log_retention_days = 30

# Container Images (replace with your ACR URLs)
container_images = {
  trellis  = "myregistry.azurecr.io/3dfigurine-trellis:latest"
  meshroom = "myregistry.azurecr.io/3dfigurine-meshroom:latest"
}

# Tags for resource organization
tags = {
  Project     = "3D Figurine Lab"
  Environment = "prod"
  ManagedBy   = "Terraform"
  CostCenter  = "Engineering"
}
