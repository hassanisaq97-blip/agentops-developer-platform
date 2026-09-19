data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "this" {
  name                       = "kv-${local.name_prefix}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  sku_name                   = "standard"
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  soft_delete_retention_days = 7
  tags                       = local.tags

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = ["Get", "List", "Set", "Delete", "Purge"]
  }
}

resource "azurerm_key_vault_secret" "postgres_password" {
  name         = "postgres-admin-password"
  value        = var.postgres_admin_password
  key_vault_id = azurerm_key_vault.this.id
}

resource "azurerm_key_vault_secret" "anthropic_api_key" {
  name         = "anthropic-api-key"
  value        = var.anthropic_api_key != "" ? var.anthropic_api_key : "not-configured"
  key_vault_id = azurerm_key_vault.this.id
}

resource "azurerm_key_vault_secret" "openai_api_key" {
  name         = "openai-api-key"
  value        = var.openai_api_key != "" ? var.openai_api_key : "not-configured"
  key_vault_id = azurerm_key_vault.this.id
}

resource "azurerm_key_vault_secret" "database_url_app" {
  name         = "database-url-app"
  value        = "postgresql+psycopg://${var.postgres_admin_username}:${var.postgres_admin_password}@${azurerm_postgresql_flexible_server.this.fqdn}:5432/agentops"
  key_vault_id = azurerm_key_vault.this.id
}

resource "azurerm_key_vault_secret" "database_url_mlflow" {
  name         = "database-url-mlflow"
  value        = "postgresql://${var.postgres_admin_username}:${var.postgres_admin_password}@${azurerm_postgresql_flexible_server.this.fqdn}:5432/mlflow"
  key_vault_id = azurerm_key_vault.this.id
}

# Container Apps' system-assigned identiteter får læseadgang til Key Vault,
# så deres secrets kan referere direkte til Key Vault-værdier
# (`key_vault_secret_id`) i stedet for at duplikere følsomme værdier som
# almindelige Container App-secrets.
resource "azurerm_key_vault_access_policy" "api" {
  key_vault_id = azurerm_key_vault.this.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_container_app.api.identity[0].principal_id

  secret_permissions = ["Get"]
}

resource "azurerm_key_vault_access_policy" "mlflow" {
  key_vault_id = azurerm_key_vault.this.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_container_app.mlflow.identity[0].principal_id

  secret_permissions = ["Get"]
}
