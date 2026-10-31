# Validation add-on: put the vault inside an Azure Network Security Perimeter (NSP). Set
# enable_network_security_perimeter = true in terraform.tfvars to create it. The perimeter, its profile and the
# association are free; only the access logs (with enable_diagnostics) cost anything.
#
# What it answers. With public access off, Key Vault's "Allow trusted Microsoft services" bypass is what admits the
# access connector identity Unity Catalog uses (README, locked posture). Microsoft documents that an association in
# Enforced mode overrides that bypass: "even trusted services are blocked unless an explicit perimeter access rule
# admits them", while "private endpoint traffic ... isn't subject to Network Security Perimeter rules"
# (learn.microsoft.com, "Configure network security for Azure Key Vault"). notebooks/TOPOLOGY.md phase 7 (rows 15 to 20) measured
# what that does to each lane.
#
# Access modes (ARM values; the portal calls Learning "Transition"): Learning leaves the vault's own firewall in charge
# and only logs what Enforced would deny; Enforced denies every public request that no inbound rule admits, whatever
# the vault's own publicNetworkAccess says. The association starts in Learning, so turning the toggle on changes
# nothing about who can read the secret until nsp_access_mode is switched.
#
# The optional inbound rule is subscription-based: it admits requests from resources in the listed subscriptions,
# which the perimeter identifies by the identity on the request. The access connector and its identity live in
# var.subscription_id. Whether that rule admits Unity Catalog's fetch is a measurement, not an assumption.

resource "azurerm_network_security_perimeter" "demo" {
  tags  = var.tags
  count = var.enable_network_security_perimeter ? 1 : 0

  name                = "nsp-${var.name}"
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name
}

resource "azurerm_network_security_perimeter_profile" "vault" {
  count = var.enable_network_security_perimeter ? 1 : 0

  name                          = "vault"
  network_security_perimeter_id = azurerm_network_security_perimeter.demo[0].id
}

resource "azurerm_network_security_perimeter_association" "vault" {
  count = var.enable_network_security_perimeter ? 1 : 0

  name                                  = azurerm_key_vault.demo.name
  network_security_perimeter_profile_id = azurerm_network_security_perimeter_profile.vault[0].id
  resource_id                           = azurerm_key_vault.demo.id
  access_mode                           = var.nsp_access_mode
}

resource "azurerm_network_security_perimeter_access_rule" "connector_subscription" {
  count = var.enable_network_security_perimeter && var.nsp_admit_connector_subscription ? 1 : 0

  name                                  = "admit-connector-subscription"
  network_security_perimeter_profile_id = azurerm_network_security_perimeter_profile.vault[0].id
  direction                             = "Inbound"
  subscription_ids                      = ["/subscriptions/${var.subscription_id}"]
}

# Perimeter access logs: one row per admitted or denied request with its source and the rule that decided it.
resource "azurerm_monitor_diagnostic_setting" "nsp_access" {
  count = var.enable_network_security_perimeter && var.enable_diagnostics ? 1 : 0

  name                       = "access-to-log-analytics"
  target_resource_id         = azurerm_network_security_perimeter.demo[0].id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.audit[0].id

  enabled_log {
    category_group = "allLogs"
  }
}

output "network_security_perimeter" {
  description = "The perimeter around the vault, its access mode and whether the inbound rule for the connector's subscription exists."
  value = var.enable_network_security_perimeter ? {
    id           = azurerm_network_security_perimeter.demo[0].id
    profile_id   = azurerm_network_security_perimeter_profile.vault[0].id
    access_mode  = azurerm_network_security_perimeter_association.vault[0].access_mode
    inbound_rule = var.nsp_admit_connector_subscription ? azurerm_network_security_perimeter_access_rule.connector_subscription[0].name : null
  } : null
}
