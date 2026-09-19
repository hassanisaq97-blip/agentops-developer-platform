# ADR 0004: Hvorfor MLflow til observability

## Status

Accepteret.

## Kontekst

En agent-kørsel involverer flere LLM-kald og tool-kald i rækkefølge. Uden
tracing er det umuligt at fejlsøge, hvorfor en agent tog en bestemt
beslutning, eller at sammenligne latency/token-forbrug på tværs af kørsler.
Vi overvejede at bygge et hjemmerullet trace-format oven på structlog, men
det ville genopfinde noget, der allerede findes som en veletableret,
open source-standard i ML/AI-økosystemet.

## Beslutning

MLflow Tracing (`mlflow-skinny` som klient-afhængighed). Manuelle spans
(`mlflow.start_span`) omkring tre niveauer: agent-kørslen som helhed
(`AGENT`-span), hvert LLM-kald (`LLM`-span), og hvert MCP tool-kald
(`TOOL`-span) — verificeret ved faktisk at køre en agent-kørsel og bekræfte,
at traces og spans dukker op (`tests/integration/test_mlflow_tracing.py`),
fremfor at antage at instrumenteringen virker.

Vi bruger manuelle spans frem for `@mlflow.trace`-dekoratoren de fleste
steder, fordi dekoratoren automatisk ville serialisere `self` (en hel
`AgentOrchestrator`/`LLMGateway`-instans) som span-input — manuelle spans lader
os eksplicit vælge, hvad der logges (redactede tool-arguments, ikke interne
objekter).

## Konsekvenser

- Kræver en kørende MLflow tracking-server i produktion (`docker-compose`
  starter én). Uden den, eller med en forkert `MLFLOW_TRACKING_URI`, logges
  traces i stedet lokalt til `./mlruns` — harmløst i test, men skal
  konfigureres korrekt i en rigtig deployment.
- Under udvikling opdagede vi, at MLflow's default `mlflow_tracking_uri`
  (`http://localhost:5000`) får klientens indbyggede retry-logik til at
  blokere i op til flere minutter, hvis ingen server svarer — alle tests, der
  bygger FastAPI-appen, sætter derfor eksplicit en lokal fil-baseret
  tracking-URI. Se `docs/experiments/lessons-learned.md`.
- `Task.events_json` i PostgreSQL duplikerer en delmængde af, hvad MLflow
  også gemmer — bevidst, fordi de tjener forskellige formål: databasen
  betjener `/tasks/{id}/trace` uden afhængighed af, at MLflow er oppe; MLflow
  betjener tværgående analyse (sammenligning af mange kørsler, latency-trends).
