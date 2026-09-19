# CLAUDE.md

Denne fil hjælper Claude Code (og andre coding agents) med at arbejde korrekt
i dette repository. Læs den, før du foretager ændringer.

## Hvad dette er

AgentOps Developer Platform: en observerbar og evaluerbar AI-platform til
agent-assisteret softwareudvikling. Se `docs/architecture.md` for den fulde
arkitektur og `docs/portfolio.md` for projektresuméet.

## Centrale directories

- `src/agentops/security/` — sandboxing, command allowlisting, secret-redaction.
  Dette er trust-boundary'en. Ændringer her kræver ekstra omhu.
- `src/agentops/mcp_server/` — MCP-serveren og dens developer tools.
- `src/agentops/gateway/` — provider-uafhængig LLM Gateway (Anthropic/OpenAI/test).
- `src/agentops/agent/` — coding agent orchestrator, risk-klassificering, context-strategier.
- `src/agentops/persistence/` — SQLAlchemy-modeller og Alembic-migrations.
- `src/agentops/api/` — FastAPI-applikationen.
- `src/agentops/evaluation/` — evalueringsframework og benchmark-cases.
- `evals/fixtures/` — små target-repositories brugt af evalueringerne.
- `demo_repo/` — target-repository til den reproducerbare demo.
- `docs/adr/` — Architecture Decision Records.

## Kommandoer

```bash
uv venv && uv pip install -e . --group dev   # opsætning
ruff check src tests scripts migrations      # lint
ruff format src tests scripts migrations     # formatering
mypy src/agentops                            # typecheck
pytest tests -m "not integration" -q         # hurtige unit-tests
pytest tests -m integration -q               # integrationstests (spawner ægte subprocesser)
python scripts/run_evals.py --provider test  # deterministisk evaluerings-suite
```

## Coding conventions

- Python 3.12, type hints overalt, `from __future__ import annotations`.
- Ingen kommentarer, der blot gentager koden — kun kommentarer der forklarer et
  ikke-oplagt HVORFOR (en sikkerhedsbegrundelse, en API-kvirk, et trade-off).
- Foretræk at udvide en eksisterende, testet modul frem for at duplikere logik.
- Alle nye MCP-tools eller agent-handlinger SKAL klassificeres i
  `agentops.agent.risk.TOOL_RISK_LEVELS` — udeladelse behandles som HIGH risk
  (fail closed).

## Sikkerhedsregler — må ikke omgås

- Filsystemadgang for agenten går ALTID gennem `WorkspaceSandbox`. Tilføj aldrig
  en kodesti, der læser/skriver filer uden om den.
- Subprocess-kald går ALTID gennem `agentops.security.commands`
  (`run_git_readonly`/`run_pytest`) — aldrig `subprocess.run(..., shell=True)`
  eller nye generiske "kør denne kommando"-funktioner.
- HIGH-risk tool calls (`edit_file`, `apply_patch`) skal fortsat kræve
  menneskelig godkendelse, medmindre `AGENT_AUTO_APPROVE_HIGH_RISK=true` er
  eksplicit sat — svæk ikke denne kontrol for at få en demo til at virke.
- Secrets kommer kun fra environment variables. Commit aldrig en `.env`-fil
  eller en nøgle i kildekoden.

## Testkrav

- Kør `pytest tests -m "not integration" -q`, `ruff check`, og `mypy` før du
  betragter en ændring som færdig.
- Rør du sikkerhedslaget, MCP-tools, gateway'et eller orchestratoren, kør også
  `pytest tests -m integration -q` — disse tester den fulde kæde med en ægte
  spawnet MCP-server-subprocess.
- Tilføj en test, der ville have fanget enhver bug, du retter.

## Hvad du ikke må gøre

- Opfind ikke benchmark-, evaluerings- eller performance-tal. Kør dem og citer
  det faktiske resultat, eller sig eksplicit at det ikke er målt.
- Deaktivér ikke en fejlende test for at få CI grøn — find rodårsagen.
- Tilføj ikke nye tredjepartsafhængigheder uden en klar begrundelse.
