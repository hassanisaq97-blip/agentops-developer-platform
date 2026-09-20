"""Prisberegning med duplikeret logik, brugt som refaktorerings-fixture."""


def price_with_tax(price: float, tax_rate: float) -> float:
    return price + price * tax_rate


def price_with_tax_and_shipping(price: float, tax_rate: float, shipping: float) -> float:
    # Duplikerer skatteberegningen fra price_with_tax i stedet for at genbruge den.
    return price + price * tax_rate + shipping
