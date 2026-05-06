variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "3dfigurine-lab"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
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

variable "storage_sku" {
  description = "Storage account SKU"
  type        = string
  default     = "Standard_LRS"
}

variable "container_registry_sku" {
  description = "Container Registry SKU"
  type        = string
  default     = "Basic"

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.container_registry_sku)
    error_message = "Container Registry SKU must be Basic, Standard, or Premium."
  }
}

variable "log_retention_days" {
  description = "Log Analytics retention period in days"
  type        = number
  default     = 30

  validation {
    condition     = var.log_retention_days >= 30 && var.log_retention_days <= 730
    error_message = "Retention days must be 30-730."
  }
}

variable "enable_monitoring" {
  description = "Enable Application Insights monitoring"
  type        = bool
  default     = true
}

variable "container_images" {
  description = "Container image references for batch jobs"
  type        = map(string)
  default = {
    trellis  = "myregistry.azurecr.io/3dfigurine-trellis:latest"
    meshroom = "myregistry.azurecr.io/3dfigurine-meshroom:latest"
  }
}

variable "azure_files_share_name" {
  description = "Azure Files share mounted into Container Apps jobs"
  type        = string
  default     = "jobdata"
}

variable "azure_files_share_quota_gb" {
  description = "Azure Files share quota in GiB"
  type        = number
  default     = 1024
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
  default = {
    Project     = "3D Figurine Lab"
    Environment = "dev"
    ManagedBy   = "Terraform"
    CostCenter  = "Engineering"
  }
}
