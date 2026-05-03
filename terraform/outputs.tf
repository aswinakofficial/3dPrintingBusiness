output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.main.name
}

output "storage_account_name" {
  description = "Name of the storage account"
  value       = azurerm_storage_account.main.name
}

output "storage_account_connection_string" {
  description = "Connection string for storage account"
  value       = azurerm_storage_account.main.primary_connection_string
  sensitive   = true
}

output "storage_account_primary_blob_endpoint" {
  description = "Primary blob endpoint"
  value       = azurerm_storage_account.main.primary_blob_endpoint
}

output "container_registry_name" {
  description = "Name of the container registry"
  value       = azurerm_container_registry.main.name
}

output "container_registry_login_server" {
  description = "Container registry login server"
  value       = azurerm_container_registry.main.login_server
}

output "container_registry_admin_username" {
  description = "Container registry admin username"
  value       = azurerm_container_registry.main.admin_username
}

output "container_registry_admin_password" {
  description = "Container registry admin password"
  value       = azurerm_container_registry.main.admin_password
  sensitive   = true
}

output "key_vault_id" {
  description = "ID of the Key Vault"
  value       = azurerm_key_vault.main.id
}

output "key_vault_uri" {
  description = "URI of the Key Vault"
  value       = azurerm_key_vault.main.vault_uri
}

output "log_analytics_workspace_id" {
  description = "ID of Log Analytics Workspace"
  value       = azurerm_log_analytics_workspace.main.id
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

output "virtual_network_id" {
  description = "ID of the virtual network"
  value       = azurerm_virtual_network.main.id
}

output "subnet_id" {
  description = "ID of the subnet"
  value       = azurerm_subnet.main.id
}

output "network_security_group_id" {
  description = "ID of the network security group"
  value       = azurerm_network_security_group.main.id
}

output "public_ip_address" {
  description = "Public IP address of the VM"
  value       = azurerm_public_ip.main.ip_address
}

output "public_ip_fqdn" {
  description = "FQDN of the public IP"
  value       = azurerm_public_ip.main.fqdn
}

output "vm_id" {
  description = "ID of the virtual machine"
  value       = azurerm_linux_virtual_machine.main.id
}

output "vm_name" {
  description = "Name of the virtual machine"
  value       = azurerm_linux_virtual_machine.main.name
}

output "vm_ssh_command" {
  description = "SSH command to connect to the VM"
  value       = "ssh -i ~/.ssh/azure_3dfigurine ${var.admin_username}@${azurerm_public_ip.main.ip_address}"
}

output "vm_private_ip_address" {
  description = "Private IP address of the VM"
  value       = azurerm_network_interface.main.private_ip_address
}

output "deployment_summary" {
  description = "Summary of deployed resources"
  value = {
    project_name       = var.project_name
    environment        = var.environment
    location           = var.location
    resource_group     = azurerm_resource_group.main.name
    storage_account    = azurerm_storage_account.main.name
    container_registry = azurerm_container_registry.main.name
    key_vault          = azurerm_key_vault.main.name
    log_analytics      = azurerm_log_analytics_workspace.main.name
    vm_name            = azurerm_linux_virtual_machine.main.name
    vm_size            = var.vm_size
    vm_public_ip       = azurerm_public_ip.main.ip_address
    vm_fqdn            = azurerm_public_ip.main.fqdn
    acr_login_server   = azurerm_container_registry.main.login_server
  }
}
