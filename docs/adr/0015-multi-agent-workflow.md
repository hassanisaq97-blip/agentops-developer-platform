# ADR 0015: Et fast, ikke-cyklisk multi-agent workflow

## Status

Accepteret.

## Kontekst

En almindelig faldgrube ved "multi-agent"-systemer er et frit chat-loop
mellem agenter uden nogen naturlig afslutning — hver agent kan i princippet
blive ved med at svare den næste, uden en øvre grænse eller et klart
ansvarsskel. Det er svært at holde deterministisk, svært at sætte et
trin-budget på, og svært at holde inden for platformens eksisterende
human-in-the-loop-model.

Kravet var fire roller med klart ansvar: Developer (løser opgaven), Test
(tester ændringen), Security (undersøger sikkerhedsproblemer), Reviewer
(laver et afsluttende review) — uden ubegrænset "snak" mellem dem.

## Beslutning

`agentops.agent.multi_agent.MultiAgentOrchestrator` kører en FAST rækkefølge
uden tilbageløb: Developer → Test → Security → Reviewer, altid i den
rækkefølge, aldrig cyklisk. Hver fase er bygget oven på den EKSISTERENDE
`AgentOrchestrator` — ingen ny agent-loop-implementering:

- **Developer-fasen** er en almindelig `AgentOrchestrator.run()`-kørsel med
  samme trin-budget som en enkelt-agent-opgave
  (`multi_agent_developer_max_steps`, default = `agent_max_tool_calls`).
  Rammer den et HIGH-risk tool call, pauser HELE workflowet
  (`TaskStatus.AWAITING_APPROVAL`) præcis som en normal opgave — samme
  `PendingApproval`-mekanisme, samme godkendelseskrav (ADR-0005, ADR-0011).
  `resume_after_approval()` genoptager specifikt Developer-fasen.
- **Test-fasen** er endnu en `AgentOrchestrator.run()`-kørsel, men med et
  langt mindre budget (`multi_agent_test_max_steps=6`) — den skal kun
  orientere sig og køre testsuiten, ikke løse opgaven forfra.
- **Security-fasen er BEVIDST IKKE et LLM-kald.** Den deterministiske
  test-provider har ingen reel evne til semantisk sikkerhedsvurdering (den
  reagerer kun på strukturerede tool-resultater), så en "AI-drevet"
  sikkerhedsreview ville enten være meningsløs med test-provideren eller
  umulig at måle ærligt. I stedet kører
  `agentops.agent.security_scan.scan_diff_for_issues` en deterministisk,
  mønster-baseret statisk scanning af `git diff` (farlige kald som
  `eval()`/`os.system()`/`shell=True`, hardkodede secrets via den
  eksisterende `agentops.security.secrets.redact_text`, path
  traversal-mønstre). Det gør Security-fasen ægte og provider-uafhængig —
  samme kontrol kører, uanset om Developer-fasen blev drevet af en rigtig
  model eller test-provideren.
- **Reviewer-fasen** er en deterministisk, Python-komponeret syntese af de
  tre foregående fasers `success`-felter (`approved` kun hvis Developer
  fuldførte, testsuiten består, og Security ikke fandt noget) — ikke endnu
  et LLM-kald, af samme grund som Security-fasen.

**Afslutningsregel:** pipelinen stopper ALTID efter Reviewer (eller
tidligere, hvis Developer-fasen fejler/afventer godkendelse) — der er
strukturelt ingen vej tilbage til en tidligere fase. `agent_handoffs` tælles
og eksponeres (0 ved en godkendelsespause, ellers 4 ved en fuldført kørsel).

**Fælles task state / observability:** hele workflowet logges som ét
MLflow-span (`multi_agent_workflow`), med hver fase som et indlejret span
(`multi_agent_phase:<rolle>`) — synligt som ét samlet trace, men med hver
agents arbejde adskilt indeni. Persisteres i en NY `workflows`-tabel
(`agentops.persistence.workflow_repository`), adskilt fra `tasks` — en
workflow-kørsel har en anden facon (flere faser, ét samlet verdict) end en
enkelt-agent-opgave.

## Konsekvenser

- Security- og Reviewer-fasernes "intelligens" er bevidst deterministisk,
  ikke LLM-drevet — det er en styrke for testbarhed og en ærlig grænse: en
  rigtig LLM ville kunne give en langt mere nuanceret sikkerhedsvurdering,
  men denne platform lover kun det, den faktisk kan verificere.
- Et nyt endepunkt-par (`POST /workflows`, `POST /workflows/{id}/approve`)
  mirrorer `tasks.py`'s struktur bevidst, for at holde de to ressourcer
  letgenkendelige for en fremtidig bidragyder.
- Multi-agent-workflowet ændrer INTET ved den eksisterende
  enkelt-agent-orchestrator eller dens API — det er et rent additivt lag
  oven på den.
