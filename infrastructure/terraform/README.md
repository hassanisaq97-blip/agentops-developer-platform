# Terraform — Azure

Infrastructure as Code til at deploye platformen til Azure Container Apps.
Se `docs/adr/0009-azure-arkitektur.md` for begrundelsen for arkitekturen.

## Status: fmt valideret, init/validate ikke muligt i udviklingsmiljøet

```bash
terraform fmt -check -recursive   # ✅ bestået (0 diff)
terraform init                    # ❌ blokeret — se nedenfor
terraform validate                # ❌ kræver init (kan ikke tjekke provider-schema uden)
```

`terraform init` skal hente `hashicorp/azurerm`-provideren fra
`registry.terraform.io`. I det sandboxede miljø, dette projekt er udviklet i,
er udgående adgang til `registry.terraform.io` blokeret af netværkspolitikken
(bekræftet: `403 Forbidden` på discovery-endpointet). Dette er en
miljøbegrænsning, ikke en fejl i konfigurationen — i et almindeligt
udviklingsmiljø eller en CI-runner med normal internetadgang vil `terraform
init && terraform validate` fungere uden ændringer.

**Der er IKKE foretaget nogen faktisk Azure-deployment.** Det ville kræve
Azure-credentials, som ikke er tilgængelige/relevante i dette miljø, og ville
medføre reelle omkostninger.

## Hvordan det faktisk bruges (med credentials)

```bash
az login
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars
# ... udfyld terraform.tfvars ...
terraform init
terraform plan
terraform apply

# Byg og push images til det oprettede registry:
az acr login --name <container_registry_login_server uden ".azurecr.io">
docker build -f ../../docker/api.Dockerfile -t <login_server>/agentops-api:latest ../..
docker push <login_server>/agentops-api:latest
docker build -f ../../docker/mlflow.Dockerfile -t <login_server>/agentops-mlflow:latest ../..
docker push <login_server>/agentops-mlflow:latest

# Opdatér api_image/mlflow_image i terraform.tfvars, og kør terraform apply igen.
```

## Ressourcer denne konfiguration opretter

| Ressource | Formål |
|---|---|
| Resource Group | Container for alt andet |
| Container Registry (Basic) | Hoster API- og MLflow-images |
| PostgreSQL Flexible Server (B1ms) + to databaser | Applikations-state (`agentops`) og MLflow backend store (`mlflow`) — se ADR 0009 for afvejningen mod to separate servere |
| Storage Account + Blob Container | MLflow artifact store |
| Key Vault | Database-password og LLM API-nøgler; Container Apps læser dem via managed identity |
| Log Analytics Workspace | Bagvedliggende logging for Container Apps Environment |
| Container Apps Environment | Managed miljø for de to Container Apps |
| Container App: `api` | Kører FastAPI-applikationen, offentligt tilgængelig |
| Container App: `mlflow` | Kører MLflow tracking-serveren, kun internt tilgængelig |
