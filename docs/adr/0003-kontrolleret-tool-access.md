# ADR 0003: Hvorfor kontrolleret tool access frem for fri filsystemadgang

## Status

Accepteret.

## Kontekst

Den simpleste måde at lade en agent "arbejde i et repository" er at give den
et generelt shell- eller filsystem-tool og lade modellen selv formulere
kommandoer. Det er også den mest risikable: modellens output er ikke tillid
til (se `docs/security.md`), og et generelt shell-tool ville gøre platformen
lige så sikker som "kør, hvad end en LLM finder på".

## Beslutning

Hvert tool har et smalt, specifikt formål og et fast input/output-schema
(`search_code`, `read_file`, `run_tests`, osv.) — aldrig et generisk
"execute"-tool. Al filsti-validering går gennem én sandbox-klasse
(`WorkspaceSandbox`), og al kommandoeksekvering går gennem en allowlist
(`agentops.security.commands`). Tools klassificeres desuden i tre
risikoniveauer (LAV/MIDDEL/HØJ), og ukendte tools behandles som HØJ (fail
closed, ikke fail open) — se `agentops.agent.risk`.

## Konsekvenser

- Agenten kan ikke gøre noget, vi ikke eksplicit har givet den et tool til —
  heller ikke selvom en model "finder på" en kreativ måde at omgå det på,
  fordi der ikke findes en generel eksekveringsvej at ty til.
- Nye funktioner kræver et nyt, gennemtænkt tool i stedet for en generisk
  udvidelse — mere udviklingsarbejde, men en markant mindre angrebsflade.
- `apply_patch` implementerer sin egen unified-diff-parser i ren Python i
  stedet for at kalde systemets `patch`-binary, netop for at undgå at
  reintroducere en shell-kommando-vej (se `docs/mcp.md`).
