from .access import ACTION_CREATE, ACTION_READ, has_module_access
from .i18n import LANGUAGE_LABELS, normalize_language, translate
from .models import ApplicationSetting, UserModuleAccess


def module_access(request):
    user = getattr(request, "user", None)
    app_setting = ApplicationSetting.load()
    active_language = normalize_language(
        request.session.get(
            "active_language",
            request.COOKIES.get("active_language", app_setting.default_language),
        )
    )
    return {
        "app_setting": app_setting,
        "app_language_options": [
            {"code": code, "label": LANGUAGE_LABELS.get(code, label)}
            for code, label in ApplicationSetting.Language.choices
        ],
        "active_language": active_language,
        "t": lambda text: translate(text, active_language),
        "can_create_requisitions": has_module_access(
            user, UserModuleAccess.Module.REQUISITIONS, ACTION_CREATE
        ),
        "can_read_requisitions": has_module_access(
            user, UserModuleAccess.Module.REQUISITIONS, ACTION_READ
        ),
        "can_read_procurement": has_module_access(
            user, UserModuleAccess.Module.PROCUREMENT, ACTION_READ
        ),
        "can_read_transport": has_module_access(
            user, UserModuleAccess.Module.TRANSPORT, ACTION_READ
        ),
        "can_read_transport_reports": has_module_access(
            user, UserModuleAccess.Module.TRANSPORT_REPORTS, ACTION_READ
        ),
        "can_read_commercial_documents": has_module_access(
            user, UserModuleAccess.Module.COMMERCIAL_DOCUMENTS, ACTION_READ
        ),
        "can_read_fuel": has_module_access(
            user, UserModuleAccess.Module.FUEL, ACTION_READ
        ),
        "can_read_visas": has_module_access(
            user, UserModuleAccess.Module.VISAS, ACTION_READ
        ),
        "can_manage_users": bool(user and user.is_authenticated and user.is_superuser),
        "can_manage_setup": bool(user and user.is_authenticated and user.is_superuser),
        "can_show_api": bool(user and user.is_authenticated and user.is_superuser),
    }
