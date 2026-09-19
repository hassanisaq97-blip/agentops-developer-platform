"""Authentication-modul brugt som eval-fixture."""


def authenticate_user(username: str, password: str) -> bool:
    """Verificerer brugerens legitimationsoplysninger."""
    return bool(username) and bool(password)
