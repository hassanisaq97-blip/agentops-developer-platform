"""Tekstformattering brugt som eval-fixture."""


def truncate(text: str, max_length: int) -> str:
    # BUG: mangler "..."-suffiks og afkorter ét tegn for kort.
    return text[: max_length - 1]


def title_case(text: str) -> str:
    return " ".join(word.capitalize() for word in text.split())
