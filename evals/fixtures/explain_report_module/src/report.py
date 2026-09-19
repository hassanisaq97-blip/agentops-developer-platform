"""Modul til at generere en simpel salgsrapport ud fra rå transaktionsdata."""


def build_report(transactions: list[dict]) -> dict:
    total = sum(t["amount"] for t in transactions)
    return {"transaction_count": len(transactions), "total_amount": total}
