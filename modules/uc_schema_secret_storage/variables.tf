variable "databricks_profile" {
  description = "Optional CLI profile; null/empty uses standard Databricks unified authentication from the environment."
  type        = string
  default     = null
}

variable "catalog_name" {
  description = "Unity Catalog catalog name."
  type        = string
  nullable    = false

  validation {
    # The helper joins catalog and schema into a UC full name, then URL-encodes it.
    condition     = can(regex("^[A-Za-z0-9_-]+$", var.catalog_name))
    error_message = "catalog_name must be letters, digits, underscores and hyphens."
  }
}

variable "schema_name" {
  description = "Unity Catalog schema name to bind to the external secret manager connection."
  type        = string
  nullable    = false

  validation {
    # Same reason as catalog_name.
    condition     = can(regex("^[A-Za-z0-9_-]+$", var.schema_name))
    error_message = "schema_name must be letters, digits, underscores and hyphens."
  }
}

variable "schema_id" {
  description = "Provider id of the schema (databricks_schema.<name>.id). The helper never uses it: it is in the drift read's query only so that Terraform defers that read to apply while the schema does not exist yet."
  type        = string
  nullable    = false
}

variable "connection_name" {
  description = "Unity Catalog AZURE_KEY_VAULT connection name."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[A-Za-z0-9_-]+$", var.connection_name))
    error_message = "connection_name must be letters, digits, underscores and hyphens."
  }
}

variable "secret_names" {
  description = "Secret names in Azure Key Vault expected to appear inside the bound Unity Catalog schema."
  type        = set(string)
  default     = []
  nullable    = false

  validation {
    # Key Vault secret names are letters, digits and hyphens; the helper URL-encodes them in REST paths.
    condition     = alltrue([for name in var.secret_names : can(regex("^[A-Za-z0-9-]+$", name))])
    error_message = "secret_names must be Key Vault secret names: letters, digits and hyphens."
  }
}

variable "secret_versions" {
  description = "Key Vault secret version tokens so secret discovery re-runs when Key Vault secrets are created or updated."
  type        = list(string)
  default     = []
  nullable    = false
}
