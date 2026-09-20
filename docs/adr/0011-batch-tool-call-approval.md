# ADR 0011: Godkendelse af flere tool calls som én atomisk batch

## Status

Accepteret.

## Kontekst

Anthropics og OpenAIs tool-use-protokoller tillader, at modellen returnerer
flere parallelle `tool_use`-blocks i én assistant-tur (fx "læs fil X" og
"kør tests" i samme svar). Protokollen kræver, at ALLE `tool_use`-blocks i
en tur får et tilhørende `tool_result`, i en samlet efterfølgende
user-besked, før samtalen kan fortsætte — der er ikke noget gyldigt
mellemtilstand, hvor nogle kald er besvaret og andre ikke.

Den oprindelige implementering af orchestratoren antog implicit præcis ét
tool call pr. tur (`tool_calls[0]`) og ignorerede resten. Det er ikke bare
en manglende feature — det er et korrekthedsproblem: hvis modellen
returnerer to kald, og kun det første eksekveres, mister vi det andet kalds
resultat permanent, og en efterfølgende samtaleture ville mangle et
`tool_result` for det ubesvarede `tool_use`, hvilket er en ugyldig
tilstand over for Anthropic/OpenAI's API.

Samtidig skal HØJ-risiko handlinger (`agentops.agent.risk`) fortsat kræve
eksplicit menneskelig godkendelse (ADR-0005), og ukendte tools skal
behandles fail-closed (som HØJ-risiko).

## Beslutning

Alle tool calls fra ÉN model-tur godkendes og eksekveres som én atomisk
batch:

- `PendingToolCall` repræsenterer ét enkelt afventende kald (id, tool_name,
  arguments, risk_level). `PendingApproval` bliver en liste af disse
  (`tool_calls: list[PendingToolCall]`) i stedet for ét fladt kald.
- I `AgentOrchestrator._run_loop`: hvis MINDST ét kald i turen kræver
  godkendelse (HØJ-risiko, eller ukendt tool jf. fail-closed-politikken),
  pauser HELE batchen — ingen af kaldene i turen eksekveres, heller ikke de
  LAV/MIDDEL-risiko kald i samme tur. Kun hvis INGEN kald i turen kræver
  godkendelse, eksekveres de alle sekventielt.
- I `AgentOrchestrator._resume()`: ved godkendelse eksekveres alle
  afventende kald i batchen; ved afvisning markeres alle som afvist. Begge
  grene producerer et `tool_result` for hvert `tool_use`-id, så samtalen
  altid er gyldig, når den sendes til providren igen.
- Persistering (`ApprovalRecord.tool_calls_json`) og API-svar
  (`PendingApprovalResponse.tool_calls`) afspejler samme liste-struktur.

Alternativet — at eksekvere LAV/MIDDEL-risiko kald i en blandet batch med
det samme og kun lade det HØJ-risiko kald afvente — blev fravalgt: det ville
kræve at sende et ufuldstændigt sæt `tool_result`s til modellen midt i en
afventende godkendelse, hvilket enten bryder protokollen eller kræver en
kunstig "delvis tur"-tilstand, der ikke har noget naturligt modstykke i
Anthropic/OpenAI's API.

## Konsekvenser

- Et menneske kan opleve at skulle godkende en batch, hvor kun ét af flere
  kald reelt er højrisiko — det er en bevidst konservativ afvejning
  (samme spirit som ADR-0005: friktion frem for stiltiende risiko).
  Godkendelses-UI'et (og `scripts/run_demo.py`) viser alle kald i batchen,
  så et menneske kan se præcis hvilke dele der er lav/høj risiko.
- `ApprovalRecord` fik en skema-migration
  (`102113bd290d_approval_batches.py`) fra tre flade kolonner
  (`tool_name`, `arguments_json`, `risk_level`) til én
  `tool_calls_json`-kolonne.
- `AgentOrchestrator._finalize()` var allerede nøglet på `tool_call_id` pr.
  event, så den krævede ingen ændringer for at understøtte flere kald pr.
  tur.
