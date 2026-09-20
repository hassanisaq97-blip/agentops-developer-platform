# Portfolio-beskrivelse: AgentOps Developer Platform

## Projektnavn

**AgentOps Developer Platform**

## Kort beskrivelse

En observerbar og evaluerbar AI-platform til agent-assisteret
softwareudvikling. En coding agent modtager en softwareopgave, undersøger og
ændrer et repository gennem en rigtig MCP-server (kontrolleret context
acquisition, ikke "hele repoet i prompten"), med human-in-the-loop-godkendelse
af risikable handlinger, fuld MLflow-tracing, og et reproducerbart
evalueringsframework med deterministiske success-kriterier.

## Tech stack (faktisk implementeret)

Python 3.12, FastAPI, Pydantic, SQLAlchemy + Alembic, PostgreSQL, den
officielle MCP Python SDK, Anthropic- og OpenAI-SDK'erne, MLflow Tracing,
structlog, pytest, Docker/Docker Compose, GitHub Actions, Terraform
(azurerm), Kubernetes-manifests.

## Tre CV-punkter

- Designede og implementerede en AI-assisteret udviklerplatform med
  coding-agent orchestration, en rigtig MCP-server til kontrolleret
  repository-adgang (også direkte anvendelig fra Claude Code via et
  checket-ind `.mcp.json`), og en provider-uafhængig LLM Gateway med
  routing og retries, hvor fallback ved et rigtigt providerudfald kun går
  til en anden konfigureret rigtig provider — aldrig til den
  deterministiske test-provider (se ADR-0012).
- Implementerede MLflow-baseret distribueret tracing (agent → LLM-kald →
  tool-kald) og et reproducerbart evalueringsframework (11 cases,
  inklusive adversarial cases for unsafe changes og prompt injection) med
  deterministiske metrics (task success, tests bestået, antal tool calls,
  unødvendige filændringer) — verificeret til at give en målt success rate
  på 45 % med den indbyggede test-provider, ikke en opdigtet 100 %.
- Byggede et human-in-the-loop-godkendelsessystem med tre risikoniveauer,
  containeriserede platformen med Docker, og satte CI/CD op med et separat
  "AI Quality Gate" (deterministiske agent-evalueringer som en del af
  pipeline'en, adskilt fra dyre real-LLM-evalueringer).

## 30-sekunders forklaring (til jobsamtale)

"Jeg byggede en platform, hvor en coding agent løser softwareopgaver ved at
bruge en rigtig MCP-server til at undersøge et repository — søge i kode,
læse filer, køre tests — i stedet for at få hele repoet proppet ind i
prompten. Højrisiko-handlinger som at ændre filer kræver menneskelig
godkendelse. Alting spores i MLflow, og jeg byggede et evalueringsframework,
der måler, om agenten faktisk løste opgaven, med objektive kriterier — ikke
bare modellens egen vurdering af sig selv."

## 2-minutters teknisk forklaring

"Arkitekturen har fire hovedlag. En FastAPI-applikation modtager opgaver og
persisterer dem i PostgreSQL. En agent-orchestrator kører en agentisk løkke:
den beder en LLM Gateway om et modelsvar, og hvis modellen vil bruge et
tool, sender orchestratoren kaldet videre til en MCP-server, som jeg har
bygget på den officielle MCP Python SDK. MCP-serveren kører faktisk som en
separat proces, spawnet over stdio — præcis som Claude Code selv ville gøre
det — og er sandboxed til ét konfigureret repository med path traversal-
beskyttelse og en allowlist for kommandoer, den kan køre.

LLM Gateway'et er provider-uafhængigt: samme kode kan tale med Anthropic,
OpenAI, eller en deterministisk test-provider, jeg byggede specifikt til at
kunne teste og demonstrere hele systemet uden en API-nøgle. Risikable
tool-kald som at ændre en fil stopper løkken og venter på en eksplicit
godkendelse via API'et, før de udføres.

Alt logges som MLflow-spans — én agent-kørsel bliver ét trace med
underliggende spans for hvert LLM-kald og tool-kald. Og fordi jeg ville have
et ærligt billede af, om systemet rent faktisk virker, byggede jeg et
evalueringsframework med 11 benchmark-cases og deterministiske
success-kriterier — det målte faktisk en success rate på 45 % med
test-provideren, fordi den kun genkender ét bug-mønster, hvilket beviste, at
kriterierne målte noget reelt i stedet for altid at returnere succes."

## 10 sandsynlige interviewspørgsmål — og svar baseret på det faktiske projekt

**1. Hvorfor MCP i stedet for at kalde funktioner direkte?**
MCP er en åben standard, der lader samme server bruges af min egen
orchestrator OG af Claude Code eller andre MCP-klienter uden ændringer.
Det tvinger også en klar adskillelse: agent-logik ved ikke, hvordan
repository-adgang fungerer internt, kun at den kan bede om et tool og få et
resultat.

**2. Hvordan forhindrer du, at agenten ødelægger noget?**
Tre lag: (1) hvert tool har et smalt, fast schema — der findes intet
generelt "kør en kommando"-tool; (2) al filsti-validering går gennem én
sandbox-klasse, der afviser path traversal og symlink-escape; (3) tools, der
ændrer filer, er klassificeret høj-risiko og kræver eksplicit menneskelig
godkendelse, før de udføres.

**3. Hvordan styrer du context, så du ikke sender hele repoet til modellen?**
Jeg implementerede fire eksplicitte context-strategier — fra "kun
opgaveteksten" til "CLAUDE.md plus et forudberegnet repository-resumé" — og
målte faktisk forskellen i prompt-størrelse og antal tool calls mellem dem.
Standardtilstanden giver modellen ingen repository-indhold på forhånd; den
skal selv bede om det via MCP tools.

**4. Hvordan tester du et system, der er afhængigt af en LLM?**
Med en deterministisk test-provider — en lille state machine, der
simulerer en scriptet tool-brugende samtale uden netværkskald. Det lod mig
bygge og teste hele resten af systemet (orchestrator, godkendelsesflow,
evalueringsframework, API) uden nogen API-nøgle, og gav 105 automatiske
tests, jeg kunne køre reproducerbart.

**5. Hvordan ved du, at evalueringerne faktisk måler noget?**
Jeg designede bevidst benchmark-cases, hvor jeg forventede, at nogle ville
lykkes og andre fejle med test-provideren (fordi den kun kan løse ét
bug-mønster). Da jeg kørte suiten (11 cases, inklusive to adversarial cases
for unsafe changes og prompt injection), matchede det faktiske resultat
(45 % success rate, 100 % match mod den dokumenterede forventning for hver
case) præcis det forventede — hvis alle cases havde givet succes eller
fejl, ville det tyde på, at kriterierne ikke målte noget reelt.

**6. Hvad sker der, hvis LLM-provideren er nede?**
Gatewayen retryer med backoff. Hvis en ANDEN rigtig provider er konfigureret
(fx OpenAI, når Anthropic er primær), falder den over til den — et ægte
provider-til-provider failover, markeret eksplicit som `used_fallback=true`
i traces og API-svar. Uden en anden rigtig provider konfigureret er der
bevidst INTET fallback: opgaven markeres `FAILED` med en forklaring, i
stedet for stille at falde tilbage til den deterministiske test-provider og
risikere at fremstille et scriptet, ikke-repræsentativt svar som en løst
opgave. Det var faktisk den oprindelige default (test-provideren som
fallback for alle providers), som jeg rettede — se ADR-0012.

**7. Hvordan fungerer human-in-the-loop rent teknisk?**
Når orchestratoren støder på et højrisiko tool-kald, stopper den løkken,
serialiserer hele samtaletilstanden til JSON, og gemmer den i PostgreSQL med
status "afventer godkendelse". Et API-kald til
`/tasks/{id}/approve` genoptager kørslen fra præcis dét punkt — enten ved at
udføre handlingen eller ved at registrere en afvisning og lade modellen
fortsætte derfra.

**8. Hvorfor kører MCP-serveren ikke som en separat container?**
Fordi MCP over stdio er designet til en lokal, kortlivet proces pr.
klient-session — ikke en langtidsholdt netværkstjeneste. At tvinge den ind i
en separat container ville have introduceret en netværksgrænse uden nogen
reel fordel, siden den kun nogensinde har én klient (orchestratoren selv).

**9. Hvad ville du ændre, hvis dette skulle skalere til production-last?**
Async database-adgang eller en connection pool tunet til samtidighed,
en baggrundsjobkø til lange agent-kørsler i stedet for at holde HTTP-
forbindelsen åben, og autentificering/autorisation på API-endpoints — ingen
af de eksisterer i dag, og det er dokumenteret eksplicit som kendte
begrænsninger, ikke skjulte antagelser.

**10. Hvad var den sværeste bug, du stødte på?**
En forklarende kommentar i en test-fixture (`# BUG: skal være a + b`) fik
den deterministiske providers naive regex til at matche den forkerte linje i
en anden funktion og ødelægge den i stedet for at rette den tiltænkte bug.
Det fangede min egen evalueringstest, fordi jeg havde en eksplicit
forventning om, at den case skulle lykkes — uden den forventning ville jeg
ikke nødvendigvis have opdaget det.
