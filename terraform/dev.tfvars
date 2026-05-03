# Development Environment Configuration

project_name = "3dfigurine-lab"
environment  = "dev"
location     = "eastus"
vm_size      = "Standard_NC24s_v3" # Cheaper than A100 for dev

container_registry_sku = "Basic"
storage_sku            = "Standard_LRS"
storage_access_tier    = "Hot"

enable_monitoring  = true
log_retention_days = 7 # Shorter retention for cost savings

enable_auto_scaling = false

container_images = {
  trellis  = "myregistry.azurecr.io/3dfigurine-trellis:dev"
  meshroom = "myregistry.azurecr.io/3dfigurine-meshroom:dev"
}

admin_username      = "azureuser"
ssh_public_key_path = "~/.ssh/azure_3dfigurine.pub"

vnet_address_space      = ["10.1.0.0/16"]
subnet_address_prefixes = ["10.1.1.0/24"]
allowed_ssh_ips         = ["0.0.0.0/0"]

tags = {
  Project     = "3D Figurine Lab"
  Environment = "dev"
  ManagedBy   = "Terraform"
  CostCenter  = "Engineering"
}
