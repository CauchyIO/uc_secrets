# Expose validated inputs for assertions; variables.tf links to the actual root declaration.
output "network" {
  value = { public = var.public_network_access_enabled, acls = var.network_acls }
}
output "lifecycle" {
  value = {
    purge_protection = var.purge_protection_enabled
    purge_on_destroy = var.purge_soft_delete_on_destroy
    catalog_force    = var.catalog_force_destroy
    schema_force     = var.schema_force_destroy
  }
}
output "options" {
  value = {
    fixture       = var.create_dummy_secret
    deployer_role = var.create_deployer_role_assignment
    profile       = var.databricks_profile
    tags          = var.tags
  }
}
