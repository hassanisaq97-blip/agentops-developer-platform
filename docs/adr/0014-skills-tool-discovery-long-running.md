# ADR 0014: Skills, dynamisk tool discovery, og checkpoint-baserede langvarige opgaver

## Status

Accepteret.

## Kontekst

Tre beslægtede udvidelser af agent-orchestratoren, der alle handler om at
give agenten PRÆCIS den kontekst og det tidsrum, den har brug for — hverken
mere eller mindre:

1. Alle MCP-tool-beskrivelser sendes altid til modellen, uanset opgavetype
   — unødvendig context/tokens/"tool-støj", og skalerer dårligt, hvis
   platformen får mange flere tools.
2. Ingen skills-lag: enhver opgavetype (debugging, security review, test
   generation, migration review, API review) får samme generiske
   instruktioner.
3. En agent-kørsel er ét synkront kald fra start til slut (jf. ADR-0007) —
   der er ingen måde at dele en stor opgave op i flere afgrænsede kørsler,
   og intet overlever en uventet nedlukning af API'et midt i en kørsel.

## Beslutning

### Skills (`agentops.agent.skills`)

En `Skill` er ren, statisk data (instruktioner, anbefalede MCP-tools,
sikkerhedsregler, tjek) — ikke kode. `select_skill(task_description)` er en
BILLIG, deterministisk keyword-matching, der kører FØR noget LLM-kald —
formålet er netop at undgå at bruge en dyr model-forespørgsel blot til at
vælge, hvilke instruktioner der er relevante. Kun den valgte skills
instruktioner tilføjes til system-prompten (`AgentEventType.SKILL_SELECTED`
logges til traces). At tilføje en ny skill kræver kun en ny `Skill(...)`-post.

### Dynamisk tool discovery (`agentops.agent.tool_discovery`)

Når `Settings.agent_dynamic_tool_discovery=True` (default `False`, ingen
ændring i eksisterende adfærd), filtreres den fulde MCP-tool-liste til en
delmængde — enten fra den valgte skills `recommended_tools`, eller via en
simpel keyword-fallback, hvis ingen skill matchede. Bevidst FAIL-OPEN på
tilgængelighed (intet matchede → vis alt): at vise ét ekstra read-only tool
er ikke en sikkerhedsrisiko, i modsætning til risk-godkendelse (ADR-0005,
ADR-0011), som forbliver uændret fail-closed. `AgentEventType.TOOLS_DISCOVERED`
logges, og `AgentRunResult.tools_available_count`/`tools_discovered_count`
gør forskellen målbar i evals.

### Checkpoint-baserede langvarige opgaver

Ny `TaskStatus.PAUSED` — adskilt fra `AWAITING_APPROVAL` (en
godkendelsesbeslutning) og fra `MAX_STEPS_REACHED` (opgavens SAMLEDE
trin-budget er brugt op). PAUSED betyder: "denne ene kørsel er stoppet
bevidst efter et afgrænset antal trin (`max_continuous_steps`), men opgaven
er langt fra færdig — genoptag med `AgentOrchestrator.continue_task()`."

To uafhængige mekanismer bærer dette:

1. **Checkpointing under kørslen.** `_run_loop` kalder en valgfri
   `on_checkpoint`-callback efter hver model-tur. API-laget
   (`agentops.api.routers.tasks._make_checkpoint_callback`) binder denne til
   den aktuelle DB-session/opgave og kalder
   `task_repository.checkpoint_progress`, som COMMITTER STRAKS — ikke kun
   ved requestets afslutning. Det er selve pointen: dør processen midt i en
   lang opgave, overlever det seneste checkpoint.
2. **Recovery ved opstart.** `task_repository.recover_interrupted_tasks`
   køres i FastAPI's `lifespan`, før noget andet. En opgave med status
   `"running"` betyder, at processen blev lukket ned midt i en kørsel —
   ingen ren afslutning skrev et terminalt resultat. Har den et checkpoint
   (ikke-tom `conversation_state`), markeres den `PAUSED` med en tydelig
   advarsel; har den intet, markeres den `FAILED`. Vi GENOPTAGER ALDRIG
   automatisk ved opstart — det ville betyde ukontrollerede LLM/tool-kald
   uden opsyn. Et menneske/en efterfølgende kalder vælger eksplicit at
   fortsætte via `POST /tasks/{id}/continue`.

`AgentOrchestrator.continue_task()` er en ny, selvstændig indgang — adskilt
fra `resume()` (som specifikt håndterer en godkendelses-JA/NEJ) — der
genoptager fra `conversation_state`/`events` uden nogen
godkendelsesbeslutning at anvende.

## Konsekvenser

- `Settings.agent_checkpoint_every_n_steps=0` (default) bevarer PRÆCIS
  eksisterende adfærd: ingen automatisk pause, samme synkrone
  ende-til-ende-kørsel som før.
- En opgave, der er delt op i mange `continue`-kald, betaler en ekstra
  DB-commit og en ny MCP-server-spawn pr. segment — en bevidst pris for
  holdbarhed, i tråd med platformens generelle "friktion frem for stille
  risiko"-holdning (jf. ADR-0005).
- Skills og tool discovery er uafhængige af hinanden og af memory — alle
  tre kan slås til/fra separat, og ingen af dem ændrer risk-klassificering
  eller godkendelseskrav.
