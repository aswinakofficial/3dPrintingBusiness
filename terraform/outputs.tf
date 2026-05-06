output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.main.name
}

output "storage_account_name" {
  description = "Name of the storage account"
  value       = azurerm_storage_account.main.name
}

output "storage_account_primary_blob_endpoint" {
  description = "Primary blob endpoint of storage account"
  value       = azurerm_storage_account.main.primary_blob_endpoint
}

output "storage_account_connection_string" {
  description = "Connection string for storage account"
  value       = azurerm_storage_account.main.primary_connection_string
  sensitive   = true
}

output "file_storage_account_name" {
  description = "Name of the Azure Files storage account"
  value       = azurerm_storage_account.files.name
}

output "file_storage_account_key" {
  description = "Primary access key for the Azure Files storage account"
  value       = azurerm_storage_account.files.primary_access_key
  sensitive   = true
}

output "azure_files_share_name" {
  description = "Name of the Azure Files share mounted into Container Apps jobs"
  value       = azurerm_storage_share.job_data.name
}

output "container_registry_name" {
  description = "Name of the container registry"
  value       = azurerm_container_registry.main.name
}

output "container_registry_login_server" {
  description = "Login server for container registry"
  value       = azurerm_container_registry.main.login_server
}

output "container_registry_admin_username" {
  description = "Admin username for container registry"
  value       = azurerm_container_registry.main.admin_username
}

output "container_registry_admin_password" {
  description = "Admin password for container registry"
  value       = azurerm_container_registry.main.admin_password
  sensitive   = true
}

output "key_vault_id" {
  description = "ID of the Key Vault"
  value       = azurerm_key_vault.main.id
}

output "key_vault_name" {
  description = "Name of the Key Vault"
  value       = azurerm_key_vault.main.name
}

output "key_vault_uri" {
  description = "URI of the Key Vault"
  value       = azurerm_key_vault.main.vault_uri
}

output "log_analytics_workspace_id" {
  description = "ID of Log Analytics Workspace"
  value       = azurerm_log_analytics_workspace.main.id
}

output "container_apps_environment_name" {
  description = "Name of the Azure Container Apps environment"
  value       = azurerm_container_app_environment.main.name
}

output "container_apps_environment_id" {
  description = "ID of the Azure Container Apps environment"
  value       = azurerm_container_app_environment.main.id
}

output "container_images" {
  description = "Container images configured for remote job execution"
  value       = var.container_images
}

output "application_insights_instrumentation_key" {
  description = "Instrumentation key for Application Insights"
  value       = var.enable_monitoring ? azurerm_application_insights.main[0].instrumentation_key : null
  sensitive   = true
}

output "application_insights_app_id" {
  description = "App ID for Application Insights"
  value       = var.enable_monitoring ? azurerm_application_insights.main[0].app_id : null
}

output "deployment_summary" {
  description = "Summary of deployed resources for Container Apps batch processing"
  value = {
    resource_group      = azurerm_resource_group.main.name
    location            = azurerm_resource_group.main.location
    environment         = var.environment
    storage_account     = azurerm_storage_account.main.name
    file_storage        = azurerm_storage_account.files.name
    file_share          = azurerm_storage_share.job_data.name
    container_registry  = azurerm_container_registry.main.name
    acr_login_server    = azurerm_container_registry.main.login_server
    container_apps_env  = azurerm_container_app_environment.main.name
    key_vault_name      = azurerm_key_vault.main.name
    log_analytics_name  = azurerm_log_analytics_workspace.main.name
  }
}
