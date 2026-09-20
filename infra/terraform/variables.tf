variable "subscription_id" {
  description = "Azure subscription the demo is deployed into."
  type        = string
}

variable "tenant_id" {
  description = "Entra tenant id."
  type        = string
}

variable "location" {
  description = <<-EOT
    Single region for the whole stack. It has to be a region that offers the
    model deployments in var.model_deployments. Check with:
      az cognitiveservices model list -l <region> -o table
  EOT
  type        = string
  default     = "swedencentral"
}

variable "name_prefix" {
  description = "Short, DNS-safe token used to build globally unique resource names."
  type        = string
  default     = "aidb"

  validation {
    condition     = can(regex("^[a-z0-9]{2,12}$", var.name_prefix))
    error_message = "name_prefix must be 2 to 12 lowercase letters or digits."
  }
}

variable "resource_group_name" {
  description = "Resource group to create. Leave empty to derive it from name_prefix and location."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    lifecycle = "poc"
    project   = "ai-features-in-azure-databases"
  }
}

# ---------------------------------------------------------------------------
# Access. Everything is Entra only, so these role assignments are the whole of
# the access model. There are no keys to hand out.
# ---------------------------------------------------------------------------

variable "admin_object_ids" {
  description = <<-EOT
    Entra object ids granted Owner on the resource group, plus the Cosmos data
    plane and Foundry inference. Leave empty to grant the identity running
    Terraform, which is what scripts/setup.sh does.
  EOT
  type        = list(string)
  default     = []
}

variable "admin_principal_type" {
  description = "Principal type of admin_object_ids: User, Group or ServicePrincipal."
  type        = string
  default     = "User"
}

variable "postgres_entra_admin_object_id" {
  description = "Entra object id made PostgreSQL administrator. A flexible server with password auth disabled is unreachable without one."
  type        = string
}

variable "postgres_entra_admin_name" {
  description = "User principal name or group display name matching postgres_entra_admin_object_id."
  type        = string
}

variable "postgres_entra_admin_type" {
  description = "Principal type of the PostgreSQL administrator: User, Group or ServicePrincipal."
  type        = string
  default     = "User"
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

variable "allowed_ip_rules" {
  description = <<-EOT
    Source CIDRs allowed through the PostgreSQL and Cosmos firewalls.

    Both engines are Entra only here and Cosmos has key authentication disabled,
    so reaching the endpoint still requires a valid token and a data-plane role
    assignment. Narrow this to your own address for anything long-lived.
  EOT
  type        = list(string)
  default     = []
}

variable "allow_all_networks" {
  description = "Open both databases to every source address, ignoring allowed_ip_rules. Convenient when presenting from a network whose address is unknown in advance."
  type        = bool
  default     = false
}

variable "allow_azure_services" {
  description = "Allow Azure services through the PostgreSQL and Cosmos firewalls."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

variable "postgres_sku_name" {
  description = "General Purpose rather than Burstable: DiskANN index builds are CPU bound and burst credits run out partway through the load."
  type        = string
  default     = "GP_Standard_D4ds_v5"
}

variable "postgres_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "16"
}

variable "postgres_storage_mb" {
  description = "PostgreSQL storage in MB."
  type        = number
  default     = 32768
}

variable "database_name" {
  description = "Database created in both engines."
  type        = string
  default     = "ops-db"
}

variable "cosmos_container_name" {
  description = "Cosmos container holding the tickets."
  type        = string
  default     = "tickets"
}

variable "cosmos_max_throughput" {
  description = <<-EOT
    Autoscale ceiling for the container, in RU/s. The floor is a tenth of this.

    Azure will not later let you set a ceiling below a tenth of the highest value
    ever provisioned on the container, so briefly raising this is not reversible.
  EOT
  type        = number
  default     = 5000
}

variable "foundry_sku_name" {
  description = "Azure AI Services SKU."
  type        = string
  default     = "S0"
}

variable "model_deployments" {
  description = <<-EOT
    Foundry model deployments. The map key is the deployment name, which is what
    goes into .env, not the model name. Capacity is in thousands of tokens per
    minute.

    SKUs are region specific. Verify availability with:
      az cognitiveservices model list -l <region> -o table
  EOT
  type = map(object({
    model_name    = string
    model_version = string
    sku_name      = string
    capacity      = number
  }))
  default = {
    "text-embedding-3-large" = {
      model_name    = "text-embedding-3-large"
      model_version = "1"
      sku_name      = "GlobalStandard"
      capacity      = 50
    }
    "text-embedding-3-small" = {
      model_name    = "text-embedding-3-small"
      model_version = "1"
      sku_name      = "GlobalStandard"
      capacity      = 120
    }
    "gpt-5.5" = {
      model_name    = "gpt-5.5"
      model_version = "2026-04-24"
      sku_name      = "GlobalStandard"
      capacity      = 100
    }
    # azure_ai.generate() sends temperature 0.2 and offers no way to override it.
    # Reasoning models that accept only the default temperature reject the call,
    # so the in-database panel needs a deployment like this one.
    "gpt-4.1-mini" = {
      model_name    = "gpt-4.1-mini"
      model_version = "2025-04-14"
      sku_name      = "GlobalStandard"
      capacity      = 50
    }
  }
}

variable "chat_deployment_name" {
  description = "Deployment the application uses for chat. Must be a key of model_deployments."
  type        = string
  default     = "gpt-5.5"
}

variable "postgres_chat_deployment_name" {
  description = "Deployment azure_ai.generate() uses from inside PostgreSQL. Must accept a caller supplied temperature."
  type        = string
  default     = "gpt-4.1-mini"
}

variable "cosmos_zone_redundant" {
  description = "Zone redundancy for the Cosmos account. Capacity constrained in some regions, where it fails with ServiceUnavailable."
  type        = bool
  default     = false
}
