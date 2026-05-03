variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "3dfigurine-lab"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.project_name))
    error_message = "Project name must be 3-20 characters, lowercase alphanumeric and hyphens only."
  }
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "location" {
  description = "Azure region for resource deployment"
  type        = string
  default     = "eastus"

  validation {
    condition     = length(var.location) > 0
    error_message = "Location cannot be empty."
  }
}

variable "vm_size" {
  description = "Azure VM size for GPU compute"
  type        = string
  default     = "Standard_NC24ads_A100_v4"

  validation {
    condition     = can(regex("^(Standard_NC|Standard_ND|Standard_NV)", var.vm_size))
    error_message = "VM size must be a GPU-enabled Azure VM type."
  }
}

variable "container_registry_sku" {
  description = "Container Registry SKU (Basic, Standard, Premium)"
  type        = string
  default     = "Premium"

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.container_registry_sku)
    error_message = "SKU must be Basic, Standard, or Premium."
  }
}

variable "storage_sku" {
  description = "Storage account SKU"
  type        = string
  default     = "Premium_LRS"

  validation {
    condition     = contains(["Standard_LRS", "Standard_GRS", "Standard_RAGRS", "Standard_ZRS", "Premium_LRS", "Premium_ZRS"], var.storage_sku)
    error_message = "Invalid storage SKU."
  }
}

variable "storage_access_tier" {
  description = "Storage account access tier"
  type        = string
  default     = "Hot"

  validation {
    condition     = contains(["Hot", "Cool"], var.storage_access_tier)
    error_message = "Access tier must be Hot or Cool."
  }
}

variable "enable_monitoring" {
  description = "Enable Application Insights and monitoring"
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "Log Analytics retention in days"
  type        = number
  default     = 30

  validation {
    condition     = var.log_retention_days >= 7 && var.log_retention_days <= 730
    error_message = "Log retention must be between 7 and 730 days."
  }
}

variable "enable_auto_scaling" {
  description = "Enable auto-scaling for VM resources"
  type        = bool
  default     = false
}

variable "container_images" {
  description = "Container image URIs"
  type = object({
    trellis  = string
    meshroom = string
  })

  default = {
    trellis  = "mcr.microsoft.com/hello-world:latest"
    meshroom = "mcr.microsoft.com/hello-world:latest"
  }
}

variable "admin_username" {
  description = "VM admin username"
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key file"
  type        = string
  default     = "~/.ssh/azure_3dfigurine.pub"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)

  default = {
    Project     = "3D Figurine Lab"
    Environment = "prod"
    ManagedBy   = "Terraform"
  }
}

variable "allowed_ssh_ips" {
  description = "CIDR blocks allowed for SSH access"
  type        = list(string)

  default = ["0.0.0.0/0"] # Change to restrict SSH access
}

variable "vnet_address_space" {
  description = "Virtual network address space"
  type        = list(string)
  default     = ["10.0.0.0/16"]
}

variable "subnet_address_prefixes" {
  description = "Subnet address prefixes"
  type        = list(string)
  default     = ["10.0.1.0/24"]
}
