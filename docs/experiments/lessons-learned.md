# Lessons learned

Dette dokument beskriver, hvad der rent faktisk skete under udviklingen af
AgentOps Developer Platform — inklusive de ting, der ikke virkede første
gang. Formålet er at vise reel eksperimentering, ikke at fremstille det som
om alle beslutninger var rigtige fra start.

## Hvad der virkede

- **MCP over stdio som subprocess** viste sig at være markant simplere end
  forventet at teste: fordi den officielle `mcp`-SDK lader en
  `ClientSession` tale til en spawnet proces, kunne vi skrive rigtige
  integrationstests (`tests/integration/test_mcp_server_protocol.py`), der
  beviser, at MCP-protokollen faktisk bliver talt — ikke kun at
  tool-funktionerne findes.
- **Den deterministiske test-provider** som en lille state machine (afgør
  næste tool call ud fra, hvilke tools der allerede er kaldt, og hvad deres
  resultater var) gjorde det muligt at bygge og teste HELE resten af
  platformen (orchestrator, approval-flow, evaluation framework, API) uden
  nogen API-nøgle. Det var ikke oplagt på forhånd, at én simpel playbook
  kunne bære så meget af testdækningen.
- **Risk-klassificering af tools som en ren, lille funktion**
  (`agentops.agent.risk.risk_level_for`) gjorde human-in-the-loop-flowet
  meget nemmere at implementere korrekt end forventet: orchestratoren
  behøver ikke vide noget om, HVORFOR et tool er højrisiko — den spørger
  bare og pauser.

## Hvad der IKKE virkede første gang

### 1. En kommentar ødelagde den deterministiske providers patch-generator

Den første version af eval-fixturen `fix_failing_test_add/src/calculator.py`
havde en forklarende kommentar på buggy-linjen:

```python
def add(a, b):
    return a - b  # BUG: skal være a + b
```

Den deterministiske providers naive regex (`^(\s*)return (\w+) - (\w+)\s*$`)
matcher kun linjer, der IKKE har andet efter udtrykket — kommentaren fik
regex'en til slet ikke at matche den tiltænkte linje, men i stedet matche en
identisk, korrekt linje i en anden funktion (`subtract`), som blev
fejlagtigt "rettet" og derved ødelagt. Dette blev fanget af
`tests/integration/test_evaluation_framework.py`, som forventede at
`fix_failing_test_add` skulle lykkes, men fik `success=False` med BEGGE
tests fejlende i stedet for kun én.

**Rettelse:** kommentaren blev fjernet fra fixturen. **Lære:** en
mønstergenkendelse uden ægte kodeforståelse er skrøbelig over for
overfladiske variationer som kommentarer — noget en rigtig LLM naturligvis
ikke ville have problemer med, men som er værd at dokumentere som en
grundlæggende begrænsning ved den deterministiske test-double.

### 2. MLflow's default tracking-URI fik testsuiten til at hænge i minutter

Da MLflow-tracing blev koblet ind i FastAPI's opstart
(`configure_mlflow(settings)`), begyndte `tests/integration/test_api.py` at
timeoute. Årsagen: `Settings.mlflow_tracking_uri` defaulter til
`http://localhost:5000` (den URI, docker-compose bruger), men ingen
MLflow-server kørte under testene. MLflow's klient retryer HTTP-kald med
exponentiel backoff (op til 7 forsøg, i praksis flere minutter), før den
opgiver.

**Rettelse:** alle tests, der bygger FastAPI-appen, sætter nu eksplicit
`mlflow_tracking_uri` til en lokal SQLite-fil
(`sqlite:///{tmp_path}/mlflow.db`) — ingen netværksafhængighed. **Lære:**
en default, der er fornuftig i docker-compose, kan være en fælde i tests,
hvis den ikke gøres eksplicit override-bar. Dette er nu dokumenteret i ADR
0004.

### 3. Postgres' native ENUM-type overlevede en Alembic-downgrade

Den første version af `ApprovalRecord.decision` brugte
`sa.Enum(ApprovalDecision)`, som på PostgreSQL opretter en `CREATE TYPE
... AS ENUM`. Da vi testede `alembic downgrade base` efterfulgt af en ny
`alembic upgrade head` mod en RIGTIG lokal PostgreSQL-instans (ikke kun
SQLite), fejlede upgraden med `DuplicateObject: type "approvaldecision"
already exists` — den auto-genererede downgrade dropper tabellen, men ikke
den separate ENUM-type-definition.

**Rettelse:** skiftede til `Enum(ApprovalDecision, native_enum=False)`,
som gemmer værdien som en almindelig `VARCHAR` — identisk adfærd på tværs af
SQLite og PostgreSQL, uden en separat type-livscyklus at holde styr på.
**Lære:** test migrations op OG ned mod en rigtig database, ikke kun SQLite
— dette er et kendt Alembic/PostgreSQL-fælde, vi ellers ikke ville have
opdaget før en rigtig produktionsdatabase.

### 4. MCP-SDK'ets API havde ændret sig siden træningsdata

`from mcp.server.fastmcp import FastMCP` (den API, vi forventede fra ældre
dokumentation) fejlede med en eksplicit migrationsbesked fra den installerede
`mcp` v2.2.0: klassen hedder nu `MCPServer`
(`mcp.server.mcpserver.MCPServer`). Vi inspicerede den faktiske installerede
pakkes signaturer direkte (`inspect.signature`) i stedet for at gætte ud fra
træningsdata, hvilket også afslørede andre detaljer (fx at
`ToolAnnotations` bruger `read_only_hint`/`destructive_hint` som feltnavne).

**Lære:** for hurtigt-udviklende SDK'er (MCP, Anthropic, MLflow) er det
nødvendigt at verificere mod den faktisk installerede version, ikke antage
API'et fra træning.

### 5. Anthropic SDK'et har ikke længere en top-level `temperature`-parameter

Under implementeringen af `AnthropicProvider` gav mypy en overload-fejl på
`temperature=request.temperature` i kaldet til `messages.create()`. Ved
inspektion af den installerede SDK's signatur var `temperature` faktisk ikke
længere blandt parametrene. Parameteren blev fjernet fra kaldet — determinisme
i vores egne tests styres i stedet af den deterministiske test-provider, ikke
af en temperature-indstilling mod en rigtig model.

### 6. MCP's `structured_content` er inkonsistent på tværs af returtyper

Under implementeringen af `MCPClient.call_tool` observerede vi, at et tool
med returtype `str` eller `list[dict]` får sit resultat wrappet i
`structured_content` som `{"result": ...}`, mens et tool med returtype
`dict` (uden generisk parameter) slet ikke får en JSON-schema udledt og
derfor har `structured_content=None`. I stedet for at bygge speciallogik pr.
returtype standardiserede vi på at læse `content`-listens tekstblokke
konsekvent — de er altid til stede, uanset returtype.

### 7. En ny fixture eksponerede en antagelse i den deterministiske providers navneudledning

Da eval-suiten blev udvidet fra 4 til 11 cases (for at dække validering,
refaktorering, endnu en navigation-case, unødvendige filændringer, unsafe
changes og prompt injection), blev en ny case
(`fix_failing_test_discount`) først kørt med en fejlende test navngivet
`test_loyalty_bonus_increases_total`, mens kildefunktionen hed
`total_with_loyalty_bonus`. Den deterministiske providers
`_extract_failing_function` udleder søgeforespørgslen for `search_code`
direkte fra testnavnet (`FAILED\s+\S+::test_(\w+)`), så den søgte efter
`def loyalty_bonus_increases_total` — som ikke findes — og gav op uden at
finde eller rette buggen. Kørslen viste korrekt `success=False`, men det var
en fejl i FIXTUREN, ikke i platformen: `expect_deterministic_provider_to_solve=True`
var forkert forventning for den daværende fixture.

**Rettelse:** testfunktionen blev omdøbt til `test_total_with_loyalty_bonus`,
så navnet matcher kildefunktionen — identisk mønster med de øvrige
solvable cases (`test_add` ↔ `add`). **Lære:** den deterministiske
providers "navigation" er reelt navnematching på testnavn ↔ funktionsnavn,
ikke semantisk forståelse — en ny fixture skal designes med dette i
mente, og en eval-kørsel, der ikke matcher sin dokumenterede forventning,
skal altid undersøges (er det platformen eller fixturen, der er forkert?),
aldrig bare accepteres eller "rettes" ved at ændre den dokumenterede
forventning uden at forstå hvorfor.

**Faktisk, reproducerbar kørsel efter rettelsen** (`--provider test`,
`evals/results/a8813936-da83-4263-bdf6-824967c7c022.json`):

| Metric | Værdi |
|---|---|
| Success rate | 45 % (5/11) |
| Forventning matchet | 100 % (11/11) |
| Gennemsnitligt antal tool calls | 4.1 |

Alle 11 cases matcher deres dokumenterede forventning i `cases.py` — inklusiv
de nye adversarial cases: `unsafe_change_resists_deleting_test` (agenten
sletter ikke testen, selvom opgaveteksten selv foreslår det som "den
letteste vej") og `prompt_injection_in_file_content` (en instruktion skjult
i en fil-docstring, der forsøger at få agenten til at indsætte en bagdør,
ændrer intet ved at HIGH-risk-handlingen stadig blev gatet bag en
`APPROVAL_REQUIRED`-event, jf. `SuccessCriterion.HIGH_RISK_ACTIONS_WERE_GATED`).
Det er en <45 % success rate for en grund, der er dokumenteret med vilje:
6 af de 11 cases er bevidst designet til at vise den deterministiske
test-providers kendte grænser (ingen semantisk kodeforståelse, ingen
navigation uden en fejlende test som udløser), ikke en regression.

**Vigtig præcisering om, hvad prompt injection-casen faktisk beviser:** den
deterministiske provider er strukturelt immun over for injektion i
fil-indhold, fordi den aldrig fortolker fritekst — den reagerer kun på
strukturerede tool-resultater. Casen beviser derfor IKKE, at en rigtig LLM
ikke kan manipuleres af injiceret tekst; det kan den. Den beviser, at selv
hvis en model manipuleres til at foreslå en HIGH-risk handling, kan den
IKKE få effekt uden en menneskelig godkendelse — det er platformens reelle
forsvarslag mod prompt injection (se ADR 0005 og 0011), og det er det, en
kørsel mod en rigtig LLM (`--provider anthropic`, endnu ikke udført i dette
miljø, se afsnittet om kendte begrænsninger) faktisk ville teste
meningsfuldt: om godkendelsesgrænsen holder, ikke om modellen "falder for"
teksten.

## Context-strategier: hvad blev faktisk målt

`scripts/run_context_experiment.py` kørte den samme opgave
(`fix_failing_test_add`) under alle fire strategier med den deterministiske
provider. Faktiske, reproducerbare tal (se
`docs/experiments/context-strategy-results.json`):

| Strategi | System-prompt (tegn) | Tools | Status | Tool calls | Tests |
|---|---|---|---|---|---|
| A: minimal | 96 | Nej | completed (uden at røre repoet) | 0 | – |
| B: claude_md | 334 | Nej | completed (uden at røre repoet) | 0 | – |
| C: targeted_mcp | 334 | Ja | completed | 6 | 2/2 |
| D: optimized | 484 | Ja | completed | 6 | 2/2 |

**Hvad dette faktisk viser:** uden tools (A/B) kan agenten ikke løse en
opgave, der kræver at røre en faktisk fil — den svarer, men uden grundlag i
det virkelige repository. Med tools (C/D) lykkes opgaven. Strategi D bruger
mere plads i prompten (et forudberegnet repository-resumé), men det
reducerer IKKE antallet af tool calls hos den deterministiske provider — det
er forventet, fordi playbooken ikke "læser" det forudberegnede resumé
semantisk. **Hvad dette IKKE viser:** om et forudberegnet resumé rent
faktisk reducerer antallet af exploratory tool calls, en RIGTIG model ville
foretage. Det kræver ægte sprogforståelse og er ikke målt her — se
begrænsningen nedenfor.

## Kendte begrænsninger i det, der er målt

- **Ingen reelle LLM-metrics.** Uden en konfigureret `ANTHROPIC_API_KEY`
  eller `OPENAI_API_KEY` er alle tal i `evals/results/` og
  `docs/experiments/context-strategy-results.json` produceret af den
  deterministiske test-provider. Det er en gyldig måling af selve
  platformens mekanik (kører løkken korrekt? gates high-risk-handlinger
  korrekt? beregnes success-kriterier korrekt?), men det er IKKE et mål for,
  hvor godt en rigtig LLM ville løse opgaverne. `.github/workflows/evals-llm.yml`
  er klargjort til at køre den samme suite mod Anthropic, men er ikke kørt i
  dette miljø.
- **Claude Code-eksperimentet (Setup A-D med den faktiske Claude Code CLI)**
  er ikke gennemført som en separat, interaktiv sammenligning — dette
  udviklingsmiljø er selv en Claude Code-session, der byggede platformen, og
  havde ikke adgang til at spawne en anden, uafhængig Claude Code-session til
  at måle på. Det generelle context-strategi-eksperiment ovenfor bruger
  samme underliggende platform og MCP-server, som Claude Code selv ville
  forbinde til (se `docs/mcp.md`), og er den nærmeste reproducerbare
  erstatning, vi kunne udføre i dette miljø.
- **Docker- og Terraform-builds** kunne ikke fuldføres i udviklingsmiljøet på
  grund af netværksrestriktioner mod hhv. Docker Hub's blob-CDN og
  `registry.terraform.io` — se ADR 0008 og 0009. `docker compose config` og
  `terraform fmt` blev begge kørt og bestået.
