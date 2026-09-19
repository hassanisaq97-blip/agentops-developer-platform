output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "container_registry_login_server" {
  value = azurerm_container_registry.this.login_server
}

output "api_url" {
  value       = "https://${azurerm_container_app.api.latest_revision_fqdn}"
  description = "Offentlig URL til FastAPI-applikationen."
}

output "postgres_fqdn" {
  value = azurerm_postgresql_flexible_server.this.fqdn
}

output "key_vault_name" {
  value = azurerm_key_vault.this.name
}
