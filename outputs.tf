# Core outputs. scripts/smoke_test.sh reads several of them by name, so renaming one breaks it. None carries a secret
# value: unity_catalog_secret_for_lane is a name and apim_named_value_list_url is an address that needs an authorized
# caller. The add-ons keep their outputs next to their resources (diagnostics.tf, ncc.tf, nsp.tf).

output "key_vault_name" {
  description = "Name of the Key Vault (kv-ucsec-<workspace id>)."
  value       = azurerm_key_vault.demo.name
}

output "service_credential" {
  description = "Unity Catalog SERVICE credential that carries the access connector's managed identity."
  value       = databricks_credential.key_vault.name
}

output "key_vault_connection" {
  description = "Unity Catalog AZURE_KEY_VAULT connection the bound schema reads its secrets through."
  value       = databricks_connection.key_vault.name
}

output "bound_schema" {
  description = "<catalog>.<schema> bound to the Key Vault connection (STORAGE_TYPE_EXTERNAL)."
  value       = module.schema_secret_storage.schema_full_name
}

output "unity_catalog_secret_for_lane" {
  description = "Unity Catalog full name of the APIM lane secret (<catalog>.<schema>.<secret>); the name only, never the value."
  value       = "${module.schema_secret_storage.schema_full_name}.${var.lane_secret_name}"
}

output "apim_named_value_list_url" {
  description = "ARM listValue URL of the APIM named value that holds the lane secret; scripts/smoke_test.sh reseed pipes the value from it into Key Vault. The URL only, never the value."
  value       = "https://management.azure.com${local.apim_named_value_id}/listValue?api-version=${local.apim_named_value_api_version}"
}

output "model_provider_service" {
  description = "Full name of the Unity Gateway model provider service (<catalog>.<schema>.<service id>); callers need EXECUTE on it."
  value       = local.model_provider_service_full_name
}

output "databricks_profile" {
  description = "Optional workspace profile; empty means the CLI uses environment authentication."
  value       = var.databricks_profile == null ? "" : var.databricks_profile
}

output "workspace_host" {
  description = "Host of the workspace the Databricks provider is configured for."
  value       = data.databricks_current_config.this.host
}
