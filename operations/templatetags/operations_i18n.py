from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

from operations.i18n import translate

register = template.Library()


@register.filter
def tr(text, language="en"):
    return translate(text, language)


@register.simple_tag(takes_context=True)
def money(context, value):
    currency = context.get("display_currency", "USD")
    if currency not in {"USD", "UGX"}:
        currency = "USD"
    try:
        amount = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")
    try:
        exchange_rate = Decimal(str(context.get("ugx_exchange_rate", "3800")))
    except (InvalidOperation, TypeError, ValueError):
        exchange_rate = Decimal("3800")
    if exchange_rate <= 0:
        exchange_rate = Decimal("3800")
    if currency == "UGX":
        amount *= exchange_rate
    amount = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{currency} {amount:.0f}"
