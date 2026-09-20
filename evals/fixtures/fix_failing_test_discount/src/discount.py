"""Prisberegning med loyalitetsbonus, brugt som eval-fixture."""


def total_with_loyalty_bonus(base_price: float, bonus_credit: float) -> float:
    return base_price - bonus_credit


def apply_percentage_discount(base_price: float, percentage: float) -> float:
    return base_price - base_price * percentage
