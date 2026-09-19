# ADR 0010: Kubernetes-manifests som demonstration, ikke som anbefalet driftsform

## Status

Accepteret.

## Kontekst

Kubernetes er ofte "det man forventer at se" i en platform af denne type,
men er sjældent den rigtige første anbefaling for en applikation af denne
skala (én API-service, én database, én observability-service). Vi ville
demonstrere Kubernetes-kompetence uden at foreslå det som den faktiske
anbefalede driftsform — se også ADR 0009 om, hvorfor Azure-arkitekturen
foretrækker Container Apps.

## Beslutning

Et minimalt manifest-sæt (`infrastructure/kubernetes/`) med Deployment +
Service for hver af de tre komponenter, readiness/liveness probes, og
resource requests/limits — men ingen Ingress, HorizontalPodAutoscaler, eller
NetworkPolicy, fordi de ville tilføje kompleksitet uden at være begrundet af
et faktisk driftsbehov her.

## Konsekvenser

- Manifesterne er statisk valideret med `kubeconform` mod de officielle
  Kubernetes-schemas (cluster-frit — se `infrastructure/kubernetes/README.md`
  for hvorfor `kubectl apply --dry-run=client` ikke var muligt i
  udviklingsmiljøet: selv client-side dry-run kræver API-discovery mod en
  reachable klynge).
- De er IKKE deployet til en rigtig klynge (`kind`/`minikube`/cloud) i dette
  projekt. Det ville kræve enten et Kubernetes-miljø i sandboxen (ikke
  tilgængeligt) eller en cloud-konto (kræver credentials, se ADR 0009).
- Hvis platformen faktisk skulle køre i Kubernetes, ville de manglende
  stykker (Ingress/TLS, HPA, PodDisruptionBudget, NetworkPolicy) være det
  naturlige næste skridt — ikke tilføjet nu, fordi de ikke kan
  demonstreres/testes uden en klynge, og fordi at tilføje dem uprøvet ville
  være at hævde noget, vi ikke har verificeret.
