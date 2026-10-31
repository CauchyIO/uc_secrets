# Validation add-on: a Network Connectivity Configuration (NCC) private endpoint from the serverless compute plane
# to the vault. Set enable_ncc_private_endpoint = true and databricks_account_id in terraform.tfvars to create it.
#
# What it is for: an NCC private endpoint carries traffic that serverless COMPUTE (notebooks, jobs, SQL warehouses,
# model serving) opens itself, for example an Azure SDK SecretClient in a notebook. Unity Catalog's own secret fetch,
# the one behind dbutils.secrets.get and Unity Gateway's secret_reference, is made by the Unity Catalog service with
# the access connector identity and does not travel through the workspace's NCC. notebooks/topology_matrix.py
# measures both lanes from compute so the difference is visible, not assumed.
#
# Lifecycle facts that matter before enabling this:
# - The Databricks provider cannot unbind an NCC from a workspace: destroying databricks_mws_ncc_binding is a no-op
#   that only logs a warning. The workspace keeps the NCC until an account admin replaces it with another NCC.
#   Destroying the NCC itself therefore fails while the workspace still points at it.
# - Private endpoint rules bill per hour from creation until deletion, approved or not.
# - A new binding takes effect after about ten minutes, and running serverless compute must be restarted to use it.
# - Apply with DATABRICKS_TF_ENABLED_PF_RESOURCES=databricks_mws_ncc_private_endpoint_rule so the rule resource
#   waits for Databricks to finish creating the endpoint (PENDING) before the approval step below runs.

provider "databricks" {
  alias           = "account"
  host            = "https://accounts.azuredatabricks.net"
  account_id      = var.databricks_account_id
  azure_tenant_id = var.tenant_id
  auth_type       = var.databricks_account_auth_type
}

resource "databricks_mws_network_connectivity_config" "demo" {
  count    = var.enable_ncc_private_endpoint ? 1 : 0
  provider = databricks.account

  name   = "ncc-${var.name}"
  region = var.location
}

# Databricks creates an Azure private endpoint towards the vault's "vault" sub-resource in its own subscription.
resource "databricks_mws_ncc_private_endpoint_rule" "key_vault" {
  count    = var.enable_ncc_private_endpoint ? 1 : 0
  provider = databricks.account

  network_connectivity_config_id = databricks_mws_network_connectivity_config.demo[0].network_connectivity_config_id
  resource_id                    = azurerm_key_vault.demo.id
  group_id                       = "vault"
}

resource "databricks_mws_ncc_binding" "demo_workspace" {
  count    = var.enable_ncc_private_endpoint ? 1 : 0
  provider = databricks.account

  network_connectivity_config_id = databricks_mws_network_connectivity_config.demo[0].network_connectivity_config_id
  workspace_id                   = tonumber(var.workspace_id)
}

output "ncc_private_endpoint" {
  description = "The NCC private endpoint rule towards the vault as Databricks reports it right after apply; ESTABLISHED only after the approval step and Databricks' own refresh."
  value = var.enable_ncc_private_endpoint ? {
    network_connectivity_config_id = databricks_mws_network_connectivity_config.demo[0].network_connectivity_config_id
    rule_id                        = databricks_mws_ncc_private_endpoint_rule.key_vault[0].rule_id
    endpoint_name                  = databricks_mws_ncc_private_endpoint_rule.key_vault[0].endpoint_name
    connection_state               = databricks_mws_ncc_private_endpoint_rule.key_vault[0].connection_state
  } : null
}
