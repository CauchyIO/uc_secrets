# Binds a Unity Catalog schema to an external secret store (Beta `secret_storage`, no provider resource yet) through
# uc_secret_storage.py, which calls the Databricks CLI using unified authentication. The provisioners are deliberate: they are
# the compatibility adapter for this API until databricks_schema exposes secret_storage.

locals {
  schema_full_name = "${var.catalog_name}.${var.schema_name}"
  helper_script    = "${path.module}/uc_secret_storage.py"
}

# Drift detection: query the current schema secret_storage state during plan/refresh.
data "external" "binding_state" {
  program = ["python3", local.helper_script, "read-binding"]

  query = {
    profile = var.databricks_profile == null ? "" : var.databricks_profile
    schema  = local.schema_full_name
    # Not used by the helper. While the schema does not exist yet its id is unknown, so Terraform defers this read to
    # apply (after the schema is created) instead of reading a missing schema during plan.
    schema_id = var.schema_id
  }
}

resource "terraform_data" "binding" {
  input = {
    script     = local.helper_script
    profile    = var.databricks_profile == null ? "" : var.databricks_profile
    schema     = local.schema_full_name
    connection = var.connection_name
  }

  # Re-apply if the target schema/connection changes OR if the live schema binding drifted outside Terraform.
  triggers_replace = [
    local.schema_full_name,
    var.connection_name,
    data.external.binding_state.result.storage_type == "STORAGE_TYPE_EXTERNAL" && data.external.binding_state.result.connection_name == var.connection_name ? "bound" : "drifted",
  ]

  provisioner "local-exec" {
    command = "python3 \"$UC_STORAGE_SCRIPT\" bind"
    environment = {
      UC_STORAGE_SCRIPT     = self.input.script
      UC_STORAGE_PROFILE    = self.input.profile
      UC_STORAGE_SCHEMA     = self.input.schema
      UC_STORAGE_CONNECTION = self.input.connection
    }
  }

  provisioner "local-exec" {
    when    = destroy
    command = "python3 \"$UC_STORAGE_SCRIPT\" unbind"
    environment = {
      UC_STORAGE_SCRIPT  = self.input.script
      UC_STORAGE_PROFILE = self.input.profile
      UC_STORAGE_SCHEMA  = self.input.schema
    }
  }
}

# Read-verified secret discovery: lists the bound schema (triggering lazy import from Key Vault)
# and returns each secret's Unity Catalog metadata (`full_name`, `securable_kind`, `external_secret_id`).
data "external" "secret" {
  for_each = var.secret_names

  program = ["python3", local.helper_script, "read-secret"]

  query = {
    profile         = var.databricks_profile == null ? "" : var.databricks_profile
    catalog         = var.catalog_name
    schema          = var.schema_name
    secret          = each.value
    binding_id      = terraform_data.binding.id
    secret_versions = join(",", var.secret_versions)
  }
}
