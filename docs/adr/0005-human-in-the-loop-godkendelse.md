# ADR 0005: Hvorfor human-in-the-loop-godkendelse

## Status

Accepteret.

## Kontekst

En coding agent, der kan ændre filer, er per definition i stand til at
forårsage skade — ved en fejl i egen logik, ved en fejlvurdering, eller ved
at blive manipuleret via prompt injection (se `docs/security.md`). I
enterprise-sammenhæng er "modellen plejer at have ret" ikke tilstrækkeligt
for irreversible handlinger.

## Beslutning

Alle tool calls klassificeres i LAV/MIDDEL/HØJ risiko
(`agentops.agent.risk`). HØJ-risiko handlinger (`edit_file`, `apply_patch`)
stopper den agentiske løkke og returnerer status `awaiting_approval` i
stedet for at udføre handlingen. Et menneske skal eksplicit godkende eller
afvise via `POST /tasks/{id}/approve`, før orchestratoren genoptager
kørslen (`AgentOrchestrator.resume()`). Beslutningen (og hvornår den blev
taget) persisteres i `ApprovalRecord`.

`AGENT_AUTO_APPROVE_HIGH_RISK=true` findes som en eksplicit undtagelse, kun
tiltænkt automatiserede evalueringskørsler, der skal kunne gennemføres uden
et menneske i loopet — aldrig som en produktionsindstilling.

## Konsekvenser

- En agent-kørsel kan ikke fuldføre en filændring "i baggrunden" uden
  synlighed — den stopper og venter.
- Kræver, at samtaletilstanden (`conversation_state`) er fuldt serialiserbar
  til JSON, så den kan genoptages efter en (potentielt lang) pause — det
  formede designet af `Message`/`AgentEvent` som Pydantic-modeller fra start.
- Tilføjer et ekstra API-kald til den lykkelige vej for enhver opgave, der
  rører filer. Det er en bevidst friktion, ikke en fejl.
