# Kubernetes-manifests

Minimalt manifest-sæt til at køre platformen i en klynge: `postgres`,
`mlflow`, `agentops-api`, hver med Deployment + Service, readiness/liveness
probes og resource requests/limits. Ingen ekstra kompleksitet (ingen
Ingress/HPA/NetworkPolicy) er tilføjet, fordi projektets skala ikke
begrunder det — se `docs/adr/0010-kubernetes-eller-ikke.md`.

## Status: statisk valideret, ikke deployet

Manifesterne er valideret med:

```bash
kubectl kustomize . | kubeconform -summary -strict -
```

hvilket bekræfter, at alle 11 ressourcer er strukturelt gyldige mod de
officielle Kubernetes OpenAPI-schemas (kørt lokalt under udviklingen af dette
projekt — output: `Valid: 10, Invalid: 0, Errors: 0`, plus 1 for
`secret.example.yaml` separat).

De er IKKE deployet til en rigtig klynge. `kubectl apply` (selv med
`--dry-run=client`) kræver API-discovery mod en reachable klynge — der var
ingen `kind`/`minikube`/rigtig klynge tilgængelig i det miljø, dette blev
udviklet i. `kubeconform` blev derfor brugt som cluster-frit alternativ, da
det validerer strukturelt mod de samme schemas uden at kræve en klynge.

## Sådan bruges det (når en klynge er tilgængelig)

```bash
# 1. Byg og push images til et registry, klyngen kan trække fra, og opdater
#    image-referencerne i api.yaml/mlflow.yaml.
# 2. Opret secrets (aldrig fra secret.example.yaml direkte):
cp secret.example.yaml secret.local.yaml
# ... udfyld rigtige værdier i secret.local.yaml ...
kubectl apply -f secret.local.yaml

# 3. Deploy resten:
kubectl apply -k .
```
