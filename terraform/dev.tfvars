# Development Environment Configuration for ACI Batch Processing

project_name = "3dfiglab"
environment  = "dev"
location     = "westus"

container_registry_sku = "Basic"
storage_sku            = "Standard_LRS"
storage_access_tier    = "Hot"

enable_monitoring  = true
log_retention_days = 30

container_images = {
  trellis  = "acr3dfiglabdev.azurecr.io/3dfigurine-trellis:latest"
  meshroom = "acr3dfiglabdev.azurecr.io/3dfigurine-meshroom:latest"
}


tags = {
  Project     = "3D Figurine Lab"
  Environment = "dev"
  ManagedBy   = "Terraform"
  CostCenter  = "Engineering"
}
