# ADR 0007: Hvorfor `POST /tasks` kører agenten synkront

## Status

Accepteret, med kendt skaleringsgrænse.

## Kontekst

En agent-kørsel kan tage fra under et sekund (test-provideren) til flere
sekunder eller minutter (en rigtig LLM med mange tool calls). Standardmønsteret
i produktionssystemer for langvarige operationer er en baggrundsjobkø: API'et
returnerer med det samme, og klienten poller status.

## Beslutning

`POST /tasks` afventer agent-kørslen synkront og returnerer det fulde
resultat i samme response. Ingen jobkø, ingen worker-proces.

Dette er en bevidst forenkling for et projekt af denne skala: at indføre en
jobkø (fx Celery/RQ + Redis) ville tilføje en hel infrastrukturkomponent og
et nyt fejlscenarie (jobs, der forsvinder, retry-logik, dead-letter queues)
for at løse et problem, projektets faktiske brugsmønster (én demonstreret
opgave ad gangen) ikke har.

## Konsekvenser

- En langsom agent-kørsel (mange tool calls, en langsom LLM) holder
  HTTP-forbindelsen åben tilsvarende længe. Uden en timeout-strategi på
  klientsiden kan dette opleves som en hængende request.
- `agent_max_tool_calls`-grænsen (default 25) sætter et praktisk loft over,
  hvor længe en kørsel kan tage.
- Denne beslutning bør genovervejes, hvis platformen skal håndtere flere
  samtidige, langvarige opgaver — se `docs/architecture.md#skalering`.
