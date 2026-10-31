# Azure side: resource group, managed identity, access connector, RBAC Key Vault, and write-only secrets.

data "azurerm_client_config" "current" {}

locals {
  # The APIM named value holding the lane's shared secret. outputs.tf builds the operator's listValue URL from the same
  # id and API version, so the ephemeral read below and scripts/smoke_test.sh reseed address the same object.
  apim_named_value_api_version = "2022-08-01"
  apim_named_value_id          = "/subscriptions/${var.apim.subscription_id}/resourceGroups/${var.apim.resource_group}/providers/Microsoft.ApiManagement/service/${var.apim.service_name}/namedValues/${var.apim.shared_secret_name}"
}

resource "azurerm_resource_group" "demo" {
  tags     = var.tags
  name     = "rg-${var.name}"
  location = var.location
}

resource "azurerm_user_assigned_identity" "key_vault_reader" {
  tags                = var.tags
  name                = "id-${var.name}"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
}

# The access connector is the Azure resource a Unity Catalog service credential points at.
resource "azurerm_databricks_access_connector" "key_vault" {
  tags                = var.tags
  name                = "dbac-${var.name}"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.key_vault_reader.id]
  }
}

resource "azurerm_key_vault" "demo" {
  tags = var.tags
  # Key Vault names are global and capped at 24 characters: kv-ucsec- (9) + workspace id (15).
  name                          = "kv-ucsec-${var.workspace_id}"
  resource_group_name           = azurerm_resource_group.demo.name
  location                      = azurerm_resource_group.demo.location
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = var.purge_protection_enabled
  soft_delete_retention_days    = var.soft_delete_retention_days
  public_network_access_enabled = var.public_network_access_enabled

  network_acls {
    default_action             = var.network_acls.default_action
    bypass                     = var.network_acls.bypass
    ip_rules                   = var.network_acls.ip_rules
    virtual_network_subnet_ids = var.network_acls.virtual_network_subnet_ids
  }
}

# The managed identity may list and read secrets. That is the only identity Databricks uses against the vault.
resource "azurerm_role_assignment" "identity_reads_secrets" {
  scope                = azurerm_key_vault.demo.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.key_vault_reader.principal_id
}

# The deployment identity needs Key Vault Secrets Officer, either here or via existing RBAC.
resource "azurerm_role_assignment" "deployer_writes_secrets" {
  count = var.create_deployer_role_assignment ? 1 : 0

  scope                = azurerm_key_vault.demo.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Fetch the existing APIM Databricks-lane shared secret ephemerally via ARM (`listValue`).
# Ephemeral resources are evaluated in memory and never persisted in terraform.tfstate or plan files.
ephemeral "azapi_resource_action" "apim_lane_secret" {
  type                   = "Microsoft.ApiManagement/service/namedValues@${local.apim_named_value_api_version}"
  resource_id            = local.apim_named_value_id
  action                 = "listValue"
  method                 = "POST"
  response_export_values = ["value"]
}

# Write the APIM secret into Key Vault using Terraform 1.11+ write-only `value_wo`.
# Full resource lifecycle & drift detection in state, with zero secret plaintext in terraform.tfstate.
resource "azurerm_key_vault_secret" "lane" {
  tags             = var.tags
  name             = var.lane_secret_name
  key_vault_id     = azurerm_key_vault.demo.id
  value_wo         = ephemeral.azapi_resource_action.apim_lane_secret.output.value
  value_wo_version = var.lane_secret_version
  content_type     = "APIM Databricks-lane shared secret, consumed by Unity Gateway via Unity Catalog"

  depends_on = [azurerm_role_assignment.deployer_writes_secrets]
}
