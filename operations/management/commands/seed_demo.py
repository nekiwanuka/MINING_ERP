from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from operations.models import UserModuleAccess


class Command(BaseCommand):
    help = "Create demo ERP groups and login credentials."

    def handle(self, *args, **options):
        credentials = [
            ("requester", "Requester", False, False),
            ("procurement", "Procurement", False, False),
            ("transport", "Transport", False, False),
            ("fuel", "Fuel", False, False),
            ("visas", "Visas", False, False),
            ("admin", "Admin", True, True),
        ]
        password = "MiningERP2026!"
        user_model = get_user_model()

        groups = {
            name: Group.objects.get_or_create(name=name)[0]
            for name in ["Requester", "Procurement", "Transport", "Fuel", "Visas"]
        }
        for username, group_name, is_staff, is_superuser in credentials:
            user, _created = user_model.objects.get_or_create(username=username)
            user.set_password(password)
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.save()
            if group_name in groups:
                user.groups.add(groups[group_name])

            if username == "requester":
                self.grant(
                    user, UserModuleAccess.Module.REQUISITIONS, create=True, read=True
                )
            elif username == "procurement":
                self.grant(user, UserModuleAccess.Module.PROCUREMENT, read=True)
                self.grant(
                    user, UserModuleAccess.Module.REQUISITIONS, read=True, update=True
                )
                for module in [
                    UserModuleAccess.Module.SUPPLIERS,
                    UserModuleAccess.Module.PURCHASE_INQUIRIES,
                    UserModuleAccess.Module.SUPPLIER_INVOICES,
                    UserModuleAccess.Module.PURCHASE_ORDERS,
                    UserModuleAccess.Module.PURCHASE_RECEIPTS,
                    UserModuleAccess.Module.COMMERCIAL_DOCUMENTS,
                    UserModuleAccess.Module.FINANCIAL_REPORTS,
                ]:
                    self.grant(
                        user, module, create=True, read=True, update=True, delete=True
                    )
            elif username == "transport":
                self.grant(user, UserModuleAccess.Module.REQUISITIONS, read=True)
                self.grant(
                    user,
                    UserModuleAccess.Module.TRANSPORT,
                    create=True,
                    read=True,
                    update=True,
                    delete=True,
                )
                self.grant(user, UserModuleAccess.Module.TRANSPORT_REPORTS, read=True)
                self.grant(
                    user,
                    UserModuleAccess.Module.COMMERCIAL_DOCUMENTS,
                    create=True,
                    read=True,
                    update=True,
                )
            elif username == "fuel":
                self.grant(
                    user,
                    UserModuleAccess.Module.FUEL,
                    create=True,
                    read=True,
                    update=True,
                    delete=True,
                )
            elif username == "visas":
                self.grant(
                    user,
                    UserModuleAccess.Module.VISAS,
                    create=True,
                    read=True,
                    update=True,
                    delete=True,
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Demo credentials created. Password for all demo users: MiningERP2026!"
            )
        )

    def grant(self, user, module, create=False, read=False, update=False, delete=False):
        UserModuleAccess.objects.update_or_create(
            user=user,
            module=module,
            defaults={
                "can_create": create,
                "can_read": read,
                "can_update": update,
                "can_delete": delete,
            },
        )
