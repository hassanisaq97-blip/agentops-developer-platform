class LLMGatewayError(Exception):
    """Base-exception for alle gateway-fejl — normaliseret på tværs af providers."""


class ProviderError(LLMGatewayError):
    """En enkelt providers kald fejlede (efter retries)."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class AllProvidersFailedError(LLMGatewayError):
    """Både den valgte provider og eventuel fallback-provider fejlede."""


class UnknownProviderError(LLMGatewayError):
    """Der er anmodet om en provider, der ikke er registreret i gatewayen."""
