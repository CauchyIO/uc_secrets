# Isolates the Beta Unity Catalog schema-binding REST call (`secret_storage` on `/api/2.1/unity-catalog/schemas`)
# until native `databricks_schema.secret_storage` support lands (CauchyIO/terraform-provider-databricks#1).
module "schema_secret_storage" {
  source = "./modules/uc_schema_secret_storage"

  databricks_profile = var.databricks_profile
  catalog_name       = databricks_catalog.demo.name
  schema_name        = databricks_schema.secrets.name
  connection_name    = databricks_connection.key_vault.name
  secret_names       = concat([azurerm_key_vault_secret.lane.name], azurerm_key_vault_secret.dummy[*].name)
  secret_versions    = concat([azurerm_key_vault_secret.lane.version], azurerm_key_vault_secret.dummy[*].version)
  schema_id          = databricks_schema.secrets.id
}

