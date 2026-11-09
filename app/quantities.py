"""Decimal shopping quantities; no conversion between mass, volume, and count."""

from decimal import Decimal, InvalidOperation

from .db import DataError

UNITS = {
    "g": ("g", Decimal(1)), "gram": ("g", Decimal(1)), "grams": ("g", Decimal(1)),
    "kg": ("g", Decimal(1000)), "mg": ("g", Decimal("0.001")),
    "ml": ("ml", Decimal(1)), "l": ("ml", Decimal(1000)),
    "tsp": ("ml", Decimal("4.92892159375")),
    "tbsp": ("ml", Decimal("14.78676478125")),
    "cup": ("ml", Decimal("236.5882365")),
    "each": ("each", Decimal(1)), "item": ("each", Decimal(1)),
}


def quantity(value):
    try:
        if isinstance(value, bool):
            raise ValueError
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > Decimal("1000000000") or amount < Decimal("0.00000001"):
            raise ValueError
        return format(amount.normalize(), "f")
    except (InvalidOperation, ValueError):
        raise DataError("Amounts and servings must be positive finite decimal quantities.") from None


def unit_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 40:
        raise DataError("An ingredient unit is required (for example g, ml, or each).")
    return " ".join(value.lower().split())


def base_quantity(amount, unit):
    unit = unit_name(unit)
    canonical, multiplier = UNITS.get(unit, (unit, Decimal(1)))
    return Decimal(quantity(amount)) * multiplier, canonical
