# ADR 0002: Hvorfor en provider-uafhængig LLM Gateway

## Status

Accepteret.

## Kontekst

Platformen skal kunne bruge forskellige LLM-providers (Anthropic, OpenAI) og
skal kunne testes og køre CI uden en API-nøgle. Hvis agent-orchestratoren
kaldte en providers SDK direkte, ville:

- al agent-logik blive koblet til én providers meddelelsesformat (Anthropics
  content-blocks vs. OpenAIs tool_calls-format er forskellige).
- automatiseret test uden API-nøgler være umuligt.
- model-routing (billig model til simple opgaver, stærk model til komplekse)
  kræve if/else-logik spredt ud over kodebasen.

## Beslutning

Et `LLMGateway` med et fælles `LLMProvider`-interface. Tre implementeringer:
`AnthropicProvider`, `OpenAIProvider`, og en `DeterministicTestProvider`, der
simulerer en scriptet, reproducerbar tool-brugende samtale uden netværkskald.
Gatewayen selv står for: model-routing (`ModelRouter`), retries med backoff
(tenacity), og fallback til test-provideren hvis den primære provider fejler
efter retries.

## Konsekvenser

- Al kode uden for `agentops.gateway` arbejder udelukkende med
  provider-uafhængige schemas (`Message`, `ToolCall`, `CompletionResult`).
- Hele platformen (agent, evals, API, CI) kan testes og demonstreres uden
  nogen API-nøgle, ved at sætte `LLM_DEFAULT_PROVIDER=test`.
- Fallback til test-provideren markeres altid eksplicit
  (`CompletionResult.used_fallback=true`) — det bliver aldrig fremstillet som
  et ægte modelsvar, hverken i traces eller i evalueringsresultater.
- Ulempe: en ny provider kræver en ny oversættelsesklasse (~100 linjer). Det
  er en bevidst pris for at holde resten af systemet enkelt.
