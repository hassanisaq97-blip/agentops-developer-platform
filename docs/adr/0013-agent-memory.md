# ADR 0013: Persistent agent-memory som udtrukne resuméer, ikke rå samtaler

## Status

Accepteret.

## Kontekst

En agent, der starter helt forfra på hver opgave, gentager de samme
fejltagelser og genopdager den samme repository-struktur igen og igen.
Platformen skal kunne lade en agent "lære" af tidligere opgaver i samme
repository — men naivt ville det betyde at gemme og genindsætte hele
tidligere samtaler i en ny system-prompt, hvilket:

- vokser ubegrænset (context-størrelse/tokens stiger med antal tidligere opgaver),
- inkluderer rå tool-result-tekst, der kan indeholde uverificeret
  fil-indhold (samme trussel som `evals/fixtures/prompt_injection_in_file_content/`),
- gør det svært at afgøre, hvad der reelt var en nyttig erfaring, og hvad
  der bare var støj i samtalen.

## Beslutning

`agentops.memory` gemmer et LILLE antal UDTRUKNE `MemoryRecord`-poster pr.
afsluttet opgave (`agentops.memory.extraction.extract_memories`) — bygget
UDELUKKENDE fra allerede-strukturerede felter på `AgentRunResult`
(`tools_used`, `files_changed`, `tests_passed/failed`, `warnings`,
`final_answer`), aldrig fra rå `conversation_state` eller rå
tool-result-tekst. Tre kategorier: `task_outcome`, `tool_effectiveness`,
`lesson_learned`.

**Sanitisering (poisoning-forsvar):** hver tekst, der bliver til en
memory-post, køres gennem `agentops.memory.sanitize.sanitize_memory_text`,
som afviser og erstatter tekst, der matcher kendte
prompt-injection-mønstre, med en fast placeholder og sætter `flagged=True`.
`MemoryStore.search` udelukker ALTID flagged rækker — fail closed, samme
politik som ukendte MCP-tools i `agentops.agent.risk`. Dette er
defense-in-depth: den primære kontrol er allerede, at kun strukturerede
felter bliver til memory, men hvis en RIGTIG LLM blev manipuleret af
injiceret fil-indhold og ekko'ede det i sit `final_answer`, ville det ellers
kunne "arves" som tillid værdig erfaring i en senere opgave.

**Søgning:** en simpel, forklarlig keyword-overlap-scoring i Python
(`agentops.memory.store.search`) — ingen embeddings/vector-database. Bevidst
valg: memory-mængden pr. workspace er lille, så en Python-side scoring er
hurtig nok og introducerer ingen ny afhængighed (jf. kravet om ikke at bruge
unødvendigt komplekse frameworks).

**Grænseflade til orchestratoren:** `AgentOrchestrator` kender IKKE til
SQLAlchemy. Den tager to valgfrie, plain async callables ved konstruktion
(`memory_retriever`, `memory_saver`) — samme separation som
`agentops.persistence.task_repository` allerede holder over for API-laget.
`agentops.memory.integration` forbinder disse til det session-parameteriserede
`agentops.memory.store` og logger hvert kald som et MLflow-span
(`memory_retrieval`/`memory_store`, `SpanType.MEMORY`).

**Off by default:** `Settings.agent_memory_enabled=False`. Ingen
eksisterende kald-steder (API, evals, eksisterende tests) ændrer opførsel,
medmindre dette eksplicit slås til.

## Konsekvenser

- Memory er scoped pr. workspace (`workspace_key_for`, en hash af
  workspace-roden) — blandes aldrig på tværs af repositories.
- En opgave, der aldrig når et terminalt resultat (COMPLETED/FAILED/
  MAX_STEPS_REACHED) — fx fordi den venter på godkendelse eller er PAUSED —
  gemmer ENDNU IKKE memory; det sker først, når opgaven reelt er færdig.
- Den deterministiske test-provider kan strukturelt ikke "bruge" memory
  semantisk (den reagerer kun på tool-resultater, ikke på fritekst i
  system-prompten) — memory's adfærdsmæssige effekt (færre tool calls,
  højere success rate) kan derfor kun måles meningsfuldt med en rigtig LLM.
  Det, der ER målt og testet her, er selve mekanikken: bliver relevant
  memory rent faktisk hentet, injiceret, og gemt korrekt? Se
  `docs/experiments/lessons-learned.md`.
