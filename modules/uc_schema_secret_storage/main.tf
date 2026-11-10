# Binds a Unity Catalog schema to an external secret store via uc_secret_storage.py
# until databricks_schema exposes secret_storage natively (CauchyIO/terraform-provider-databricks#1).

locals {
  schema_full_name = "${var.catalog_name}.${var.schema_name}"
  helper_script    = "${path.module}/uc_secret_storage.py"
  profile          = coalesce(var.databricks_profile, "")
  is_bound = (
    data.external.binding_state.result.storage_type == "STORAGE_TYPE_EXTERNAL" &&
    data.external.binding_state.result.connection_name == var.connection_name
  )
}

data "external" "binding_state" {
  program = ["python3", local.helper_script, "read-binding"]

  query = {
    profile   = local.profile
    schema    = local.schema_full_name
    schema_id = var.schema_id # Defers read until the schema exists on first apply.
  }
}

resource "terraform_data" "binding" {
  input = {
    script     = local.helper_script
    profile    = local.profile
    schema     = local.schema_full_name
    connection = var.connection_name
  }

  triggers_replace = [
    local.schema_full_name,
    var.connection_name,
    local.is_bound ? "bound" : "drifted",
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

data "external" "secret" {
  for_each = var.secret_names
  program  = ["python3", local.helper_script, "read-secret"]

  query = {
    profile         = local.profile
    catalog         = var.catalog_name
    schema          = var.schema_name
    secret          = each.value
    binding_id      = terraform_data.binding.id
    secret_versions = join(",", var.secret_versions)
  }
}
