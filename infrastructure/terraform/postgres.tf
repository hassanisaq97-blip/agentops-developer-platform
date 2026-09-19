# Én Azure Database for PostgreSQL Flexible Server, med to logisk adskilte
# databaser: `agentops` (applikations-state) og `mlflow` (MLflow backend
# store). Dette er en bevidst afvejning: fuld infrastrukturel adskillelse
# (to separate Flexible Server-instanser) ville koste dobbelt så meget for et
# projekt af denne skala uden en tilsvarende gevinst — logisk adskillelse via
# separate databaser/credentials bevarer princippet fra ADR 0006/0004 om at
# holde applikations-state og observability-data adskilt, uden at fordoble
# driftsomkostningen. Se docs/adr/0009-azure-arkitektur.md.
resource "azurerm_postgresql_flexible_server" "this" {
  name                          = "psql-${local.name_prefix}"
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  version                       = "16"
  administrator_login           = var.postgres_admin_username
  administrator_password        = var.postgres_admin_password
  storage_mb                    = 32768
  sku_name                      = "B_Standard_B1ms" # billigste burstable SKU — tilstrækkelig til demo-/lav-trafik-brug
  backup_retention_days         = 7
  public_network_access_enabled = true # se firewall-regel nedenfor; en produktions-opsætning ville bruge privat VNet-integration i stedet
  tags                          = local.tags
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = "agentops"
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "utf8"
}

resource "azurerm_postgresql_flexible_server_database" "mlflow" {
  name      = "mlflow"
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "utf8"
}
