# Staging Environment Configuration for ACI Batch Processing

project_name = "3dfigurine-lab"
environment  = "staging"
location     = "eastus"

container_registry_sku = "Premium"
storage_sku            = "Premium_LRS"
storage_access_tier    = "Hot"

enable_monitoring  = true
log_retention_days = 30

container_images = {
  trellis  = "myregistry.azurecr.io/3dfigurine-trellis:staging"
  meshroom = "myregistry.azurecr.io/3dfigurine-meshroom:staging"
}

tags = {
  Project     = "3D Figurine Lab"
  Environment = "staging"
  ManagedBy   = "Terraform"
  CostCenter  = "Engineering"
}
