# Databricks side: service credential -> Key Vault connection -> schema bound to the vault
# -> Unity Gateway model provider service whose API key is the Key Vault-backed Unity Catalog secret.

locals {
  # Unity Catalog names take underscores where the Azure names (var.name) take hyphens.
  uc_name = replace(var.name, "-", "_")

  # <catalog>.<schema>.<service id>: the securable the caller grant targets and the name the model_provider_service
  # output hands to scripts/smoke_test.sh.
  model_provider_service_full_name = "${module.schema_secret_storage.schema_full_name}.${databricks_ai_gateway_model_provider_service.litellm_via_apim.model_provider_service_id}"
}

# The workspace the Databricks provider is configured for; the workspace_host output reads its host.
data "databricks_current_config" "this" {}

resource "databricks_credential" "key_vault" {
  name    = local.uc_name
  purpose = "SERVICE"
  comment = "Managed identity that may list and read secrets in ${azurerm_key_vault.demo.name}"

  azure_managed_identity {
    access_connector_id = azurerm_databricks_access_connector.key_vault.id
    managed_identity_id = azurerm_user_assigned_identity.key_vault_reader.id
  }

  depends_on = [azurerm_role_assignment.identity_reads_secrets]
}

resource "databricks_connection" "key_vault" {
  name            = "${local.uc_name}_key_vault"
  connection_type = "AZURE_KEY_VAULT"
  comment         = "External secret manager for ${var.catalog_name}.${var.schema_name}"

  options = {
    vault_name = azurerm_key_vault.demo.name
    credential = databricks_credential.key_vault.name
  }
}

resource "databricks_catalog" "demo" {
  name          = var.catalog_name
  comment       = var.catalog_comment
  storage_root  = var.catalog_storage_root
  force_destroy = var.catalog_force_destroy
}

resource "databricks_schema" "secrets" {
  catalog_name  = databricks_catalog.demo.name
  name          = var.schema_name
  comment       = "Backed by Azure Key Vault ${azurerm_key_vault.demo.name}; secrets here are read-only mirrors."
  force_destroy = var.schema_force_destroy
}

resource "databricks_ai_gateway_model_provider_service" "litellm_via_apim" {
  parent                    = "schemas/${module.schema_secret_storage.schema_full_name}"
  model_provider_service_id = "litellm_via_apim"
  comment                   = "LiteLLM behind the APIM Databricks lane. The bearer is the Key Vault-backed Unity Catalog secret, read at request time."

  config = {
    provider_type = "EXTERNAL_MODEL_PROVIDER_TYPE_CUSTOM"

    targets = [
      for model in var.litellm_models : {
        model            = model
        native_api_types = ["openai/v1/chat/completions"]
        endpoint_route   = var.apim_endpoint_route
      }
    ]

    custom = {
      direct = {
        base_url = var.apim_lane_base_url
        api_key = {
          secret_reference = {
            name = "secrets/${module.schema_secret_storage.secrets[var.lane_secret_name].full_name}"
          }
        }
      }
    }
  }
}

# A caller needs EXECUTE on the provider plus USE on catalog and schema, and nothing on the secret.
resource "databricks_grant" "caller_can_use_catalog" {
  count      = var.caller_principal == null ? 0 : 1
  catalog    = databricks_catalog.demo.name
  principal  = var.caller_principal
  privileges = ["USE_CATALOG", "USE_SCHEMA"]
}

resource "databricks_grant" "caller_can_query_provider" {
  count                  = var.caller_principal == null ? 0 : 1
  model_provider_service = local.model_provider_service_full_name
  principal              = var.caller_principal
  privileges             = ["EXECUTE"]
}
