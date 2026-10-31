# Validation add-on: make Key Vault tell us who reads the secrets and from which address.
# Set enable_diagnostics = true in terraform.tfvars to create it.
#
# Key Vault's AuditEvent log records the caller IP and the identity of every data-plane call, including the
# SecretGet that Unity Catalog performs when a Databricks user or Unity Gateway reads an external secret.
# Nothing else in this configuration depends on these two resources; `./scripts/smoke_test.sh callers` queries the result.

resource "azurerm_log_analytics_workspace" "audit" {
  tags  = var.tags
  count = var.enable_diagnostics ? 1 : 0

  name                = "law-${var.name}"
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name
  sku                 = "PerGB2018"
}

resource "azurerm_monitor_diagnostic_setting" "key_vault_audit" {
  count = var.enable_diagnostics ? 1 : 0

  name                       = "audit-to-log-analytics"
  target_resource_id         = azurerm_key_vault.demo.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.audit[0].id

  enabled_log {
    category = "AuditEvent"
  }
}

output "log_analytics_workspace_customer_id" {
  description = "Workspace (customer) id of the Log Analytics workspace that scripts/smoke_test.sh callers and perimeter query; null unless enable_diagnostics."
  value       = var.enable_diagnostics ? azurerm_log_analytics_workspace.audit[0].workspace_id : null
}

output "key_vault_reader_principal_id" {
  description = "Object id of the managed identity behind the service credential; Key Vault audit rows should carry it."
  value       = azurerm_user_assigned_identity.key_vault_reader.principal_id
}
