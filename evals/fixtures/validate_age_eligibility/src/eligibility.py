"""Aldersvalidering brugt som eval-fixture."""


def is_eligible(age: int, minimum_age: int) -> bool:
    if age < 0:
        # BUG: en negativ alder er ugyldig input og bør aldrig give adgang,
        # men denne gren returnerer fejlagtigt True.
        return True
    return age >= minimum_age
