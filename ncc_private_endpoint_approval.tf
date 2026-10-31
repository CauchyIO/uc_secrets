# Optional NCC approval compatibility bridge, separate from the Beta UC binding.
# ARM supports declarative approval using azapi_update_resource on
# Microsoft.KeyVault/vaults/privateEndpointConnections. Its generated child ID must first
# be discovered by matching properties.privateEndpoint.id to the NCC endpoint_name.
# The live child name matches endpoint_name; the helper verifies the match rather than
# assuming it for every rule, and handles delayed ARM visibility.
# Preserve the existing terraform_data address, inputs and rule_id trigger: changing to AzAPI
# would require a separate state/ownership migration on an already approved live endpoint.
# AzAPI 2.13.0 azapi_update_resource does not implement import, so it cannot adopt
# this approval through an import block without planning a new approval operation.
# No destroy hook: deleting this bookkeeping resource must never revoke endpoint approval.

# The endpoint stays PENDING until the vault owner approves the connection on the Azure side, and expires unapproved
# after fourteen days. The helper approves the one connection whose private endpoint carries the rule's endpoint name
# and fails if that connection is not there yet.
resource "terraform_data" "approve_private_endpoint" {
  count = var.enable_ncc_private_endpoint ? 1 : 0

  input = {
    vault_id      = azurerm_key_vault.demo.id
    endpoint_name = databricks_mws_ncc_private_endpoint_rule.key_vault[0].endpoint_name
  }

  triggers_replace = [databricks_mws_ncc_private_endpoint_rule.key_vault[0].rule_id]

  provisioner "local-exec" {
    command = "python3 \"$NCC_APPROVAL_SCRIPT\" approve"
    environment = {
      NCC_APPROVAL_SCRIPT = "${path.module}/scripts/ncc_private_endpoint.py"
      NCC_VAULT_ID        = self.input.vault_id
      NCC_ENDPOINT_NAME   = self.input.endpoint_name
    }
  }
}

