# Staging Environment Configuration

project_name = "3dfigurine-lab"
environment  = "staging"
location     = "eastus"
vm_size      = "Standard_NC24ads_A100_v4"  # Production-grade for testing

container_registry_sku = "Premium"
storage_sku        = "Premium_LRS"
storage_access_tier = "Hot"

enable_monitoring   = true
log_retention_days  = 14

enable_auto_scaling = false

container_images = {
  trellis   = "myregistry.azurecr.io/3dfigurine-trellis:staging"
  meshroom  = "myregistry.azurecr.io/3dfigurine-meshroom:staging"
}

admin_username  = "azureuser"
ssh_public_key_path = "~/.ssh/azure_3dfigurine.pub"

vnet_address_space      = ["10.2.0.0/16"]
subnet_address_prefixes = ["10.2.1.0/24"]
allowed_ssh_ips = ["0.0.0.0/0"]

tags = {
  Project     = "3D Figurine Lab"
  Environment = "staging"
  ManagedBy   = "Terraform"
  CostCenter  = "Engineering"
}
