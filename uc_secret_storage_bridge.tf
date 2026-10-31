# BETA BRIDGE: the only always-wired external API bridge in this reference.
# Credential, connection, catalog and schema are native provider resources in databricks.tf.
# Databricks provider 1.140.0 does not expose databricks_schema.secret_storage.
# This module supplies binding, drift detection and secret metadata discovery through the CLI.
# See README for the migration procedure once native secret_storage support exists: do not
# simply delete this module, because its destroy provisioner deliberately unbinds the schema.

# Isolates the Beta Unity Catalog schema-binding REST call (`secret_storage` on `/api/2.1/unity-catalog/schemas`)
# with drift detection (`GET ?include_secret_storage=true`) and read-verified secret discovery.
module "schema_secret_storage" {
  source = "./modules/uc_schema_secret_storage"

  databricks_profile = var.databricks_profile
  catalog_name       = databricks_catalog.demo.name
  schema_name        = databricks_schema.secrets.name
  connection_name    = databricks_connection.key_vault.name
  secret_names       = concat([azurerm_key_vault_secret.lane.name], azurerm_key_vault_secret.dummy[*].name)
  secret_versions    = concat([azurerm_key_vault_secret.lane.version], azurerm_key_vault_secret.dummy[*].version)

  # Unknown until the schema exists, which makes the module's drift read wait for it on a first deploy or a schema
  # replacement instead of failing the plan with "Schema ... does not exist".
  schema_id = databricks_schema.secrets.id
}

