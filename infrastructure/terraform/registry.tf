# Azure Container Registry — hoster de images, `docker/api.Dockerfile` og
# `docker/mlflow.Dockerfile` bygger.
resource "azurerm_container_registry" "this" {
  name                = replace("acr${local.name_prefix}", "-", "")
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Basic"
  admin_enabled       = true # simpelt for dette projekts skala; en produktions-opsætning ville bruge managed identity + AcrPull-rolle i stedet
  tags                = local.tags
}
