from .models import UserModuleAccess

ACTION_CREATE = "create"
ACTION_READ = "read"
ACTION_UPDATE = "update"
ACTION_DELETE = "delete"

REQUESTER_GROUP = "Requester"
PROCUREMENT_GROUP = "Procurement"
TRANSPORT_GROUP = "Transport"
FUEL_GROUP = "Fuel"
VISA_GROUP = "Visas"

ACTION_FIELDS = {
    ACTION_CREATE: "can_create",
    ACTION_READ: "can_read",
    ACTION_UPDATE: "can_update",
    ACTION_DELETE: "can_delete",
}

PROCUREMENT_MODULES = {
    UserModuleAccess.Module.PROCUREMENT,
    UserModuleAccess.Module.SUPPLIERS,
    UserModuleAccess.Module.PURCHASE_INQUIRIES,
    UserModuleAccess.Module.SUPPLIER_INVOICES,
    UserModuleAccess.Module.PURCHASE_ORDERS,
    UserModuleAccess.Module.PURCHASE_RECEIPTS,
}

TRANSPORT_MODULES = {
    UserModuleAccess.Module.TRANSPORT,
    UserModuleAccess.Module.TRANSPORT_REPORTS,
}

FUEL_MODULES = {UserModuleAccess.Module.FUEL}
VISA_MODULES = {UserModuleAccess.Module.VISAS}

NON_REQUISITION_MODULES = {
    module for module, _label in UserModuleAccess.Module.choices
} - {UserModuleAccess.Module.REQUISITIONS}


def user_in_groups(user, groups):
    return user.is_authenticated and user.groups.filter(name__in=groups).exists()


def has_module_access(user, module, action):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    field_name = ACTION_FIELDS[action]
    access = UserModuleAccess.objects.filter(user=user, module=module).first()
    if access is not None:
        return getattr(access, field_name)

    group_names = set(user.groups.values_list("name", flat=True))
    if (
        REQUESTER_GROUP in group_names
        and module == UserModuleAccess.Module.REQUISITIONS
    ):
        return action in {ACTION_CREATE, ACTION_READ}
    if PROCUREMENT_GROUP in group_names:
        if module in PROCUREMENT_MODULES:
            return True
        if module == UserModuleAccess.Module.REQUISITIONS:
            return action in {ACTION_READ, ACTION_UPDATE}
    if TRANSPORT_GROUP in group_names:
        if module == UserModuleAccess.Module.TRANSPORT:
            return True
        if module == UserModuleAccess.Module.TRANSPORT_REPORTS:
            return action == ACTION_READ
        if module == UserModuleAccess.Module.REQUISITIONS:
            return action == ACTION_READ
    if FUEL_GROUP in group_names:
        if module in FUEL_MODULES:
            return True
    if VISA_GROUP in group_names:
        if module in VISA_MODULES:
            return True
    return False


def has_any_module_access(user, modules, actions=None):
    actions = actions or [ACTION_CREATE, ACTION_READ, ACTION_UPDATE, ACTION_DELETE]
    return any(
        has_module_access(user, module, action)
        for module in modules
        for action in actions
    )


def has_only_requisition_access(user):
    if not user or not user.is_authenticated or user.is_superuser:
        return False
    if not has_any_module_access(user, [UserModuleAccess.Module.REQUISITIONS]):
        return False
    return not has_any_module_access(user, NON_REQUISITION_MODULES)


def can_edit_requisition(user, requisition):
    if not user or not user.is_authenticated:
        return False
    if requisition.status != requisition.Status.SUBMITTED:
        return False
    if user.is_superuser:
        return True
    if has_module_access(user, UserModuleAccess.Module.REQUISITIONS, ACTION_UPDATE):
        return True
    return (
        requisition.requester_id == user.id
        and has_module_access(user, UserModuleAccess.Module.REQUISITIONS, ACTION_CREATE)
        and has_module_access(user, UserModuleAccess.Module.REQUISITIONS, ACTION_READ)
    )
