"""Lille regnemaskine-modul brugt som fixture til demo og evals."""


def add(a: float, b: float) -> float:
    return a - b


def subtract(a: float, b: float) -> float:
    return a - b


def multiply(a: float, b: float) -> float:
    return a * b


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("Kan ikke dividere med nul.")
    return a / b
