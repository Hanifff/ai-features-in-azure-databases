output "resource_group_name" {
  value = azurerm_resource_group.demo.name
}

output "location" {
  value = azurerm_resource_group.demo.location
}

output "postgres_host" {
  value = azurerm_postgresql_flexible_server.demo.fqdn
}

output "cosmos_endpoint" {
  value = azurerm_cosmosdb_account.demo.endpoint
}

output "database_name" {
  value = var.database_name
}

output "cosmos_container_name" {
  value = var.cosmos_container_name
}

# Three endpoint shapes, not interchangeable. The models one serves the Azure AI
# inference SDK, the services one the project SDKs, and the openai one is the
# only form the PostgreSQL azure_ai extension accepts.
output "foundry_models_endpoint" {
  value = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.services.ai.azure.com/models"
}

output "foundry_services_endpoint" {
  value = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.services.ai.azure.com"
}

output "foundry_openai_endpoint" {
  value = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.openai.azure.com"
}

output "chat_deployment_name" {
  value = var.chat_deployment_name
}

output "postgres_chat_deployment_name" {
  value = var.postgres_chat_deployment_name
}

output "embedding_deployment_name" {
  value = "text-embedding-3-large"
}

output "embedding_small_deployment_name" {
  value = "text-embedding-3-small"
}

output "cosmos_max_throughput" {
  value = var.cosmos_max_throughput
}

# Everything scripts/setup.sh needs to write .env, in one read.
output "dotenv" {
  description = "Values for the application .env file. Contains no secrets: every service authenticates with Entra ID."
  value = {
    SUBSCRIPTION_ID               = var.subscription_id
    RESOURCE_GROUP                = azurerm_resource_group.demo.name
    FOUNDRY_MODELS_ENDPOINT       = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.services.ai.azure.com/models"
    FOUNDRY_SERVICES_ENDPOINT     = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.services.ai.azure.com"
    FOUNDRY_OPENAI_ENDPOINT       = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.openai.azure.com"
    FOUNDRY_CHAT_MODEL            = var.chat_deployment_name
    FOUNDRY_PG_CHAT_MODEL         = var.postgres_chat_deployment_name
    FOUNDRY_EMBEDDING_MODEL       = "text-embedding-3-large"
    FOUNDRY_EMBEDDING_SMALL_MODEL = "text-embedding-3-small"
    COSMOS_DB_ENDPOINT            = azurerm_cosmosdb_account.demo.endpoint
    COSMOS_DB_DATABASE            = var.database_name
    COSMOS_DB_CONTAINER           = var.cosmos_container_name
    POSTGRES_HOST                 = azurerm_postgresql_flexible_server.demo.fqdn
    POSTGRES_PORT                 = "5432"
    POSTGRES_DB                   = var.database_name
    POSTGRES_TABLE                = "tickets"
  }
}
