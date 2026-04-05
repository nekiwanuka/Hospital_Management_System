from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter(name="ugx")
def ugx(value):
    """Format numeric values using UGX currency notation."""
    if value in (None, ""):
        return "UGX 0.00"

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return f"UGX {value}"

    return f"UGX {amount:,.2f}"


@register.filter(name="commas")
def commas(value):
    """Add thousand separators: 20000 → 20,000."""
    if value in (None, ""):
        return "0"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    if amount == amount.to_integral_value():
        return f"{int(amount):,}"
    return f"{amount:,.2f}"
