data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "demo" {
  name     = local.names.resource_group
  location = var.location
  tags     = var.tags
}

resource "azurerm_role_assignment" "admin_rg_owner" {
  for_each = toset(local.admin_object_ids)

  scope                = azurerm_resource_group.demo.id
  role_definition_name = "Owner"
  principal_id         = each.value
  principal_type       = var.admin_principal_type
}

# ---------------------------------------------------------------------------
# Azure Database for PostgreSQL flexible server
# ---------------------------------------------------------------------------

resource "azurerm_postgresql_flexible_server" "demo" {
  name                = local.names.postgres
  resource_group_name = azurerm_resource_group.demo.name
  location            = var.location
  version             = var.postgres_version
  sku_name            = var.postgres_sku_name
  storage_mb          = var.postgres_storage_mb

  public_network_access_enabled = true
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false

  # Entra only. No password is generated, stored or rotated anywhere.
  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = var.tenant_id
  }

  # azure_ai calls Foundry as this identity, so no API key ever leaves the
  # database and none is stored in it.
  identity {
    type = "SystemAssigned"
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }
}

resource "azurerm_postgresql_flexible_server_active_directory_administrator" "demo" {
  server_name         = azurerm_postgresql_flexible_server.demo.name
  resource_group_name = azurerm_resource_group.demo.name
  tenant_id           = var.tenant_id
  object_id           = var.postgres_entra_admin_object_id
  principal_name      = var.postgres_entra_admin_name
  principal_type      = var.postgres_entra_admin_type
}

# An allow-list only. CREATE EXTENSION still has to run per database, which
# tools/load_postgres.py does.
resource "azurerm_postgresql_flexible_server_configuration" "azure_extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.demo.id
  value     = local.postgres_extensions
}

resource "azurerm_postgresql_flexible_server_configuration" "shared_preload_libraries" {
  name      = "shared_preload_libraries"
  server_id = azurerm_postgresql_flexible_server.demo.id
  value     = local.postgres_shared_preload_libraries

  depends_on = [azurerm_postgresql_flexible_server_configuration.azure_extensions]
}

resource "azurerm_postgresql_flexible_server_database" "demo" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.demo.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  count = var.allow_azure_services ? 1 : 0

  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.demo.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allowed" {
  for_each = local.firewall_ranges

  name             = each.key
  server_id        = azurerm_postgresql_flexible_server.demo.id
  start_ip_address = each.value.start
  end_ip_address   = each.value.end
}

# ---------------------------------------------------------------------------
# Azure Cosmos DB for NoSQL
# ---------------------------------------------------------------------------

resource "azurerm_cosmosdb_account" "demo" {
  name                = local.names.cosmos
  resource_group_name = azurerm_resource_group.demo.name
  location            = var.location
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  public_network_access_enabled = true
  automatic_failover_enabled    = false
  free_tier_enabled             = false
  local_authentication_enabled  = false

  # Vector and full-text policies are immutable once a container exists, so both
  # capabilities have to be right at create time.
  capabilities {
    name = "EnableNoSQLVectorSearch"
  }

  capabilities {
    name = "EnableNoSQLFullTextSearch"
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = var.location
    failover_priority = 0
    zone_redundant    = var.cosmos_zone_redundant
  }

  ip_range_filter = local.cosmos_ip_filter

  tags = var.tags
}

resource "azurerm_cosmosdb_sql_database" "demo" {
  name                = var.database_name
  resource_group_name = azurerm_resource_group.demo.name
  account_name        = azurerm_cosmosdb_account.demo.name
}

# The container is created by tools/load_cosmos.py rather than here, because the
# vector and full-text index policies belong with the code that decides which
# fields are embedded and searched.

resource "azurerm_cosmosdb_sql_role_assignment" "admin_data" {
  for_each = toset(local.admin_object_ids)

  resource_group_name = azurerm_resource_group.demo.name
  account_name        = azurerm_cosmosdb_account.demo.name
  role_definition_id  = "${azurerm_cosmosdb_account.demo.id}/sqlRoleDefinitions/${local.cosmos_data_contributor_role_id}"
  principal_id        = each.value
  scope               = azurerm_cosmosdb_account.demo.id
}

# ---------------------------------------------------------------------------
# Microsoft Foundry (Azure AI Services)
# ---------------------------------------------------------------------------

resource "azurerm_cognitive_account" "foundry" {
  name                = local.names.foundry
  resource_group_name = azurerm_resource_group.demo.name
  location            = var.location
  kind                = "AIServices"
  sku_name            = var.foundry_sku_name

  # Required for the https://<name>.openai.azure.com endpoint form, which is the
  # only shape the PostgreSQL azure_ai extension accepts.
  custom_subdomain_name         = local.names.foundry
  public_network_access_enabled = true
  local_auth_enabled            = false

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

resource "azurerm_cognitive_deployment" "models" {
  for_each = var.model_deployments

  name                 = each.key
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = each.value.model_name
    version = each.value.model_version
  }

  sku {
    name     = each.value.sku_name
    capacity = each.value.capacity
  }
}

# This is what makes azure_openai.create_embeddings() and azure_ai.generate()
# work from inside SQL without an API key.
resource "azurerm_role_assignment" "postgres_to_foundry" {
  scope                = azurerm_cognitive_account.foundry.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_postgresql_flexible_server.demo.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "admin_foundry_openai" {
  for_each = toset(local.admin_object_ids)

  scope                = azurerm_cognitive_account.foundry.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = each.value
  principal_type       = var.admin_principal_type
}

# The /models inference endpoint is Models-as-a-Service, not Azure OpenAI. It
# needs Microsoft.CognitiveServices/accounts/MaaS/*, which OpenAI User does not
# grant. Without this the SDK fails with PermissionDenied on MaaS/embeddings/action.
resource "azurerm_role_assignment" "admin_foundry_maas" {
  for_each = toset(local.admin_object_ids)

  scope                = azurerm_cognitive_account.foundry.id
  role_definition_name = "Azure AI Developer"
  principal_id         = each.value
  principal_type       = var.admin_principal_type
}
