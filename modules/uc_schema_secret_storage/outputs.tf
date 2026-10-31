output "schema_full_name" {
  description = "Full Unity Catalog schema name (<catalog>.<schema>) bound to the external secret store."
  value       = local.schema_full_name
}

output "secrets" {
  description = "Map of discovered Unity Catalog external secrets keyed by secret name."
  value = {
    for name, d in data.external.secret : name => {
      full_name          = d.result.full_name
      securable_kind     = d.result.securable_kind
      external_secret_id = d.result.external_secret_id
    }
  }
}
