from __future__ import annotations

from abc import ABC, abstractmethod

from agentops.gateway.schemas import CompletionRequest, CompletionResult


class LLMProvider(ABC):
    """Fælles interface alle LLM-providers skal implementere.

    En provider kender kun til ÉT kald til ÉN model — retries, timeouts,
    fallback og routing på tværs af providers håndteres af `LLMGateway`.
    """

    name: str

    @abstractmethod
    def complete(self, request: CompletionRequest, *, model: str) -> CompletionResult:
        """Udfør ét completion-kald. Skal kaste ProviderError ved fejl, aldrig returnere en gættet værdi."""
        raise NotImplementedError
