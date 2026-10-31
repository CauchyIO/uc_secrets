# Optional test fixture; independent of the production APIM lane secret.
# Disable for new production deployments. Existing instances migrate through moved.tf.

resource "azurerm_key_vault_secret" "dummy" {
  tags  = var.tags
  count = var.create_dummy_secret ? 1 : 0

  name             = var.dummy_secret_name
  key_vault_id     = azurerm_key_vault.demo.id
  value_wo         = "hello-from-key-vault"
  value_wo_version = 1
  content_type     = "Dummy value to demonstrate a governed read from Unity Catalog"

  depends_on = [azurerm_role_assignment.deployer_writes_secrets]
}
