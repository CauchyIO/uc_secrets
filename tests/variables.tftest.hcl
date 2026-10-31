# The fixture loads the real root variables.tf via a relative symlink.
# No providers, ephemeral APIM reads or live state are used.
variables {
  subscription_id      = "00000000-0000-0000-0000-000000000000"
  tenant_id            = "00000000-0000-0000-0000-000000000000"
  workspace_id         = "000000000000000"
  apim_lane_base_url   = "https://example.invalid/v1"
  catalog_storage_root = "abfss://catalog@example.dfs.core.windows.net/root"
  litellm_models       = ["example-model"]
  apim = {
    subscription_id    = "00000000-0000-0000-0000-000000000000"
    resource_group     = "rg-test"
    service_name       = "apim-test"
    shared_secret_name = "lane"
  }
}
run "production_defaults" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  assert {
    condition     = !output.network.public && output.network.acls.default_action == "Deny" && output.network.acls.bypass == "AzureServices"
    error_message = "The default vault must use the locked production posture."
  }
  assert {
    condition     = output.lifecycle.purge_protection && !output.lifecycle.purge_on_destroy && !output.lifecycle.catalog_force && !output.lifecycle.schema_force
    error_message = "Production lifecycle protection must be enabled."
  }
  assert {
    condition     = !output.options.fixture && output.options.profile == null
    error_message = "Production defaults must omit the test fixture and allow environment auth."
  }
}
run "explicit_test_fixture_and_existing_rbac" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables {
    create_dummy_secret             = true
    create_deployer_role_assignment = false
    databricks_profile              = "profile with ' quotes"
    tags                            = { environment = "test" }
  }
  assert {
    condition     = output.options.fixture && !output.options.deployer_role && output.options.tags.environment == "test"
    error_message = "Fixture, externally managed RBAC and tags must be honored."
  }
}
run "invalid_retention" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables { soft_delete_retention_days = 6 }
  expect_failures = [var.soft_delete_retention_days]
}
run "fractional_retention" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables { soft_delete_retention_days = 7.5 }
  expect_failures = [var.soft_delete_retention_days]
}
run "invalid_default_action" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables { network_acls = { default_action = "permit" } }
  expect_failures = [var.network_acls]
}
run "invalid_bypass" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables { network_acls = { bypass = "Everything" } }
  expect_failures = [var.network_acls]
}
run "invalid_ip" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables { network_acls = { ip_rules = ["10.1.0.1", "not-an-ip", "::1"] } }
  expect_failures = [var.network_acls]
}
run "invalid_subnet" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables { network_acls = { virtual_network_subnet_ids = ["not-a-subnet"] } }
  expect_failures = [var.network_acls]
}
run "invalid_profile" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables { databricks_profile = " " }
  expect_failures = [var.databricks_profile]
}
run "invalid_tags" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables { tags = { "invalid/key" = "test" } }
  expect_failures = [var.tags]
}
run "fixture_collision" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables {
    create_dummy_secret = true
    dummy_secret_name   = "apimlanekey"
  }
  expect_failures = [var.create_dummy_secret]
}
run "invalid_version" {
  command = plan
  module { source = "./tests/fixtures/variables" }
  variables { lane_secret_version = 1.5 }
  expect_failures = [var.lane_secret_version]
}
