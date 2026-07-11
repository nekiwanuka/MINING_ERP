from django import template

from operations.i18n import translate

register = template.Library()


@register.filter
def tr(text, language="en"):
    return translate(text, language)
