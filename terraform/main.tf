# Data source for current Azure subscription
data "azurerm_client_config" "current" {}

# Resource Group
resource "azurerm_resource_group" "main" {
  name     = "rg-${var.project_name}-${var.environment}-${var.location}"
  location = var.location

  tags = merge(
    var.tags,
    {
      Environment = var.environment
    }
  )
}

# Storage Account
resource "azurerm_storage_account" "main" {
  name                       = "st${replace(var.project_name, "-", "")}${var.environment}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  account_tier               = "Standard"
  account_replication_type   = "LRS"
  access_tier                = var.storage_access_tier
  https_traffic_only_enabled = true
  min_tls_version            = "TLS1_2"

  tags = var.tags
}

# Premium File Storage for Container Apps job data and model cache
resource "azurerm_storage_account" "files" {
  name                     = "st${replace(var.project_name, "-", "")}files${var.environment}"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Premium"
  account_replication_type = "LRS"
  account_kind             = "FileStorage"

  tags = var.tags
}

resource "azurerm_storage_share" "job_data" {
  name                 = var.azure_files_share_name
  storage_account_name = azurerm_storage_account.files.name
  quota                = var.azure_files_share_quota_gb
}

# Blob Containers for Storage Account
resource "azurerm_storage_container" "input" {
  name                  = "input"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "output" {
  name                  = "output"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "logs" {
  name                  = "logs"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

# Container Registry
resource "azurerm_container_registry" "main" {
  name                = "acr${replace(var.project_name, "-", "")}${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = var.container_registry_sku
  admin_enabled       = true

  tags = var.tags
}

# Key Vault
resource "azurerm_key_vault" "main" {
  name                = "kv-${var.project_name}-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  enabled_for_deployment          = true
  enabled_for_disk_encryption     = true
  enabled_for_template_deployment = true
  purge_protection_enabled        = false
  soft_delete_retention_days      = 7

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    key_permissions = [
      "Create", "Delete", "Get", "List", "Update"
    ]

    secret_permissions = [
      "Delete", "Get", "List", "Set"
    ]

    storage_permissions = [
      "Delete", "Get", "List", "Set"
    ]
  }

  tags = var.tags
}

# Log Analytics Workspace
resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-${var.project_name}-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days

  tags = var.tags
}

# Azure Container Apps environment for on-demand GPU jobs.
# We use this instead of ACI because ACI's GpuSku enum (V100/P100/K80) has
# zero quota on free trial subscriptions, while Container Apps' T4 / A100
# workload profiles are available on the same subscriptions.
#
# NOTE: the Consumption-GPU-NC8as-T4 workload profile is added imperatively
# (`az containerapp env workload-profile add ... --workload-profile-type
# Consumption-GPU-NC8as-T4`) because azurerm ~> 3.0 doesn't yet validate the
# GPU profile types. Upgrade to azurerm v4 to bring it back into IaC. The
# `lifecycle.ignore_changes` block below preserves the imperatively-added
# profile across `terraform apply` runs.
resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${var.project_name}-${var.environment}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
    minimum_count         = 0
    maximum_count         = 0
  }

  lifecycle {
    ignore_changes = [workload_profile]
  }

  tags = var.tags
}

# Register the existing Azure Files share with the Container Apps env so
# Jobs can mount /workspace at runtime. Trigger script writes inputs to
# this share before starting a job and reads outputs from it after.
resource "azurerm_container_app_environment_storage" "jobdata" {
  name                         = "jobdata"
  container_app_environment_id = azurerm_container_app_environment.main.id
  account_name                 = azurerm_storage_account.files.name
  share_name                   = azurerm_storage_share.job_data.name
  access_key                   = azurerm_storage_account.files.primary_access_key
  access_mode                  = "ReadWrite"
}

# Application Insights
resource "azurerm_application_insights" "main" {
  count               = var.enable_monitoring ? 1 : 0
  name                = "ai-${var.project_name}-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.main.id

  tags = var.tags
}

# Monitor Action Group (for alerts)
resource "azurerm_monitor_action_group" "main" {
  name                = "ag-${var.project_name}-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "3dfig"

  tags = var.tags
}

# Note: Azure Container Instances are created on-demand via scripts/run_job.py.
# This Terraform configuration provides the supporting infrastructure (storage,
# registry, monitoring) while batch job containers are triggered programmatically
# without persistent VM infrastructure.

# Monthly budget alert. Triggers email at 50%, 80%, and 100% of the cap so we
# notice runaway spend long before the Azure credit is exhausted.
resource "azurerm_consumption_budget_resource_group" "main" {
  name              = "budget-${var.project_name}-${var.environment}"
  resource_group_id = azurerm_resource_group.main.id

  amount     = var.budget_monthly_usd
  time_grain = "Monthly"

  time_period {
    start_date = var.budget_start_date
  }

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThan"
      threshold_type = "Actual"
      contact_emails = [var.budget_alert_email]
    }
  }
}
