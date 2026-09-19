# ADR 0009: Azure Container Apps frem for AKS

## Status

Accepteret.

## Kontekst

Platformen består af to køreklare containere (api, mlflow) plus en managed
database og blob storage. Azure tilbyder flere måder at køre containere på —
de mest relevante her er Azure Kubernetes Service (AKS) og Azure Container
Apps.

## Beslutning

**Azure Container Apps.** AKS blev fravalgt, fordi det ville kræve drift af
en hel Kubernetes-kontrolplan (node-pools, opgraderinger, RBAC, netværk) for
at køre to simple, stateløse containere — kompleksitet uden en tilsvarende
gevinst her. Container Apps giver samme kerneegenskaber, vi faktisk har brug
for (containere, autoskalering, managed identity, ingress, integration med
Log Analytics), uden at vi selv skal drifte en klynge.

Databaser og storage bruger managed Azure-tjenester (PostgreSQL Flexible
Server, Storage Account) i stedet for at køre Postgres/objekt-storage som
containere — det er den generelt anbefalede praksis for stateful workloads i
en cloud-native arkitektur: patching, backup og high availability
outsources til platformen.

Se `docs/adr/0010-kubernetes-eller-ikke.md` for, hvorfor Kubernetes-manifests
alligevel findes i repositoryet som en separat demonstration.

## Konsekvenser

- Én PostgreSQL Flexible Server-instans med to databaser (`agentops`,
  `mlflow`) i stedet for to separate serverinstanser — en bevidst
  kompromis mellem principiel adskillelse af applikations-state og
  observability-data (ADR 0006/0004) og driftsomkostning. Fuld
  infrastrukturel adskillelse (to servere) ville være det naturlige næste
  skridt ved reel produktionslast.
- Secrets (database-URL, LLM API-nøgler) ligger i Azure Key Vault; hver
  Container App læser dem via sin system-assignede managed identity
  (`key_vault_secret_id` + `identity = "System"`) i stedet for at duplikere
  dem som almindelige Container App-secrets.
- **Ikke deployet:** denne konfiguration er skrevet og formateringsvalideret
  (`terraform fmt`), men `terraform init`/`validate`/`plan`/`apply` kræver
  enten Azure-credentials (ikke tilgængelige i dette miljø) eller adgang til
  `registry.terraform.io` for at hente `azurerm`-provideren (blokeret af
  netværkspolitikken i udviklingsmiljøet — se
  `infrastructure/terraform/README.md`). Konfigurationen er derfor
  klargjort, men ikke verificeret ved en faktisk deployment.
