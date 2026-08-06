from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

from operations.i18n import translate

register = template.Library()


@register.filter
def tr(text, language="en"):
    return translate(text, language)


@register.filter
def status_class(value):
    normalized = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    status_map = {
        "submitted": "status-submitted",
        "draft": "status-draft",
        "pending": "status-pending",
        "pending-invoice": "status-pending",
        "accepted": "status-accepted",
        "accepted-by-procurement": "status-accepted",
        "purchase-inquiries-sent": "status-inquiry",
        "inquiries-sent": "status-inquiry",
        "invoice-loaded": "status-inquiry",
        "ordered": "status-issued",
        "issued": "status-issued",
        "finalized": "status-issued",
        "receipt-uploaded": "status-paid",
        "receipt-issued": "status-paid",
        "paid": "status-paid",
        "purchased": "status-paid",
        "in-delivery": "status-transit",
        "in-transportation": "status-transit",
        "in-transit": "status-transit",
        "delivered": "status-delivered",
        "active": "status-active",
        "inactive": "status-inactive",
        "cancelled": "status-cancelled",
        "expired": "status-expired",
        "expires-soon": "status-warning",
        "valid": "status-active",
        "not-started": "status-draft",
        "preparing-documents": "status-warning",
        "submitted-to-embassy": "status-submitted",
        "approved-renewed": "status-paid",
        "rejected": "status-cancelled",
    }
    return status_map.get(normalized, "status-neutral")


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


@register.simple_tag(takes_context=True)
def querystring_without_page(context):
    request = context.get("request")
    if not request:
        return ""
    query = request.GET.copy()
    query.pop("page", None)
    encoded = query.urlencode()
    return f"{encoded}&" if encoded else ""


@register.simple_tag
def get_field(form, field_name):
    try:
        return form[field_name]
    except Exception:
        return None
