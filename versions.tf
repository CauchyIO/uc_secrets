# Terraform and provider requirements, and the provider configurations the root module uses. The account-level
# Databricks provider behind the NCC add-on is configured in ncc.tf, next to the only resources that use it.

terraform {
  # Ephemeral resources (1.10) and write-only arguments (value_wo, 1.11) keep the APIM secret out of the state and plan.
  required_version = ">= 1.11"

  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0"
    }
    databricks = {
      source = "databricks/databricks"
      # Built and tested on 1.140.0 (see .terraform.lock.hcl); "~>" keeps upgrades on major version 1.
      version = "~> 1.140"
    }
    # Used only by modules/uc_schema_secret_storage, which declares the same constraint.
    external = {
      source  = "hashicorp/external"
      version = "~> 2.3"
    }
  }
}

provider "azapi" {
  subscription_id = var.apim.subscription_id
  tenant_id       = var.tenant_id
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = var.purge_soft_delete_on_destroy
    }
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
}

provider "databricks" {
  profile = var.databricks_profile
}
