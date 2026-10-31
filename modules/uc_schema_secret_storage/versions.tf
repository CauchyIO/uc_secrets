# No provider configuration here: the module only uses the built-in terraform_data and hashicorp/external, which needs
# none. Databricks access goes through the CLI using the optional profile or environment authentication.

terraform {
  required_version = ">= 1.11"

  required_providers {
    external = {
      source  = "hashicorp/external"
      version = "~> 2.3"
    }
  }
}
