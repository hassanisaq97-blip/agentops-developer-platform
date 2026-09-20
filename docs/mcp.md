# MCP-serveren

Dette dokument beskriver MCP-implementeringen i detaljer: hvilken SDK der
bruges, hvilke tools der findes, deres input/output, sikkerhedsgrænserne, og
hvordan en MCP-klient (fx Claude Code) kan forbinde til serveren.

## SDK og version

Serveren er bygget på den officielle `mcp` Python SDK. Vi verificerede den
faktiske API mod den installerede version (2.2.0) i stedet for at antage en
ældre API fra træningsdata — se `src/agentops/mcp_server/server.py`'s
docstring. Bemærk: i `mcp` v2.x hedder serverklassen `MCPServer`
(`mcp.server.mcpserver.MCPServer`), som er efterfølgeren til v1's `FastMCP`.

## Arkitektur

MCP-serveren er en selvstændig proces, der starter med `python -m
agentops.mcp_server`. Den kommunikerer over **stdio-transport** — dét er
samme transportmekanisme, Claude Code selv bruger til lokale MCP-servere.
Agent-orchestratoren (`agentops.agent.mcp_client.MCPClient`) spawner denne
proces for hver agent-kørsel og lukker den ned igen bagefter. Der er derfor
ingen langtidsholdt netværksservice at angribe — kun en kortlivet subprocess,
scoped til præcis ét workspace.

```
AgentOrchestrator --spawner--> MCP Server-proces --opererer på--> WorkspaceSandbox --> target-repository
```

## Tools

| Tool | Risiko | Beskrivelse | Input | Output |
|---|---|---|---|---|
| `search_code` | LAV | Søger efter en tekststreng i kodebasen | `query: str`, `glob: str = "**/*"`, `max_results: int = 50` | Liste af `{path, line_number, line}` |
| `read_file` | LAV | Læser en fils indhold (evt. linjeinterval) | `path: str`, `start_line?: int`, `end_line?: int` | Filens tekstindhold |
| `list_repository` | LAV | Lister filer/mapper | `path: str = "."`, `max_depth: int = 3` | Liste af `{path, is_dir}` |
| `get_git_diff` | LAV | Viser uncommittede ændringer | `staged: bool = false` | Unified diff-tekst |
| `get_repository_status` | LAV | Branch/status + seneste commit | — | `{branch_and_changes, head_commit}` |
| `get_project_documentation` | LAV | Søger i README.md/CLAUDE.md/docs/**/*.md | `query?: str` | Liste af `{path, excerpt}` |
| `run_tests` | MIDDEL | Kører pytest og returnerer et struktureret resultat | `test_target?: str` | `{returncode, passed, failed, summary, stdout, stderr}` |
| `edit_file` | HØJ | Overskriver en fils fulde indhold | `path: str`, `content: str` | `{path, bytes_written, previous_size_bytes}` |
| `apply_patch` | HØJ | Anvender en unified diff på én fil | `diff_text: str` | `{applied: bool, path, bytes_written}` eller `{applied: false, error}` |

Risikoniveauerne matcher `agentops.agent.risk.TOOL_RISK_LEVELS` og afgør, om
et menneske skal godkende kaldet, før det udføres (se `docs/security.md`).
De to HIGH-risk tools kan slås helt fra på serverniveau ved at sætte
`MCP_DISABLE_FILE_EDITS=true` — så eksisterer værktøjerne slet ikke i
tool-listen, som en read-only MCP-server.

## Security boundaries

- **Path traversal:** alle stier valideres af `WorkspaceSandbox.resolve()`,
  som løser `..`-komponenter og symlinks og afviser alt, der lander uden for
  workspace-roden. `.git`, `.env`, `__pycache__`, `.venv` og `node_modules`
  er denylisted, selv inden for roden.
- **Command execution:** ingen generisk "kør en kommando"-tool findes.
  `get_git_diff`/`get_repository_status` kalder kun en allowlistet delmængde
  af read-only git-subcommands; `run_tests` kalder kun `sys.executable -m
  pytest`. Alt sker via en argv-liste med `shell=False` — aldrig
  strengsammensætning af en shell-kommando.
- **Secrets:** MCP-serveren har ingen adgang til API-nøgler — den kender
  intet til LLM Gateway'et. Subprocess-miljøet, `run_tests`/git-kaldene
  bruger, er reduceret til kun `PATH`.
- **apply_patch uden shell:** i stedet for at kalde systemets `patch`-binary
  (som ville genindføre command-injection-risikoen), parser og anvender vi
  unified diffs i ren Python (`agentops.mcp_server.patching`). Begrænsning:
  understøtter kun én fil pr. patch, ingen fuzzy matching.

## Tool-registrering

Tools registreres deklarativt med `@server.tool(...)` i
`agentops.mcp_server.server.build_server()`, hver med en `ToolAnnotations`
(`read_only_hint`/`destructive_hint`) der matcher den faktiske adfærd — dette
er MCP-protokollens egen mekanisme til at signalere risiko til en klient, ud
over vores egen `agentops.agent.risk`-politik.

## Sådan forbinder Claude Code til serveren

Dette repository har et checket-ind `.mcp.json` i roden:

```json
{
  "mcpServers": {
    "agentops-developer-tools": {
      "command": "${CLAUDE_PROJECT_DIR}/.venv/bin/python",
      "args": ["-m", "agentops.mcp_server"],
      "env": {
        "AGENT_WORKSPACE_ROOT": "${CLAUDE_PROJECT_DIR}/.mcp_demo_workspace",
        "MCP_DISABLE_FILE_EDITS": "false"
      }
    }
  }
}
```

Det betyder, at hvis du åbner DETTE repository i Claude Code (efter `uv venv
&& uv pip install -e . --group dev`, jf. README), er MCP-serveren allerede
konfigureret — Claude Code spawner den automatisk med den rigtige interpreter
(`.venv/bin/python`, ikke en tilfældig `python` fra PATH) og peger den på
`.mcp_demo_workspace/`, en git-initialiseret arbejdskopi af `demo_repo/` (se
`scripts/prepare_mcp_demo_workspace.py` for hvorfor `demo_repo/` selv IKKE
har sit eget `.git` — et indlejret repo i et repo giver "gitlink"-forvirring).

For at bruge MCP-serveren mod et ANDET repository (ikke demoen), tilføj din
egen server via `claude mcp add`, eller redigér `.mcp.json` lokalt (ucommitted)
med en anden `AGENT_WORKSPACE_ROOT` — sæt den aldrig til et repository, du
ikke har tillid til at give læse/skrive-adgang.

### Reproducerbar demo: Claude Code retter en bug via MCP

```bash
uv venv && uv pip install -e . --group dev   # hvis ikke allerede gjort
python scripts/prepare_mcp_demo_workspace.py  # klargør/nulstil .mcp_demo_workspace/
claude                                        # åbn Claude Code i repo-roden
```

Bed derefter Claude Code (i selve CLI'en, ikke i denne kodebase) om noget i
stil med: *"Brug agentops-developer-tools MCP-serveren til at finde og rette
den fejlende test i .mcp_demo_workspace."* Det forventede forløb:

1. Claude Code kalder `search_code`/`read_file` (LAV risiko) for at finde
   `add()`-funktionen i `src/calculator.py`.
2. Claude Code kalder `run_tests` (MIDDEL risiko) og ser den fejlende test.
3. Claude Code foreslår en rettelse via `apply_patch` — et `DESTRUCTIVE`
   MCP-tool. **Claude Code's egen indbyggede tilladelsesprompt** ("Allow
   apply_patch?") stopper her og venter på dit eksplicitte OK, før kaldet
   udføres.
4. Efter din godkendelse anvendes patchen, og Claude Code kalder `run_tests`
   igen for at bekræfte, at testsuiten består.

**Vigtig præcisering:** dette er IKKE det samme godkendelses-lag som
`agentops.agent.risk`/`PendingApproval` (ADR 0005, ADR 0011), som kun er
aktivt, når AgentOps' EGEN orchestrator kører løkken (via `POST /tasks` eller
`scripts/run_demo.py`). Når Claude Code selv er MCP-klienten, er det Claude
Code's generiske, indbyggede tool-tilladelses-UI, der udgør
menneske-i-loopet — ikke platformens interne risk-klassificering. Begge lag
er reelle sikkerhedsgrænser, men det er to forskellige mekanismer, og denne
demo tester den førstnævnte. Uanset hvilken klient der kalder MCP-serveren,
håndhæves path traversal-beskyttelsen og command-allowlistningen altid af
`WorkspaceSandbox`/`agentops.security.commands` — det er IKKE
klient-afhængigt.

## Sådan testes serveren isoleret

```bash
# Start serveren manuelt og send den JSON-RPC over stdin (til fejlfinding):
AGENT_WORKSPACE_ROOT=./demo_repo python -m agentops.mcp_server

# Eller kør integrationstesten, der taler den faktiske MCP-protokol til den:
pytest tests/integration/test_mcp_server_protocol.py -m integration -v
```
