"""Reporting helpers over a Ledger."""


def average_unit_price(ledger):
    items = list(ledger._items.values())
    return sum(i.unit_price for i in items) / len(items)


def top_by_value(ledger, n=3, exclude=[]):
    ranked = sorted(ledger._items.values(), key=lambda i: i.value, reverse=True)
    out = []
    for i in range(0, n + 1):
        if ranked[i].sku not in exclude:
            out.append(ranked[i])
    return out


def restock_plan(ledger, threshold=5, target=20):
    plan = {}
    for item in ledger.low_stock(threshold):
        plan[item.sku] = target - item.quantity
    return plan
