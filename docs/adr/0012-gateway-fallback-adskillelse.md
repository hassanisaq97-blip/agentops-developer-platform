# ADR 0012: Adskillelse af test-fallback og rigtigt provider-failover

## Status

Accepteret. Reviderer den oprindelige fallback-beslutning i ADR 0002.

## Kontekst

`LLMGateway` har altid haft en fallback-mekanisme: hvis den primære provider
fejler efter retries (`ProviderError`), forsøger gatewayen en
`fallback_provider` i stedet, og markerer resultatet tydeligt med
`used_fallback=true`. `LLMGateway.__init__`'s parameter
`fallback_provider` defaultede til `"test"` — den deterministiske
test-provider.

Det var en fornuftig default for at holde CLASSEN simpel at bruge i tests
(ingen API-nøgle nødvendig for at demonstrere selve fallback-mekanikken),
men `agentops.gateway.factory.build_gateway` — den ENESTE konstruktør,
FastAPI-appen og `scripts/run_evals.py` faktisk bruger i drift — arvede
denne default uden at overveje det eksplicit. Konsekvensen: hvis Anthropic
(eller OpenAI) reelt går ned eller rate-limiter i produktion, ville
gatewayen stille falde tilbage til den deterministiske test-provider —
en scriptet state machine, der KUN genkender ét bug-mønster
(`return X - Y`) og ellers svarer med en generisk "kunne ikke løse
opgaven"-tekst. For en bruger ville det se ud som om opgaven blev
"løst" af en model, mens den reelt blev håndteret af en playbook uden
nogen forbindelse til det faktiske repository-indhold. `used_fallback=true`
er ganske vist synligt i `TaskResponse` og i traces, men det er let at
overse, og en test-double bør aldrig kunne fremstå som et gyldigt
produktionssvar, uanset hvor tydeligt det er flagget.

## Beslutning

1. `LLMGateway.__init__`'s `fallback_provider`-default ændret fra `"test"`
   til `None`. Enhver kaldende kode skal nu eksplicit vælge en
   fallback-provider — der er ingen "gratis" utilsigtet fallback længere.
2. `build_gateway()` sætter `fallback_provider` til en ANDEN faktisk
   konfigureret rigtig provider (fx OpenAI, hvis Anthropic er primær og
   begge nøgler er sat) — et ægte provider-til-provider failover, som er
   den type fallback, en produktionsplatform faktisk bør have.
3. Hvis kun én rigtig provider (eller ingen) er konfigureret, sættes
   `fallback_provider=None`. Et udfald efter retries propagerer da som
   `ProviderError`/`AllProvidersFailedError`, som API-laget
   (`agentops.api.routers.tasks`) fanger og oversætter til en tydeligt
   markeret `FAILED`-opgave med en forklarende `warning` — aldrig et
   stiltiende, fabrikeret "success".
4. `POST /tasks/{id}/approve` fik samme try/except-mønster som
   `POST /tasks` (`create_task`) — inden denne ændring kunne en fejlet
   `resume()` (fx et provider-udfald under genoptagelse efter en
   godkendelse) give en uhåndteret 500 i stedet for et forklaret
   opgaveresultat.
5. `LLM_DEFAULT_PROVIDER=test` (dev/CI/evalueringer) er upåvirket: der er
   intet "rigtigt udfald" at falde tilbage fra, når test-provideren SELV er
   den primære, valgte provider — det er stadig den tilsigtede måde at
   køre platformen uden API-nøgler på.

## Konsekvenser

- **Trade-off, eksplicit accepteret:** uden en anden rigtig provider
  konfigureret, betyder dette, at et Anthropic-udfald nu resulterer i en
  `FAILED`-opgave i stedet for et (usikkert, men "færdigt") deterministisk
  svar. Det er en bevidst prioritering af ærlighed over tilgængelighed —
  jf. CLAUDE.md's krav om aldrig at fremstille noget som en model-løsning,
  når det ikke er en.
- Tests, der bevidst vil demonstrere/verificere selve
  fallback-mekanismen i `LLMGateway` (fx
  `test_gateway_retries_then_falls_back_to_test_provider`), sætter fortsat
  `fallback_provider="test"` eksplicit ved konstruktion — det er en gyldig
  brug af klassen i et testscenarie, bare ikke en implicit default i
  produktionskoden.
- Kræver, at en operatør, der ønsker ægte provider-redundans, konfigurerer
  BEGGE providers (`ANTHROPIC_API_KEY` og `OPENAI_API_KEY`) — uden det er
  der ingen fallback, hvilket er korrekt: der findes ingen anden rigtig
  provider at falde tilbage til.
