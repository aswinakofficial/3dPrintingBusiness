terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }

  # Uncomment to use remote state storage
  # backend "azurerm" {
  #   resource_group_name  = "rg-terraform-state"
  #   storage_account_name = "stterraformstate"
  #   container_name       = "tfstate"
  #   key                  = "3dfigurine.tfstate"
  # }

  # Local state (default - good for development)
  # backend "local" {
  #   path = "terraform.tfstate"
  # }
}

provider "azurerm" {
  features {
    virtual_machine {
      graceful_shutdown              = true
      skip_shutdown_and_force_delete = false
    }
  }

  skip_provider_registration = false
}
