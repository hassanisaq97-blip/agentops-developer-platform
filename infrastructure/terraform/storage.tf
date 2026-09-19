# Blob storage til MLflow's artifact store (adskilt fra dets backend-store,
# som er PostgreSQL — se postgres.tf).
resource "azurerm_storage_account" "mlflow" {
  name                     = replace("st${local.name_prefix}mlflow", "-", "")
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  tags                     = local.tags
}

resource "azurerm_storage_container" "mlflow_artifacts" {
  name                  = "mlflow-artifacts"
  storage_account_id    = azurerm_storage_account.mlflow.id
  container_access_type = "private"
}
