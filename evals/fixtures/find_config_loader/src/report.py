"""Uden relation til konfigurationsindlæsning — bruges til at teste, at agenten ikke gætter forkert."""


def generate_summary(items: list[str]) -> str:
    return ", ".join(items)
