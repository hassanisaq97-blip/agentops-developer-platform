# Azure Container Apps blev valgt frem for AKS — se
# docs/adr/0009-azure-arkitektur.md. To Container Apps (api, mlflow) i ét
# managed Container Apps Environment.

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${local.name_prefix}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  tags                       = local.tags
}

resource "azurerm_container_app" "mlflow" {
  name                         = "ca-${local.name_prefix}-mlflow"
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type = "SystemAssigned"
  }

  registry {
    server               = azurerm_container_registry.this.login_server
    username             = azurerm_container_registry.this.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.this.admin_password
  }

  secret {
    name                = "database-url-mlflow"
    key_vault_secret_id = azurerm_key_vault_secret.database_url_mlflow.id
    identity            = "System"
  }

  template {
    min_replicas = 1
    max_replicas = 1 # PostgreSQL backend store understøtter flere replicas, men vi holder MLflow på ét replika for enkelthed her

    container {
      name   = "mlflow"
      image  = var.mlflow_image != "" ? var.mlflow_image : "${azurerm_container_registry.this.login_server}/agentops-mlflow:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "MLFLOW_BACKEND_STORE_URI"
        secret_name = "database-url-mlflow"
      }
      env {
        name  = "MLFLOW_ARTIFACT_ROOT"
        value = "wasbs://${azurerm_storage_container.mlflow_artifacts.name}@${azurerm_storage_account.mlflow.name}.blob.core.windows.net/"
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/health"
        port      = 5000
      }
      readiness_probe {
        transport = "HTTP"
        path      = "/health"
        port      = 5000
      }
    }
  }

  ingress {
    external_enabled = false # kun tilgængelig internt i Container Apps Environment, fra api-appen
    target_port      = 5000
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${local.name_prefix}-api"
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type = "SystemAssigned"
  }

  registry {
    server               = azurerm_container_registry.this.login_server
    username             = azurerm_container_registry.this.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.this.admin_password
  }
  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url_app.id
    identity            = "System"
  }
  secret {
    name                = "anthropic-api-key"
    key_vault_secret_id = azurerm_key_vault_secret.anthropic_api_key.id
    identity            = "System"
  }
  secret {
    name                = "openai-api-key"
    key_vault_secret_id = azurerm_key_vault_secret.openai_api_key.id
    identity            = "System"
  }

  template {
    min_replicas = 1
    max_replicas = 3

    container {
      name   = "api"
      image  = var.api_image != "" ? var.api_image : "${azurerm_container_registry.this.login_server}/agentops-api:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name  = "MLFLOW_TRACKING_URI"
        value = "https://${azurerm_container_app.mlflow.latest_revision_fqdn}"
      }
      env {
        name  = "LLM_DEFAULT_PROVIDER"
        value = var.anthropic_api_key != "" ? "anthropic" : "test"
      }
      env {
        name        = "ANTHROPIC_API_KEY"
        secret_name = "anthropic-api-key"
      }
      env {
        name        = "OPENAI_API_KEY"
        secret_name = "openai-api-key"
      }
      env {
        name  = "AGENT_AUTO_APPROVE_HIGH_RISK"
        value = "false"
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/health"
        port      = 8000
      }
      readiness_probe {
        transport = "HTTP"
        path      = "/ready"
        port      = 8000
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
