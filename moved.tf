# Preserve existing objects when enabling optional resource creation controls.
moved {
  from = azurerm_key_vault_secret.dummy
  to   = azurerm_key_vault_secret.dummy[0]
}

moved {
  from = azurerm_role_assignment.deployer_writes_secrets
  to   = azurerm_role_assignment.deployer_writes_secrets[0]
}
