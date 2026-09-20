# AgentOps Developer Platform

En observerbar og evaluerbar AI-platform til agent-assisteret
softwareudvikling: en coding agent, der løser softwareopgaver ved at
undersøge og ændre et repository gennem en rigtig MCP-server — med
kontrolleret context, human-in-the-loop-godkendelse af risikable handlinger,
MLflow-tracing og et reproducerbart evalueringsframework.

## Hvorfor projektet eksisterer

Coding agents kan være effektive, men enterprise-brug kræver mere end en
model, der kan skrive kode: kontrolleret context (ikke hele repoet i
prompten), afgrænset tool-adgang, observability på tværs af agent-kørsler,
et evalueringsframework der måler faktisk succes frem for antagelser, og
sikker integration i en softwareudviklingsproces med menneskelig kontrol
over risikable handlinger. Dette projekt bygger den infrastruktur.

## Centrale funktioner

- **Coding agent orchestrator** med en agentisk løkke, strukturerede
  (ikke skjulte) beslutninger, og fire eksplicitte context-strategier.
- **Rigtig MCP-server** (officiel `mcp` Python SDK) med ni developer tools,
  sandboxed til ét repository, path traversal-beskyttet, med en command
  allowlist — ingen generisk shell-adgang.
- **Provider-uafhængig LLM Gateway**: Anthropic, OpenAI, og en deterministisk
  test-provider (kører uden API-nøgle), med routing og retries. Fallback ved
  et RIGTIGT providerudfald går kun til en anden konfigureret rigtig
  provider, aldrig til test-provideren — se [ADR-0012](docs/adr/0012-gateway-fallback-adskillelse.md).
- **Human-in-the-loop-godkendelse**: højrisiko tool-kald (fil-ændringer)
  pauser agenten og kræver eksplicit godkendelse via API'et.
- **Persistent agent-memory** (off by default): udtrukne, sanitiserede
  resuméer fra tidligere opgaver — aldrig rå samtaler — scoped pr. workspace,
  med indbygget forsvar mod at gemme prompt-injection-forsøg som tillid
  værdig erfaring. Se [ADR-0013](docs/adr/0013-agent-memory.md).
- **Skills** (debugging, security review, test generation,
  database/migration review, API review): en billig, deterministisk
  keyword-klassificering vælger den relevante skill FØR noget LLM-kald —
  agenten ser aldrig alle skill-instruktioner på én gang.
- **Dynamisk MCP tool discovery** (off by default): sender kun de tools til
  modellen, den valgte skill faktisk anbefaler, i stedet for altid alle ni —
  målt til at reducere både tool calls og tokens uden at ændre resultatet.
- **Checkpoint-baserede langvarige opgaver**: fremskridt gemmes og
  committes løbende under en kørsel, en opgave kan bevidst sættes på pause
  og genoptages senere, og en uventet API-nedlukning gendannes sikkert (aldrig
  ved at genoptage LLM-kald automatisk) — se [ADR-0014](docs/adr/0014-skills-tool-discovery-long-running.md).
- **Kontrolleret multi-agent workflow** (Developer → Test → Security →
  Reviewer): en fast, ikke-cyklisk pipeline bygget oven på den samme
  orchestrator — Security-fasen er en ægte deterministisk statisk scanning,
  ikke et LLM-kald der ikke kan verificeres. Se [ADR-0015](docs/adr/0015-multi-agent-workflow.md).
- **MLflow-tracing** af hele kæden: agent-kørsel → LLM-kald → tool-kald →
  memory → multi-agent-faser, som nestede spans i ét samlet trace.
- **Reproducerbart evalueringsframework** med deterministiske
  success-kriterier — ikke en models egen selvvurdering.
- **PostgreSQL + Alembic-migrations**, Docker/Docker Compose, GitHub Actions
  CI med et separat "AI Quality Gate", og statisk validerede
  Kubernetes/Terraform-konfigurationer.

## Arkitektur

```mermaid
flowchart TB
    Dev([Udvikler]) --> API[FastAPI]
    API --> Memory[Agent Memory]
    Memory --> Skills[Skill Selection]
    Skills --> Discovery[Dynamic Tool Discovery]
    Discovery --> Orch[Agent Orchestrator / Long-running Tasks]
    Orch --> MultiAgent[Multi-Agent Workflow: Dev → Test → Security → Reviewer]
    Orch --> Gateway[LLM Gateway]
    Gateway --> Anthropic[Anthropic]
    Gateway --> OpenAI[OpenAI]
    Gateway --> TestProvider[Deterministic Test Provider]
    Orch -- "stdio, spawnet subprocess" --> MCP[MCP Server]
    MCP --> Sandbox[WorkspaceSandbox] --> Repo[(Target-repository)]
    API --> DB[(PostgreSQL)]
    Orch -.trace.-> MLflow[(MLflow)]
    Orch --> Approval{{Human-in-the-loop godkendelse}}
    Orch --> Evals[Evaluation Framework]
```

Fuld arkitekturdokumentation: [`docs/architecture.md`](docs/architecture.md).

## Ende-til-ende-demoflow

```mermaid
sequenceDiagram
    participant U as Udvikler
    participant O as Agent Orchestrator
    participant G as LLM Gateway
    participant M as MCP Server
    participant R as Repository
    participant T as MLflow

    U->>O: Opgave ("Find og ret den fejlende test")
    O->>G: CompletionRequest (system prompt + tools)
    G->>M: search_code / read_file (LAV risiko)
    M->>R: Sandboxed opslag
    R-->>G: Fund + fil-indhold
    G->>M: run_tests (MIDDEL risiko)
    M-->>G: Fejlende test identificeret
    G-->>O: Foreslået patch (apply_patch — HØJ risiko)
    O->>U: Afventer menneskelig godkendelse
    U-->>O: Godkendt
    O->>M: apply_patch udføres
    O->>M: run_tests igen
    M-->>O: Alle tests består
    O->>T: Fuld trace (agent → LLM-kald → tool-kald)
    O-->>U: Resultat + trace-link
```

Kør selv: `python scripts/run_demo.py` (ingen API-nøgle nødvendig — se
"Quick start"). For at prøve det samme forløb direkte fra Claude Code (ikke
via API'et) — se [MCP direkte i Claude Code](#mcp-direkte-i-claude-code)
nedenfor.

## MCP direkte i Claude Code

Dette repository har et checket-ind [`.mcp.json`](.mcp.json): åbner du
repositoryet i Claude Code, forbinder det automatisk til
`agentops-developer-tools` MCP-serveren, klar til at bruges mod en
git-initialiseret kopi af `demo_repo/`:

```bash
uv venv && uv pip install -e . --group dev
python scripts/prepare_mcp_demo_workspace.py   # klargør/nulstil demo-workspacet
claude                                          # åbn Claude Code her
```

Her er det Claude Code's egen indbyggede tool-godkendelses-UI, der udgør
menneske-i-loopet for `apply_patch`/`edit_file` — et andet, men lige så reelt,
godkendelseslag end platformens interne `PendingApproval` (som kun er aktivt,
når AgentOps' egen orchestrator kører løkken via API'et). Path
traversal-beskyttelse og command allowlisting gælder uændret, uanset hvilken
klient der forbinder. Detaljer og en trin-for-trin-gennemgang:
[`docs/mcp.md`](docs/mcp.md).

## Evaluering

Kørt med den indbyggede deterministiske test-provider (ingen API-nøgle
nødvendig): **success rate 36 % (5/14 cases)**, med **100 % match** mod den
dokumenterede forventning for hver case — se
[`docs/experiments/lessons-learned.md`](docs/experiments/lessons-learned.md)
for det fulde resultat og hvorfor tallet er meningsfuldt (flere cases er
bevidst designet til at ligge uden for den deterministiske providers
rækkevidde — den genkender kun ét bug-mønster og reagerer aldrig på
fritekst, hverken i opgaven eller i fil-indhold). Suiten dækker bug fixing,
validering, refaktorering, repository-navigation, unødvendige
filændringer, korrekt skill-selection, og to adversarial cases
(unsafe-change-modstand og prompt injection via fil-indhold — se
[`SuccessCriterion.HIGH_RISK_ACTIONS_WERE_GATED`](src/agentops/evaluation/schemas.py)).
Metrics inkluderer nu også memory-hits, valgt skill, antal tools
tilgængelige/sendt til modellen, `approval_violations` (skal altid være 0)
og sikkerhedsfund fra en deterministisk diff-scanning.

Tre faktiske sammenligninger (uden vs. med memory, alle tools vs. dynamisk
discovery, single vs. multi-agent) er kørt og resultaterne gemt under
[`docs/experiments/`](docs/experiments/) — se lessons-learned for tallene og
hvad de rent faktisk viser (og ikke viser) med en scriptet provider.

**Real-LLM-evalueringer (Anthropic/OpenAI) er IKKE kørt** i dette miljø —
`.github/workflows/evals-llm.yml` er klargjort og kører automatisk mod
Anthropic, når det trigges med et `ANTHROPIC_API_KEY` repository secret.

## Tech stack

Python 3.12 · FastAPI · Pydantic · SQLAlchemy + Alembic · PostgreSQL ·
officiel `mcp` Python SDK · Anthropic- og OpenAI-SDK · MLflow Tracing ·
structlog · pytest · Docker/Docker Compose · GitHub Actions · Terraform
(azurerm) · Kubernetes-manifests (statisk valideret).

## Quick start

```bash
# Lokalt, uden Docker (kræver Python 3.12+ og PostgreSQL):
uv venv && uv pip install -e . --group dev
alembic upgrade head
uvicorn agentops.api.main:app --reload
# API-dokumentation: http://localhost:8000/docs

# Med Docker Compose (virker i almindelige miljøer med normal internetadgang;
# se "Kendte begrænsninger" nedenfor for hvorfor det IKKE kunne fuldføres i
# selve udviklingsmiljøet):
docker compose up --build

# Kør testsuiten:
pytest tests -m "not integration" -q   # hurtige unit-tests
pytest tests -m integration -q         # ægte subprocesser (MCP-server, Postgres)

# Kør den reproducerbare demo (ingen API-nøgle nødvendig):
python scripts/run_demo.py

# Kør evalueringsframeworket:
python scripts/run_evals.py --provider test
```

## Repository-struktur

```
src/agentops/
  security/      sandboxing, command allowlist, secret-redaction
  mcp_server/     MCP-serveren og dens developer tools
  gateway/        provider-uafhængig LLM Gateway
  agent/          orchestrator, multi-agent workflow, skills, tool discovery, risk
  memory/         persistent agent-memory (udtræk, sanitisering, lager)
  persistence/    SQLAlchemy-modeller (tasks, workflows, memory, evalueringer)
  api/            FastAPI-applikationen (tasks-, workflows-, evaluerings-routere)
  evaluation/     evalueringsframework
  observability/  MLflow-tracing, struktureret logging
evals/fixtures/    target-repositories til evalueringer
demo_repo/         target-repository til den reproducerbare demo
migrations/        Alembic-migrations
docs/              arkitektur, sikkerhed, ADR'er, eksperimenter, portfolio
infrastructure/    Kubernetes-manifests og Terraform (Azure)
```

## Security

MCP-serveren har ingen generisk shell-adgang, al filsti-validering går
gennem én sandbox-klasse, og højrisiko-handlinger kræver menneskelig
godkendelse som standard. Fuld trusselsmodel, mitigations og kendte
begrænsninger: [`docs/security.md`](docs/security.md).

## Eksperimenter og lessons learned

Faktisk målte forskelle mellem context-strategier, og en ærlig gennemgang af
hvad der ikke virkede første gang under udviklingen:
[`docs/experiments/lessons-learned.md`](docs/experiments/lessons-learned.md).

## Kendte begrænsninger

- **Ingen reelle LLM-metrics.** Alle tal i `evals/results/` er produceret af
  den deterministiske test-provider (ingen `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`
  konfigureret i udviklingsmiljøet). `.github/workflows/evals-llm.yml` kører
  samme suite mod Anthropic, når et repository secret er sat.
- **`docker compose up --build` blev ikke fuldført i udviklingsmiljøet.**
  `docker compose config` validerer korrekt, men selve image-pull'et blev
  afvist af netværkspolitikken i det sandboxede udviklingsmiljø (bekræftet:
  manifest-opslag lykkes, men blob-download fra Docker Hub's CDN får
  `403 Forbidden`). Dette er en miljøbegrænsning, ikke en fejl i
  Dockerfiles/compose-filen — GitHub Actions-runnere har fuld
  internetadgang (se CI-jobbet `docker-build`). Se
  [ADR-0008](docs/adr/0008-docker-uden-separat-mcp-service.md).
- **`PendingApproval`/HITL-godkendelse gælder kun AgentOps' egen
  orchestrator** (API'et, `scripts/run_demo.py`, evalueringerne). Når Claude
  Code selv er MCP-klienten (se ovenfor), er det Claude Code's egen
  tool-godkendelses-UI, der er menneske-i-loopet — de to mekanismer er
  bevidst adskilte, ikke sammenblandede.
- **Kubernetes/Terraform er statisk valideret, ikke deployet.** Manifester
  og Terraform-konfiguration er kørt gennem `kubeconform`/`terraform
  fmt`/`terraform validate`, men er aldrig anvendt mod en rigtig klynge
  eller Azure-subscription — se [`docs/adr/0009`](docs/adr/0009-azure-arkitektur.md)
  og [`docs/adr/0010`](docs/adr/0010-kubernetes-eller-ikke.md).
- **Memory- og multi-agent-kvalitet er kun mekanisk verificeret.** At
  memory rent faktisk forbedrer en RIGTIG models løsning, og at Security
  Agent-fasens deterministiske scanning matcher et rigtigt sikkerhedsreview,
  er ikke målt — kun at selve mekanikken (hent/gem/filtrér/eksekvér)
  fungerer korrekt. Se `docs/experiments/lessons-learned.md`, punkt 8-9.

## Licens

MIT — se [`LICENSE`](LICENSE).
