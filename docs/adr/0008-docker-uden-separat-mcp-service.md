# ADR 0008: Hvorfor Docker — og hvorfor MCP-serveren ikke er en separat container

## Status

Accepteret.

## Kontekst

Platformen skal kunne startes af en anden udvikler med få kommandoer.
Docker/Docker Compose er standardsvaret. Spørgsmålet er, hvordan
komponenterne fordeles på containere — specifikt om MCP-serveren skal være
sin egen netværkstjeneste (som Postgres og MLflow er).

## Beslutning

**Docker Compose** med tre services: `api`, `postgres`, `mlflow`. MCP-serveren
er IKKE en fjerde service. Den kører som beskrevet i ADR 0001 som en
stdio-subprocess, spawnet af API-processen for hver agent-kørsel — det
matcher, hvordan MCP faktisk er designet til at bruges (en lokal, kortlivet
proces pr. klient-session), og introducerer ikke en netværksgrænse, der
alligevel kun ville blive brugt af én klient (orchestratoren selv).

API-imaget bruger en multi-stage build med `uv` til at installere
afhængigheder, kører som en non-root bruger, og kalder `git init` på det
konfigurerede workspace ved opstart (`docker/entrypoint.sh`), hvis det ikke
allerede er et git-repo.

## Konsekvenser

- Færre bevægelige dele i `compose.yaml` end en naiv "hver komponent er en
  container"-tilgang ville give.
- MLflow kører med sin egen SQLite backend-store i et navngivet volume —
  adskilt fra applikationens PostgreSQL-database, i tråd med princippet om at
  holde observability-data og applikations-state adskilt (ADR 0006).
- **Miljøbegrænsning under udvikling:** i den sandboxede udviklingsmiljø,
  dette projekt er bygget i, er udgående adgang til Docker Hub's
  image-lag-CDN (`production.cloudfront.docker.com`) blokeret af
  netværkspolitikken (bekræftet: manifest/auth-kald lykkes, men
  blob-download returnerer 403 Forbidden). `docker compose config` er
  valideret og korrekt; `docker build`/`docker compose up` kunne ikke
  gennemføres i selve udviklingsmiljøet. Dette er en miljøbegrænsning, ikke
  en fejl i Dockerfiles eller compose-filen — GitHub Actions-runnere har
  fuld internetadgang og vil kunne bygge og køre stacken (se
  `.github/workflows/ci.yml`, jobbet `docker-build`).
