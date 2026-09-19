# ADR 0006: Hvorfor PostgreSQL — og hvorfor synkron SQLAlchemy

## Status

Accepteret.

## Kontekst

Platformen skal persistere operationel state (opgaver, godkendelser,
evalueringskørsler) adskilt fra MLflow's observability-data. Vi skal vælge
en database og en adgangsstil (sync vs. async SQLAlchemy).

## Beslutning

**PostgreSQL**, fordi det er den mest almindelige valgte relationsdatabase i
denne type platform, understøtter JSON-kolonner godt (bruges til
`conversation_state`, `events_json`, `tools_used` osv.), og har et modent
migrationsværktøj (Alembic).

**Synkron SQLAlchemy** (psycopg3-driver) i stedet for async SQLAlchemy +
asyncpg, selvom FastAPI selv er asynkront. Det er en bevidst forenkling: ved
denne skala (én bruger ad gangen pr. agent-kørsel, ingen høj samtidighed)
tilføjer async database-adgang kompleksitet (async sessions, async
context-managers i hele persistence-laget) uden en målbar fordel. De synkrone
DB-kald sker inden for FastAPI's request-handling og blokerer kun den ene
request, der udfører dem.

## Konsekvenser

- Ved høj samtidighed ville synkron DB-adgang blive en flaskehals — dette er
  en kendt, dokumenteret grænse for platformens nuværende skala, ikke en
  skjult antagelse.
- Skema styres af Alembic-migrations (`migrations/`), ikke kun
  `Base.metadata.create_all()` — verificeret til at køre rent (upgrade +
  downgrade) mod både SQLite (tests) og en rigtig PostgreSQL-instans.
- Verificeret ved faktisk at køre migrations og CRUD-operationer mod en
  ægte lokal PostgreSQL 16-instans, ikke kun mod SQLite i tests (se
  `tests/integration/test_persistence_postgres.py`).
