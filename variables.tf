# Input variables. Values live in the gitignored terraform.tfvars; terraform.tfvars.example lists every one of them.
# None of them is a secret: the APIM lane key is read ephemerally in azure.tf and written into Key Vault with value_wo,
# so it never enters a variable, a plan or the state. That is why no variable here is marked sensitive.

variable "subscription_id" {
  description = "Azure subscription that hosts the resource group, access connector, and Key Vault."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a subscription id (GUID)."
  }
}

variable "tenant_id" {
  description = "Entra tenant of the Databricks workspace. The access connector and the Key Vault must live here."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be an Entra tenant id (GUID)."
  }
}

variable "location" {
  description = "Azure region. Same region as the workspace so secret reads stay in-region."
  type        = string
  default     = "westeurope"
  nullable    = false

  validation {
    # ncc.tf hands the same value to Databricks as the NCC region, so it has to be the programmatic name.
    condition     = can(regex("^[a-z][a-z0-9]*$", var.location))
    error_message = "location must be a programmatic Azure region name such as westeurope (lowercase, no spaces), not a display name such as \"West Europe\"."
  }
}

variable "databricks_profile" {
  description = "Optional Databricks CLI/provider profile. Null uses standard environment, OIDC or service-principal authentication."
  type        = string
  default     = null

  validation {
    condition     = var.databricks_profile == null ? true : trimspace(var.databricks_profile) != ""
    error_message = "databricks_profile must be null or a nonempty profile name."
  }
}

variable "workspace_id" {
  description = "Numeric Databricks workspace id. Used as the globally unique suffix of the Key Vault name."
  type        = string
  nullable    = false

  validation {
    # ncc.tf converts it with tonumber() for the NCC binding.
    condition     = can(regex("^[0-9]+$", var.workspace_id))
    error_message = "workspace_id must be the numeric Databricks workspace id."
  }

  validation {
    # Key Vault names are capped at 24 characters (Azure naming rules); azure.tf names the vault kv-ucsec-<workspace_id>.
    condition     = length("kv-ucsec-${var.workspace_id}") <= 24
    error_message = "workspace_id is too long: the Key Vault name kv-ucsec-<workspace_id> must fit Key Vault's 24-character limit."
  }
}

variable "name" {
  description = "Base name for every resource (resource group, identity, connector, catalog)."
  type        = string
  default     = "uc-secrets-demo"
  nullable    = false

  validation {
    # Azure names use it as is (Log Analytics workspace names allow only letters, digits and hyphens); databricks.tf
    # turns the hyphens into underscores for the Unity Catalog credential and connection names, which Unity Catalog
    # stores in lowercase.
    condition     = can(regex("^[a-z0-9]+(-[a-z0-9]+)*$", var.name))
    error_message = "name must be lowercase letters and digits, optionally separated by single hyphens (e.g. uc-secrets-demo)."
  }
}

variable "catalog_name" {
  description = "Unity Catalog catalog managed by this configuration."
  type        = string
  default     = "uc_secrets_demo"
  nullable    = false

  validation {
    # The schema-binding module and Unity Gateway's secret_reference join it unquoted into <catalog>.<schema> names and
    # references, and Unity Catalog stores names in lowercase.
    condition     = can(regex("^[a-z0-9_]+$", var.catalog_name))
    error_message = "catalog_name must be lowercase letters, digits and underscores."
  }
}

variable "schema_name" {
  description = "Schema that gets bound to Azure Key Vault. It must stay free of Databricks-managed secrets."
  type        = string
  default     = "secrets"
  nullable    = false

  validation {
    # Same reason as catalog_name.
    condition     = can(regex("^[a-z0-9_]+$", var.schema_name))
    error_message = "schema_name must be lowercase letters, digits and underscores."
  }
}

variable "lane_secret_name" {
  description = "Key Vault secret name holding the APIM Databricks-lane shared secret. Single lowercase word so the Unity Catalog name is identical."
  type        = string
  default     = "apimlanekey"
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9]+$", var.lane_secret_name))
    error_message = "lane_secret_name must be a single lowercase word (letters and digits) so the Key Vault and Unity Catalog names are identical."
  }
}

variable "lane_secret_version" {
  description = "Write-only version counter (`value_wo_version`) for `azurerm_key_vault_secret.lane`. Increment to re-sync the APIM named value into Key Vault."
  type        = number
  default     = 1
  nullable    = false

  validation {
    condition     = var.lane_secret_version >= 1 && floor(var.lane_secret_version) == var.lane_secret_version
    error_message = "lane_secret_version must be a positive integer."
  }
}

variable "dummy_secret_name" {
  description = "Key Vault secret name of the plain dummy secret used to show a governed read with dbutils or the REST API."
  type        = string
  default     = "dummysecret"
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9]+$", var.dummy_secret_name))
    error_message = "dummy_secret_name must be a single lowercase word (letters and digits) so the Key Vault and Unity Catalog names are identical."
  }
}

variable "apim" {
  description = "The existing APIM instance and the named value that holds the Databricks-lane shared secret. The secret is copied from here ephemerally into Key Vault; it never enters a variable or the state file."
  type = object({
    subscription_id    = string
    resource_group     = string
    service_name       = string
    shared_secret_name = string
  })
  nullable = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.apim.subscription_id))
    error_message = "apim.subscription_id must be a subscription id (GUID)."
  }

  validation {
    condition     = alltrue([for v in [var.apim.resource_group, var.apim.service_name, var.apim.shared_secret_name] : try(trimspace(v) != "", false)])
    error_message = "apim.resource_group, apim.service_name and apim.shared_secret_name must all be set; shared_secret_name is the named value's identifier, never the secret itself."
  }
}

variable "apim_lane_base_url" {
  description = "Base URL of the static-key Databricks lane on APIM. The lane is a passthrough to LiteLLM, so /v1 lands on LiteLLM's OpenAI-compatible routes."
  type        = string
  nullable    = false

  validation {
    # Unity Gateway sends the lane key as a bearer header to this URL.
    condition     = startswith(var.apim_lane_base_url, "https://")
    error_message = "apim_lane_base_url must be an https:// URL."
  }
}

variable "apim_endpoint_route" {
  description = "Route appended to the base URL for chat completions. Set explicitly so the upstream URL is deterministic."
  type        = string
  default     = "chat/completions"
  nullable    = false
}

variable "litellm_models" {
  description = "Model aliases the Databricks-lane LiteLLM key may call. Set these to aliases allowed by your lane's key."
  type        = list(string)
  nullable    = false

  validation {
    # Each alias becomes one target of the model provider service.
    condition     = length(var.litellm_models) > 0 && length(distinct(var.litellm_models)) == length(var.litellm_models) && alltrue([for model in var.litellm_models : try(trimspace(model) != "", false)])
    error_message = "litellm_models must contain distinct, nonempty model aliases."
  }
}

variable "caller_principal" {
  description = "Optional user, group or service principal that gets EXECUTE on the model provider service to demonstrate a caller with no access to the secret."
  type        = string
  default     = null

  validation {
    condition     = var.caller_principal == null ? true : trimspace(var.caller_principal) != ""
    error_message = "caller_principal must be null (no grants) or name a user, group or service principal."
  }
}

variable "catalog_storage_root" {
  description = "Managed storage root for the catalog. Use an authorized Azure storage path available to your Unity Catalog metastore."
  type        = string
  nullable    = false

  validation {
    # Unity Catalog managed storage on Azure is ADLS Gen2, addressed as abfss://<container>@<account>.dfs.core.windows.net/...
    condition     = startswith(var.catalog_storage_root, "abfss://")
    error_message = "catalog_storage_root must be an abfss:// path."
  }
}

variable "enable_diagnostics" {
  description = "Create the optional Log Analytics workspace and Key Vault audit diagnostic setting. Log ingestion may incur charges."
  type        = bool
  default     = false
  nullable    = false
}

variable "enable_ncc_private_endpoint" {
  description = "Create an NCC with a private endpoint rule towards the vault, bind it to the workspace and approve the endpoint (ncc.tf). Needs databricks_account_id. Rules bill per hour and the binding cannot be removed by Terraform."
  type        = bool
  default     = false
  nullable    = false
}

variable "databricks_account_id" {
  description = "Databricks account id, used only by the account-level provider behind enable_ncc_private_endpoint."
  type        = string
  default     = null

  validation {
    condition     = var.databricks_account_id == null || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.databricks_account_id))
    error_message = "databricks_account_id must be the Databricks account id (GUID)."
  }

  validation {
    condition     = var.databricks_account_id != null || !var.enable_ncc_private_endpoint
    error_message = "databricks_account_id is required when enable_ncc_private_endpoint is true."
  }
}

variable "enable_network_security_perimeter" {
  description = "Put the vault inside a Network Security Perimeter (nsp.tf): perimeter, profile and association. Free. The association starts in Learning mode, which changes nothing until nsp_access_mode is switched."
  type        = bool
  default     = false
  nullable    = false
}

variable "nsp_access_mode" {
  description = "Access mode of the vault's perimeter association. Learning (portal: Transition) and Audit only log; Enforced denies every public request no inbound rule admits, trusted services included."
  type        = string
  default     = "Learning"
  nullable    = false

  validation {
    condition     = contains(["Learning", "Audit", "Enforced"], var.nsp_access_mode)
    error_message = "nsp_access_mode must be Learning, Audit or Enforced (the ARM values)."
  }
}

variable "nsp_admit_connector_subscription" {
  description = "Add an inbound perimeter rule that admits requests from resources in subscription_id, where the access connector's identity lives. Only takes effect with enable_network_security_perimeter."
  type        = bool
  default     = false
  nullable    = false
}

# Network controls default to the locked posture measured in notebooks/TOPOLOGY.md.
# The Terraform runner still needs its own authorized network path to the Key Vault data plane.
variable "public_network_access_enabled" {
  description = "Allow Key Vault public network access. False with Deny and AzureServices is the production posture."
  type        = bool
  default     = false
  nullable    = false
}

variable "network_acls" {
  description = "Key Vault firewall. AzureServices admits the trusted access-connector identity used by Unity Catalog. IP/subnet rules only admit public access when public_network_access_enabled is true."
  type = object({
    default_action             = optional(string, "Deny")
    bypass                     = optional(string, "AzureServices")
    ip_rules                   = optional(set(string), [])
    virtual_network_subnet_ids = optional(set(string), [])
  })
  default  = {}
  nullable = false

  validation {
    condition     = contains(["Allow", "Deny"], var.network_acls.default_action)
    error_message = "network_acls.default_action must be Allow or Deny."
  }
  validation {
    condition     = contains(["AzureServices", "None"], var.network_acls.bypass)
    error_message = "network_acls.bypass must be AzureServices or None."
  }
  validation {
    condition = length(var.network_acls.ip_rules) <= 1000 && alltrue([
      for ip in var.network_acls.ip_rules : try(
        can(cidrnetmask(strcontains(ip, "/") ? ip : "${ip}/32")) &&
        !contains(["10", "127", "0"], split(".", ip)[0]) &&
        !startswith(ip, "192.168.") &&
        !(split(".", ip)[0] == "172" && tonumber(split(".", ip)[1]) >= 16 && tonumber(split(".", ip)[1]) <= 31),
        false
      )
    ])
    error_message = "network_acls.ip_rules must contain at most 1000 IPv4 addresses or CIDRs, excluding private, loopback and unspecified ranges."
  }
  validation {
    condition = length(var.network_acls.virtual_network_subnet_ids) <= 200 && alltrue([
      for id in var.network_acls.virtual_network_subnet_ids : can(regex("(?i)^/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/resourceGroups/[^/]+/providers/Microsoft.Network/virtualNetworks/[^/]+/subnets/[^/]+$", id))
    ])
    error_message = "network_acls.virtual_network_subnet_ids must contain at most 200 complete Azure subnet resource IDs."
  }
}

variable "purge_protection_enabled" {
  description = "Protect a deleted vault from purge for the retention period. Azure does not allow disabling this once enabled."
  type        = bool
  default     = true
  nullable    = false
}

variable "soft_delete_retention_days" {
  description = "Key Vault soft-delete retention in days (7–90); changing it requires vault replacement."
  type        = number
  default     = 90
  nullable    = false

  validation {
    condition     = var.soft_delete_retention_days >= 7 && var.soft_delete_retention_days <= 90 && floor(var.soft_delete_retention_days) == var.soft_delete_retention_days
    error_message = "soft_delete_retention_days must be an integer between 7 and 90."
  }
}

variable "purge_soft_delete_on_destroy" {
  description = "Let AzureRM purge the soft-deleted vault on destroy. Keep false for production; purge protection also prevents immediate purge."
  type        = bool
  default     = false
  nullable    = false
}

variable "catalog_force_destroy" {
  description = "Permit recursive deletion of catalog contents. Keep false for production."
  type        = bool
  default     = false
  nullable    = false
}

variable "schema_force_destroy" {
  description = "Permit recursive deletion of schema contents. Keep false for production."
  type        = bool
  default     = false
  nullable    = false
}

variable "catalog_comment" {
  description = "Catalog description; can preserve an existing description during a configuration-only upgrade."
  type        = string
  default     = "Governed external secrets and Unity Gateway backed by Azure Key Vault."
  nullable    = false

  validation {
    condition     = trimspace(var.catalog_comment) != "" && length(var.catalog_comment) <= 4096
    error_message = "catalog_comment must contain 1–4096 characters and not be blank."
  }
}

variable "create_deployer_role_assignment" {
  description = "Grant the current deployment identity Key Vault Secrets Officer. Disable when deployment RBAC is provisioned separately."
  type        = bool
  default     = true
  nullable    = false
}

variable "create_dummy_secret" {
  description = "Create the optional nonproduction dummysecret fixture required by the measurement notebooks. Independent of the APIM lane secret."
  type        = bool
  default     = false
  nullable    = false

  validation {
    condition     = !var.create_dummy_secret || var.dummy_secret_name != var.lane_secret_name
    error_message = "dummy_secret_name and lane_secret_name must differ when create_dummy_secret is enabled."
  }
}

variable "tags" {
  description = "Azure tags applied to every taggable resource managed here (not existing APIM resources)."
  type        = map(string)
  default     = {}
  nullable    = false

  validation {
    condition = length(var.tags) <= 50 && alltrue([
      for key, value in var.tags : try(
        length(trimspace(key)) > 0 && length(key) <= 512 &&
        alltrue([for c in ["<", ">", "%", "&", "\\", "?", "/", "\""] : !strcontains(key, c)]) && length(value) <= 256,
        false
      )
    ])
    error_message = "tags permits at most 50 entries; keys must be nonempty, at most 512 characters, without < > % & \\ ? / or double quotes; values must be non-null and at most 256 characters."
  }
}

variable "databricks_account_auth_type" {
  description = "Optional account-provider authentication type for NCC. Null permits standard unified authentication (environment/OIDC/SP or local CLI)."
  type        = string
  default     = null

  validation {
    condition     = var.databricks_account_auth_type == null ? true : can(regex("^[a-z][a-z0-9-]*$", var.databricks_account_auth_type))
    error_message = "databricks_account_auth_type must be null or a Databricks unified-authentication type such as azure-cli or azure-client-secret."
  }
}
