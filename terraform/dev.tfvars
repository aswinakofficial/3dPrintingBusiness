# Development Environment Configuration for ACI Batch Processing

project_name = "3dfigurine-lab"
environment  = "dev"
location     = "westus"

container_registry_sku = "Basic"
storage_sku            = "Standard_LRS"
storage_access_tier    = "Hot"

enable_monitoring  = true
log_retention_days = 30

container_images = {
  trellis  = "acr3dfigurinelabdev.azurecr.io/3dfigurine-trellis:latest"
  meshroom = "acr3dfigurinelabdev.azurecr.io/3dfigurine-meshroom:latest"
}


tags = {
  Project     = "3D Figurine Lab"
  Environment = "dev"
  ManagedBy   = "Terraform"
  CostCenter  = "Engineering"
}
