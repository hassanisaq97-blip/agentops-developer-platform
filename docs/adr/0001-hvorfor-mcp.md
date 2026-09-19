# ADR 0001: Hvorfor Model Context Protocol (MCP)

## Status

Accepteret.

## Kontekst

Coding agenten skal kunne undersøge og ændre et repository, uden at hele
repositoryet sendes til LLM'en, og uden at agentens kode er tæt koblet til én
bestemt måde at eksponere tools på. Vi overvejede tre tilgange:

1. Kald tool-funktioner direkte fra orchestratoren (almindelige Python-funktionskald).
2. Byg et hjemmerullet HTTP-API til developer tools.
3. Implementér en MCP-server.

## Beslutning

Vi bruger MCP (den officielle `mcp` Python SDK), fordi:

- Det er en åben, providerneutral standard — samme MCP-server kan bruges af
  vores egen orchestrator OG af Claude Code eller andre MCP-klienter uden
  ændringer. Det demonstrerer noget generaliserbart, ikke en engangsløsning.
- Protokollen har indbyggede primitiver for tool-annotationer
  (`read_only_hint`, `destructive_hint`), som matcher vores behov for at
  signalere risikoniveau.
- Ved at gøre orchestratoren til en ægte MCP-*klient* (ikke bare et modul, der
  tilfældigvis kalder nogle funktioner), tvinges en klar adskillelse mellem
  "agent-logik" og "repository-adgang" — sidstnævnte kan køre i en separat
  proces med sin egen sandboxing.

## Konsekvenser

- MCP-serveren kører som en subprocess (stdio-transport), spawnet pr.
  agent-kørsel — se ADR 0008 for hvorfor den ikke er en separat container.
- Vi er afhængige af en tredjeparts-SDK's stabilitet; vi har verificeret den
  faktiske installerede API (v2.x, `MCPServer`) i stedet for at antage en
  ældre version fra træningsdata (v1's `FastMCP`).
- Alternativet (direkte funktionskald) ville have været simplere at
  implementere, men ville ikke have bevist, at platformen faktisk forstår og
  anvender MCP — kun at den har en tool-abstraktion internt.
