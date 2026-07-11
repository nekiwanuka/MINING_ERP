from datetime import timedelta
from io import StringIO
from decimal import Decimal

from django.core import mail
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    ApplicationSetting,
    BusinessClient,
    CommercialDocument,
    Expatriate,
    ExpatriateVisa,
    FinancialRecord,
    FuelAsset,
    FuelIssue,
    FuelStockBatch,
    PurchaseInquiry,
    PurchaseOrder,
    Requisition,
    RequisitionItem,
    Supplier,
    SupplierInvoice,
    TransportCustomerInvoice,
    TransportGovernmentCharge,
    TransportRecord,
    UserModuleAccess,
    VisaEmbassy,
)


class ProtectedApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="requester", password="MiningERP2026!"
        )
        UserModuleAccess.objects.create(
            user=self.user,
            module=UserModuleAccess.Module.REQUISITIONS,
            can_create=True,
            can_read=True,
        )

    def create_requisition(self, status=Requisition.Status.SUBMITTED):
        requisition = Requisition.objects.create(
            requester=self.user,
            item_description="Crusher spare parts (4 pcs)",
            language=Requisition.Language.ENGLISH,
            quantity=Decimal("4.00"),
            status=status,
        )
        requisition.items.create(description="Crusher spare parts", pieces=4)
        return requisition

    def test_requisition_api_requires_authentication(self):
        response = self.client.get("/api/requisitions/")
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_api_root_redirects_non_admins_to_login(self):
        anonymous_response = self.client.get("/api/")
        uppercase_response = self.client.get("/API/")
        self.client.force_authenticate(user=self.user)
        non_admin_response = self.client.get("/api/")

        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn("/login/", anonymous_response.headers["Location"])
        self.assertEqual(uppercase_response.status_code, 302)
        self.assertIn("/login/", uppercase_response.headers["Location"])
        self.assertEqual(non_admin_response.status_code, 302)
        self.assertIn("/login/", non_admin_response.headers["Location"])

    def test_non_admin_user_cannot_submit_requisition_through_api(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/requisitions/",
            {
                "language": "en",
                "urgent": True,
                "items": [
                    {"description": "Crusher spare parts", "pieces": 4},
                    {"description": "Conveyor rollers", "pieces": 8},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Requisition.objects.exists())

    def test_signed_in_admin_can_access_api(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin", password="MiningERP2026!"
        )
        self.client.force_login(admin_user)
        api_root_response = self.client.get("/api/")
        self.client.force_authenticate(user=admin_user)

        create_response = self.client.post(
            "/api/suppliers/",
            {"name": "Admin Drill Supply"},
            format="json",
        )
        read_response = self.client.get("/api/suppliers/")

        self.assertEqual(api_root_response.status_code, status.HTTP_200_OK)
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(read_response.status_code, status.HTTP_200_OK)
        self.assertTrue(Supplier.objects.filter(name="Admin Drill Supply").exists())

    def test_template_requisition_create_accepts_multiple_items(self):
        self.client.login(username="requester", password="MiningERP2026!")
        response = self.client.post(
            "/requisitions/new/",
            {
                "language": "fr",
                "urgent": "on",
                "items-TOTAL_FORMS": "3",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "1",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-description": "Pompe hydraulique",
                "items-0-pieces": "2",
                "items-1-description": "Tuyau haute pression",
                "items-1-pieces": "6",
                "items-2-description": "",
                "items-2-pieces": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        requisition = Requisition.objects.prefetch_related("items").get()
        self.assertTrue(requisition.urgent)
        self.assertEqual(requisition.items.count(), 2)
        self.assertEqual(requisition.total_pieces, 8)

    def test_requester_only_sees_requisition_navigation(self):
        self.client.login(username="requester", password="MiningERP2026!")

        dashboard_response = self.client.get("/")
        requisition_response = self.client.get("/requisitions/")
        restricted_response = self.client.get("/procurement/")
        content = requisition_response.content.decode()

        self.assertEqual(dashboard_response.status_code, 302)
        self.assertEqual(dashboard_response.headers["Location"], "/requisitions/new/")
        self.assertContains(requisition_response, "Requisitions")
        self.assertNotContains(requisition_response, "Procurement")
        self.assertNotContains(requisition_response, "Transport")
        self.assertNotContains(requisition_response, "Reports")
        self.assertNotIn(">API<", content)
        self.assertEqual(restricted_response.status_code, 302)

    def test_requester_can_edit_own_submitted_requisition(self):
        requisition = self.create_requisition()
        item = requisition.items.first()
        self.client.login(username="requester", password="MiningERP2026!")

        response = self.client.post(
            f"/requisitions/{requisition.pk}/edit/",
            {
                "language": "zh",
                "items-TOTAL_FORMS": "4",
                "items-INITIAL_FORMS": "1",
                "items-MIN_NUM_FORMS": "1",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-id": str(item.pk),
                "items-0-requisition": str(requisition.pk),
                "items-0-description": "破碎机备件",
                "items-0-pieces": "5",
                "items-1-requisition": str(requisition.pk),
                "items-1-description": "输送带滚筒",
                "items-1-pieces": "3",
                "items-2-description": "",
                "items-2-pieces": "",
                "items-3-description": "",
                "items-3-pieces": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        requisition.refresh_from_db()
        self.assertEqual(requisition.language, "zh")
        self.assertEqual(requisition.total_pieces, 8)
        self.assertEqual(requisition.items.count(), 2)

    def test_requester_cannot_edit_accepted_requisition(self):
        requisition = self.create_requisition(status=Requisition.Status.ACCEPTED)
        self.client.login(username="requester", password="MiningERP2026!")

        response = self.client.get(f"/requisitions/{requisition.pk}/edit/")

        self.assertEqual(response.status_code, 403)

    def test_non_admin_requester_cannot_update_requisition_through_api(self):
        requisition = self.create_requisition()
        self.client.force_authenticate(user=self.user)

        submitted_response = self.client.patch(
            f"/api/requisitions/{requisition.pk}/",
            {
                "urgent": True,
                "items": [{"description": "Edited spare", "pieces": 9}],
            },
            format="json",
        )
        requisition.status = Requisition.Status.ACCEPTED
        requisition.save(update_fields=["status", "updated_at"])
        accepted_response = self.client.patch(
            f"/api/requisitions/{requisition.pk}/",
            {"urgent": False},
            format="json",
        )

        self.assertEqual(submitted_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(accepted_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_blocks_non_admin_even_with_module_action_permissions(self):
        supplier_user = get_user_model().objects.create_user(
            username="supplier-clerk", password="MiningERP2026!"
        )
        UserModuleAccess.objects.create(
            user=supplier_user,
            module=UserModuleAccess.Module.SUPPLIERS,
            can_create=True,
            can_read=False,
        )
        self.client.force_authenticate(user=supplier_user)

        create_response = self.client.post(
            "/api/suppliers/",
            {"name": "Drill Supply Co"},
            format="json",
        )
        read_response = self.client.get("/api/suppliers/")

        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(read_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Supplier.objects.filter(name="Drill Supply Co").exists())


class LoginExperienceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="clerk", password="MiningERP2026!"
        )

    def test_login_page_has_password_preview_and_remember_controls(self):
        response = self.client.get("/login/?next=/api/")

        self.assertContains(response, "Sign in")
        self.assertNotContains(response, "Secure department access")
        self.assertNotContains(response, "Requisitions")
        self.assertContains(response, "password-toggle")
        self.assertContains(response, "Contact administrator")
        self.assertContains(response, "password-toggle-icon")
        self.assertContains(response, "Remember my username")
        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertContains(response, 'name="next" value="/api/"')

    def test_remember_me_uses_one_hour_idle_session_and_remembers_username(self):
        response = self.client.post(
            "/login/",
            {
                "username": "clerk",
                "password": "MiningERP2026!",
                "remember_me": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertEqual(self.client.session.get_expiry_age(), 60 * 60)
        self.assertEqual(response.cookies["mining_erp_username"].value, "clerk")

    def test_login_without_remember_me_still_uses_one_hour_idle_session(self):
        response = self.client.post(
            "/login/",
            {"username": "clerk", "password": "MiningERP2026!"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertEqual(self.client.session.get_expiry_age(), 60 * 60)
        self.assertEqual(response.cookies["mining_erp_username"].value, "")

    def test_wrong_route_shows_module_not_found_message(self):
        response = self.client.get("/wrong-address-route/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Module not found", status_code=404)
        self.assertContains(response, "Contact administrator", status_code=404)


class UserAccessManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin", password="MiningERP2026!"
        )
        self.client.login(username="admin", password="MiningERP2026!")

    def access_payload(self, module_actions):
        modules = [module for module, _label in UserModuleAccess.Module.choices]
        data = {
            "username": "warehouse",
            "first_name": "Warehouse",
            "last_name": "Clerk",
            "email": "warehouse@example.com",
            "password": "MiningERP2026!",
            "is_active": "on",
            "access-TOTAL_FORMS": str(len(modules)),
            "access-INITIAL_FORMS": "0",
            "access-MIN_NUM_FORMS": "0",
            "access-MAX_NUM_FORMS": "1000",
        }
        for index, module in enumerate(modules):
            data[f"access-{index}-module"] = module
            actions = module_actions.get(module, set())
            if "create" in actions:
                data[f"access-{index}-can_create"] = "on"
            if "read" in actions:
                data[f"access-{index}-can_read"] = "on"
            if "update" in actions:
                data[f"access-{index}-can_update"] = "on"
            if "delete" in actions:
                data[f"access-{index}-can_delete"] = "on"
        return data

    def test_superuser_can_create_user_with_selected_module_permissions(self):
        form_page = self.client.get("/access/users/new/")

        self.assertContains(form_page, "Fuel Department")
        self.assertContains(form_page, "Visa Department")
        self.assertContains(form_page, "Business Documents")
        self.assertContains(form_page, "Financial Reports")

        response = self.client.post(
            "/access/users/new/",
            self.access_payload(
                {
                    UserModuleAccess.Module.REQUISITIONS: {"create", "read"},
                    UserModuleAccess.Module.FUEL: {
                        "create",
                        "read",
                        "update",
                        "delete",
                    },
                    UserModuleAccess.Module.VISAS: {
                        "create",
                        "read",
                        "update",
                        "delete",
                    },
                    UserModuleAccess.Module.TRANSPORT: {
                        "create",
                        "read",
                        "update",
                        "delete",
                    },
                    UserModuleAccess.Module.COMMERCIAL_DOCUMENTS: {
                        "create",
                        "read",
                        "update",
                    },
                    UserModuleAccess.Module.FINANCIAL_REPORTS: {
                        "create",
                        "read",
                    },
                }
            ),
        )

        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="warehouse")
        requisition_access = UserModuleAccess.objects.get(
            user=user, module=UserModuleAccess.Module.REQUISITIONS
        )
        transport_access = UserModuleAccess.objects.get(
            user=user, module=UserModuleAccess.Module.TRANSPORT
        )
        document_access = UserModuleAccess.objects.get(
            user=user, module=UserModuleAccess.Module.COMMERCIAL_DOCUMENTS
        )
        finance_access = UserModuleAccess.objects.get(
            user=user, module=UserModuleAccess.Module.FINANCIAL_REPORTS
        )
        fuel_access = UserModuleAccess.objects.get(
            user=user, module=UserModuleAccess.Module.FUEL
        )
        visa_access = UserModuleAccess.objects.get(
            user=user, module=UserModuleAccess.Module.VISAS
        )
        self.assertTrue(requisition_access.can_create)
        self.assertTrue(requisition_access.can_read)
        self.assertFalse(requisition_access.can_update)
        self.assertTrue(transport_access.can_delete)
        self.assertTrue(document_access.can_create)
        self.assertTrue(document_access.can_read)
        self.assertTrue(document_access.can_update)
        self.assertFalse(document_access.can_delete)
        self.assertTrue(finance_access.can_create)
        self.assertTrue(finance_access.can_read)
        self.assertFalse(finance_access.can_update)
        self.assertTrue(fuel_access.can_create)
        self.assertTrue(fuel_access.can_read)
        self.assertTrue(fuel_access.can_update)
        self.assertTrue(fuel_access.can_delete)
        self.assertTrue(visa_access.can_create)
        self.assertTrue(visa_access.can_read)
        self.assertTrue(visa_access.can_update)
        self.assertTrue(visa_access.can_delete)

    def test_superuser_can_update_application_setup(self):
        response = self.client.post(
            "/setup/application/",
            {
                "application_name": "Kilembe Mining ERP",
                "address": "Plot 12 Mine Road, Kasese",
                "theme": ApplicationSetting.Theme.COPPER,
                "default_language": ApplicationSetting.Language.FRENCH,
                "enable_language_switcher": "on",
            },
        )

        setting = ApplicationSetting.load()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(setting.application_name, "Kilembe Mining ERP")
        self.assertEqual(setting.address, "Plot 12 Mine Road, Kasese")
        self.assertEqual(setting.theme, ApplicationSetting.Theme.COPPER)
        self.assertEqual(setting.default_language, ApplicationSetting.Language.FRENCH)

        page = self.client.get("/")
        self.assertContains(page, "Kilembe Mining ERP")
        self.assertContains(page, "theme-copper")
        self.assertContains(page, "Plot 12 Mine Road")

    def test_language_switcher_sets_session_and_cookie(self):
        response = self.client.get("/language/?language=zh&next=/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")
        self.assertEqual(self.client.session["active_language"], "zh")
        self.assertEqual(response.cookies["active_language"].value, "zh")

    def test_language_dictionary_is_available_across_dashboard_pages(self):
        self.client.get("/language/?language=zh&next=/")

        response = self.client.get("/")
        ui_translations = response.context["ui_translations"]

        self.assertContains(response, "ui-translations")
        self.assertEqual(ui_translations["ERP dashboard"], "ERP 仪表板")
        self.assertEqual(ui_translations["Operations Control"], "运营控制")
        self.assertEqual(ui_translations["Total requisitions"], "申请总数")
        self.assertEqual(ui_translations["Document register"], "单据登记簿")
        self.assertEqual(ui_translations["Account Statement"], "对账单")
        self.assertEqual(ui_translations["Transport Invoice"], "运输发票")


class ProcurementWorkflowTests(TestCase):
    def setUp(self):
        self.requester = get_user_model().objects.create_user(
            username="mine-requester", password="MiningERP2026!"
        )
        self.procurement = get_user_model().objects.create_user(
            username="procurement", password="MiningERP2026!"
        )
        self.supplier = Supplier.objects.create(name="Copper Belt Supplies")
        for module, actions in {
            UserModuleAccess.Module.PROCUREMENT: {"read"},
            UserModuleAccess.Module.REQUISITIONS: {"read", "update"},
            UserModuleAccess.Module.PURCHASE_INQUIRIES: {"create", "read"},
            UserModuleAccess.Module.SUPPLIER_INVOICES: {"create", "read"},
            UserModuleAccess.Module.PURCHASE_ORDERS: {"create", "read"},
            UserModuleAccess.Module.PURCHASE_RECEIPTS: {"create", "read"},
        }.items():
            UserModuleAccess.objects.create(
                user=self.procurement,
                module=module,
                can_create="create" in actions,
                can_read="read" in actions,
                can_update="update" in actions,
                can_delete="delete" in actions,
            )

    def create_submitted_requisition(self):
        requisition = Requisition.objects.create(
            requester=self.requester,
            item_description="Drill bit set (12 pcs)",
            language=Requisition.Language.ENGLISH,
            quantity=Decimal("12.00"),
            status=Requisition.Status.SUBMITTED,
        )
        requisition.items.create(description="Drill bit set", pieces=12)
        return requisition

    def test_procurement_processes_requisition_item_up_to_purchase_order(self):
        requisition = self.create_submitted_requisition()
        item = requisition.items.first()
        self.client.login(username="procurement", password="MiningERP2026!")

        accept_response = self.client.post(
            f"/procurement/requisitions/{requisition.pk}/accept/"
        )
        inquiry_response = self.client.post(
            f"/procurement/requisition-items/{item.pk}/inquiries/new/",
            {
                "supplier": str(self.supplier.pk),
                "description": item.description,
                "quantity": "12.00",
            },
        )
        inquiry = PurchaseInquiry.objects.get()
        invoice_response = self.client.post(
            f"/procurement/inquiries/{inquiry.pk}/invoice/",
            {
                "new_supplier_name": "Copper Belt Imports",
                "invoice_number": "INV-001",
                "invoice_date": "2026-07-05",
                "amount": "4500.00",
                "attachment": SimpleUploadedFile(
                    "invoice.pdf", b"supplier invoice", content_type="application/pdf"
                ),
            },
        )
        order_response = self.client.post(
            f"/procurement/inquiries/{inquiry.pk}/purchase-order/",
            {"amount": "4500.00", "order_date": "2026-07-05"},
        )
        order = PurchaseOrder.objects.get()
        receipt_response = self.client.post(
            f"/procurement/orders/{order.pk}/receipt/",
            {
                "receipt_number": "RCT-001",
                "receipt_date": "2026-07-06",
                "attachment": SimpleUploadedFile(
                    "receipt.pdf", b"purchase receipt", content_type="application/pdf"
                ),
            },
        )
        process_response = self.client.get(
            f"/procurement/requisition-process/?q={requisition.requisition_number}"
        )

        requisition.refresh_from_db()
        inquiry.refresh_from_db()
        invoice = SupplierInvoice.objects.get()
        order.refresh_from_db()

        self.assertEqual(accept_response.status_code, 302)
        self.assertEqual(inquiry_response.status_code, 302)
        self.assertEqual(invoice_response.status_code, 302)
        self.assertEqual(order_response.status_code, 302)
        self.assertEqual(receipt_response.status_code, 302)
        self.assertContains(process_response, requisition.requisition_number)
        self.assertContains(process_response, inquiry.inquiry_number)
        self.assertContains(process_response, invoice.invoice_number)
        self.assertContains(process_response, order.order_number)
        self.assertContains(process_response, "RCT-001")
        self.assertEqual(inquiry.requisition_item, item)
        self.assertEqual(inquiry.supplier.name, "Copper Belt Imports")
        self.assertIsNotNone(inquiry.sent_at)
        self.assertEqual(inquiry.status, PurchaseInquiry.Status.ORDERED)
        self.assertEqual(invoice.requisition_number, requisition.requisition_number)
        self.assertEqual(invoice.supplier_name, "Copper Belt Imports")
        self.assertEqual(invoice.supplier, inquiry.supplier)
        self.assertEqual(order.inquiry, inquiry)
        self.assertEqual(order.supplier, inquiry.supplier)
        self.assertEqual(requisition.status, Requisition.Status.PURCHASED)

    def test_procurement_reviews_splits_and_sends_purchase_orders(self):
        setting = ApplicationSetting.load()
        setting.address = "Plot 12 Mine Road, Kasese"
        setting.save(update_fields=["address", "updated_at"])
        requisition = self.create_submitted_requisition()
        first_item = requisition.items.first()
        self.supplier.email = "orders@copper.example"
        self.supplier.phone = "+256700000002"
        self.supplier.save(update_fields=["email", "phone", "updated_at"])
        self.client.login(username="procurement", password="MiningERP2026!")

        review_response = self.client.post(
            f"/procurement/requisitions/{requisition.pk}/review/",
            {
                "language": "en",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "1",
                "items-MIN_NUM_FORMS": "1",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-id": str(first_item.pk),
                "items-0-requisition": str(requisition.pk),
                "items-0-description": "Reviewed drill bit set",
                "items-0-pieces": "12",
            },
        )
        item = RequisitionItem.objects.get(requisition=requisition)
        first_order_response = self.client.post(
            f"/procurement/requisition-items/{item.pk}/purchase-order/",
            {
                "supplier": str(self.supplier.pk),
                "description": item.description,
                "quantity": "5.00",
                "amount": "1800.00",
                "order_date": "2026-07-10",
                "delivery_method": "email",
                "supplier_message": "Please supply the first batch.",
            },
        )
        requisition.refresh_from_db()
        item = RequisitionItem.objects.prefetch_related(
            "purchase_inquiries__purchase_orders"
        ).get(requisition=requisition)
        dashboard_response = self.client.get("/procurement/")
        filtered_dashboard_response = self.client.get(
            "/procurement/?phase=orders&q=drill"
        )
        dated_dashboard_response = self.client.get(
            "/procurement/?phase=complete&date=2026-07-10"
        )
        second_order_response = self.client.post(
            f"/procurement/requisition-items/{item.pk}/purchase-order/",
            {
                "supplier": "",
                "new_supplier_name": "Kasese Tools",
                "new_supplier_contact": "Mary K.",
                "new_supplier_email": "orders@kasese.example",
                "new_supplier_phone": "+256700000001",
                "description": item.description,
                "quantity": "7.00",
                "amount": "2600.00",
                "order_date": "2026-07-10",
                "delivery_method": "whatsapp",
                "supplier_message": "Please supply the remaining batch.",
            },
        )

        requisition.refresh_from_db()
        orders = list(PurchaseOrder.objects.select_related("supplier", "inquiry"))
        self.assertEqual(review_response.status_code, 302)
        self.assertEqual(first_order_response.status_code, 302)
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(filtered_dashboard_response, "Universal procurement search")
        self.assertContains(filtered_dashboard_response, "Search by date")
        self.assertContains(filtered_dashboard_response, "accordion-arrow")
        self.assertContains(filtered_dashboard_response, "Split / Create PO")
        self.assertNotContains(filtered_dashboard_response, "Review / edit")
        self.assertContains(dated_dashboard_response, "2026-07-10")
        self.assertContains(dashboard_response, "7.00 of 12 pieces remaining")
        self.assertEqual(second_order_response.status_code, 302)
        self.assertEqual(len(orders), 2)
        self.assertEqual(
            sum((order.inquiry.quantity for order in orders), Decimal("0")),
            Decimal("12.00"),
        )
        self.assertEqual(requisition.status, Requisition.Status.PURCHASED)
        self.assertEqual(
            {order.supplier.name for order in orders},
            {"Copper Belt Supplies", "Kasese Tools"},
        )
        manual_supplier = Supplier.objects.get(name="Kasese Tools")
        self.assertEqual(manual_supplier.contact_person, "Mary K.")
        self.assertEqual(manual_supplier.email, "orders@kasese.example")
        self.assertEqual(manual_supplier.phone, "+256700000001")
        email_order = next(
            order for order in orders if order.delivery_method == "email"
        )
        whatsapp_order = next(
            order for order in orders if order.delivery_method == "whatsapp"
        )
        email_page = self.client.get(f"/procurement/orders/{email_order.pk}/")
        whatsapp_page = self.client.get(f"/procurement/orders/{whatsapp_order.pk}/")
        download_response = self.client.get(
            f"/procurement/orders/{email_order.pk}/download/"
        )
        print_response = self.client.get(f"/procurement/orders/{email_order.pk}/print/")
        manual_page = self.client.get("/procurement/manual/")
        self.assertContains(email_page, "Send email")
        self.assertContains(whatsapp_page, "Send WhatsApp")
        self.assertContains(email_page, "Print PO")
        self.assertContains(email_page, "Download PO")
        self.assertContains(dashboard_response, "Split / Create PO")
        self.assertContains(email_page, "printable-po-document")
        self.assertContains(email_page, "Plot 12 Mine Road, Kasese")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(print_response.status_code, 200)
        self.assertEqual(download_response["Content-Type"], "application/pdf")
        self.assertEqual(print_response["Content-Type"], "application/pdf")
        self.assertIn(
            f'attachment; filename="{email_order.order_number}.pdf"',
            download_response["Content-Disposition"],
        )
        self.assertIn(
            f'inline; filename="{email_order.order_number}.pdf"',
            print_response["Content-Disposition"],
        )
        self.assertTrue(download_response.content.startswith(b"%PDF"))
        self.assertEqual(download_response.content, print_response.content)
        self.assertIn(
            b"%%EOF",
            download_response.content,
        )
        self.assertContains(
            manual_page, "Reviewed requisition to supplier purchase order"
        )


class TransportCalculationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="transport", password="MiningERP2026!"
        )

    def create_purchase_order(self, requester_username, supplier_name, description):
        requester = get_user_model().objects.create_user(
            username=requester_username, password="MiningERP2026!"
        )
        supplier = Supplier.objects.create(name=supplier_name)
        requisition = Requisition.objects.create(
            requester=requester,
            item_description=f"{description} (1 pcs)",
            language=Requisition.Language.ENGLISH,
            quantity=Decimal("1.00"),
            status=Requisition.Status.PURCHASED,
        )
        inquiry = PurchaseInquiry.objects.create(
            requisition=requisition,
            supplier=supplier,
            description=description,
            quantity=Decimal("1.00"),
            status=PurchaseInquiry.Status.ORDERED,
            sent_at=timezone.now(),
            sent_by=self.user,
        )
        order = PurchaseOrder.objects.create(
            inquiry=inquiry,
            supplier=supplier,
            amount=Decimal("100.00"),
            order_date=timezone.localdate(),
            created_by=self.user,
        )
        return order, requisition

    def test_transport_cost_cbm_and_tax_totals(self):
        record = TransportRecord.objects.create(
            date=timezone.localdate(),
            vehicle="TRK-12",
            driver="Grace N.",
            origin="Supplier Yard",
            destination="Mining Site",
            distance_km=Decimal("250.00"),
            weight_tons=Decimal("10.00"),
            freight=Decimal("100.00"),
            fuel=Decimal("50.00"),
            length=Decimal("2.000"),
            width=Decimal("3.000"),
            height=Decimal("4.000"),
            cbm_quantity=2,
            custom_tax=Decimal("5.00"),
            created_by=self.user,
        )
        TransportGovernmentCharge.objects.create(
            transport=record, name="Port authority", amount=Decimal("10.00")
        )

        self.assertEqual(record.cbm, Decimal("48.000000000"))
        self.assertEqual(record.cost_total, Decimal("150.00"))
        self.assertEqual(record.tax_total, Decimal("15.00"))
        self.assertEqual(record.total_cost, Decimal("165.00"))

    def test_transport_create_accepts_multiple_customers_and_purchase_orders(self):
        first_order, first_requisition = self.create_purchase_order(
            "customer-one", "Copper Belt Supplies", "Crusher liners"
        )
        second_order, second_requisition = self.create_purchase_order(
            "customer-two", "Kasese Industrial", "Drill rods"
        )
        UserModuleAccess.objects.create(
            user=self.user,
            module=UserModuleAccess.Module.TRANSPORT,
            can_create=True,
            can_read=True,
        )
        self.client.login(username="transport", password="MiningERP2026!")

        response = self.client.post(
            "/transport/new/",
            {
                "date": str(timezone.localdate()),
                "vehicle": "TRK-77",
                "driver": "Maria K.",
                "container_number": "",
                "requisition": "",
                "supplier": "",
                "origin": "Border Depot",
                "destination": "Mining Site",
                "distance_km": "250.00",
                "weight_tons": "12.00",
                "freight": "185.00",
                "cbm_quantity": "1",
                "customer_orders-TOTAL_FORMS": "3",
                "customer_orders-INITIAL_FORMS": "0",
                "customer_orders-MIN_NUM_FORMS": "1",
                "customer_orders-MAX_NUM_FORMS": "1000",
                "customer_orders-0-customer_name": "Kasese Minerals",
                "customer_orders-0-purchase_order": str(first_order.pk),
                "customer_orders-0-cargo_description": "Crusher liners and bolts",
                "customer_orders-0-package_type": "crates",
                "customer_orders-0-loading_point": "Border Depot",
                "customer_orders-0-offloading_point": "Mine Store",
                "customer_orders-0-loading_sequence": "1",
                "customer_orders-0-offloading_sequence": "4",
                "customer_orders-0-billable_distance_km": "250.00",
                "customer_orders-0-pieces": "4",
                "customer_orders-0-weight_tons": "6.00",
                "customer_orders-0-length": "2.000",
                "customer_orders-0-width": "1.500",
                "customer_orders-0-height": "1.000",
                "customer_orders-0-cbm_quantity": "4",
                "customer_orders-0-cargo_charge": "120.00",
                "customer_orders-0-handling_charge": "5.00",
                "customer_orders-0-loading_charge": "10.00",
                "customer_orders-1-customer_name": "Kilembe Smelter",
                "customer_orders-1-purchase_order": str(second_order.pk),
                "customer_orders-1-cargo_description": "Drill rods",
                "customer_orders-1-package_type": "bundles",
                "customer_orders-1-loading_point": "Border Depot",
                "customer_orders-1-offloading_point": "Mpondwe Border",
                "customer_orders-1-loading_sequence": "1",
                "customer_orders-1-offloading_sequence": "1",
                "customer_orders-1-billable_distance_km": "100.00",
                "customer_orders-1-pieces": "2",
                "customer_orders-1-weight_tons": "3.50",
                "customer_orders-1-cargo_charge": "80.00",
                "customer_orders-1-offloading_charge": "8.00",
                "customer_orders-1-storage_charge": "2.00",
                "customer_orders-2-customer_name": "",
                "customer_orders-2-purchase_order": "",
                "transit_points-TOTAL_FORMS": "4",
                "transit_points-INITIAL_FORMS": "0",
                "transit_points-MIN_NUM_FORMS": "0",
                "transit_points-MAX_NUM_FORMS": "1000",
                "transit_points-0-point_type": "border",
                "transit_points-0-fee_category": "border_fee",
                "transit_points-0-fee_name": "Entry border clearance",
                "transit_points-0-place_name": "Mpondwe Border",
                "transit_points-0-reference_number": "BRD-001",
                "transit_points-0-sequence": "1",
                "transit_points-0-amount": "42.00",
                "transit_points-0-notes": "Entry border fees",
                "transit_points-1-point_type": "border",
                "transit_points-1-fee_category": "duty",
                "transit_points-1-fee_name": "Exit border duty",
                "transit_points-1-place_name": "Kasumbalesa Border",
                "transit_points-1-reference_number": "BRD-002",
                "transit_points-1-sequence": "2",
                "transit_points-1-amount": "33.00",
                "transit_points-1-notes": "Exit border fees",
                "transit_points-2-point_type": "road_toll",
                "transit_points-2-fee_category": "toll",
                "transit_points-2-fee_name": "Road toll",
                "transit_points-2-place_name": "Katunguru Toll",
                "transit_points-2-reference_number": "TOLL-77",
                "transit_points-2-sequence": "3",
                "transit_points-2-amount": "15.00",
                "transit_points-2-notes": "Road toll",
                "transit_points-3-place_name": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        record = TransportRecord.objects.prefetch_related(
            "customer_orders__purchase_order", "transit_points"
        ).get(vehicle="TRK-77")
        customer_orders = list(record.customer_orders.order_by("id"))
        transit_points = list(record.transit_points.order_by("id"))
        self.assertEqual(len(customer_orders), 2)
        self.assertEqual(len(transit_points), 3)
        self.assertEqual(
            [customer_order.customer_name for customer_order in customer_orders],
            ["Kasese Minerals", "Kilembe Smelter"],
        )
        self.assertEqual(
            customer_orders[0].cargo_description, "Crusher liners and bolts"
        )
        self.assertEqual(customer_orders[0].cargo_cbm, Decimal("12.000000000"))
        self.assertEqual(customer_orders[0].charge_total, Decimal("135.00"))
        self.assertEqual(customer_orders[1].charge_total, Decimal("90.00"))
        self.assertEqual(record.purchase_order, first_order)
        self.assertTrue(record.transit_number.startswith("TRS-"))
        self.assertEqual(
            record.customer_names_summary, "Kasese Minerals, Kilembe Smelter"
        )
        self.assertEqual(
            record.transit_points_summary,
            "Mpondwe Border, Kasumbalesa Border, Katunguru Toll",
        )
        self.assertIn(first_order.order_number, record.purchase_orders_summary)
        self.assertIn(second_order.order_number, record.purchase_orders_summary)
        self.assertEqual(transit_points[0].fee_name, "Entry border clearance")
        self.assertEqual(transit_points[1].fee_category, "duty")
        self.assertEqual(transit_points[2].fee_category, "toll")
        self.assertEqual(transit_points[0].total_amount, Decimal("42.00"))
        self.assertEqual(transit_points[1].total_amount, Decimal("33.00"))
        self.assertEqual(transit_points[2].total_amount, Decimal("15.00"))
        self.assertEqual(record.customer_charge_total, Decimal("225.00"))
        self.assertEqual(record.transit_point_total, Decimal("90.00"))
        self.assertEqual(record.total_cost, Decimal("500.00"))
        invoice_response = self.client.post(
            f"/transport/{record.pk}/invoices/generate/"
        )
        self.assertEqual(invoice_response.status_code, 302)
        invoices = list(
            TransportCustomerInvoice.objects.prefetch_related("lines")
            .filter(transport=record)
            .order_by("customer_name")
        )
        self.assertEqual(len(invoices), 2)
        first_invoice = invoices[0]
        second_invoice = invoices[1]
        self.assertEqual(first_invoice.customer_name, "Kasese Minerals")
        self.assertEqual(second_invoice.customer_name, "Kilembe Smelter")
        self.assertEqual(first_invoice.total_amount, Decimal("359.53"))
        self.assertEqual(second_invoice.total_amount, Decimal("140.47"))
        first_descriptions = [line.description for line in first_invoice.lines.all()]
        second_descriptions = [line.description for line in second_invoice.lines.all()]
        self.assertIn(
            "Shared fleet charges from Border Depot to Mine Store",
            first_descriptions,
        )
        self.assertIn(
            "Shared fleet charges from Border Depot to Mpondwe Border",
            second_descriptions,
        )
        self.assertIn("Exit border duty at Kasumbalesa Border", first_descriptions)
        self.assertNotIn("Exit border duty at Kasumbalesa Border", second_descriptions)
        invoice_list_page = self.client.get("/transport/invoices/")
        invoice_page = self.client.get(f"/transport/invoices/{first_invoice.pk}/")
        invoice_download = self.client.get(
            f"/transport/invoices/{first_invoice.pk}/download/"
        )
        invoice_print = self.client.get(
            f"/transport/invoices/{first_invoice.pk}/print/"
        )
        manual_page = self.client.get("/transport/billing-manual/")
        self.assertContains(invoice_list_page, first_invoice.invoice_number)
        self.assertContains(invoice_list_page, "Customer invoices")
        self.assertContains(invoice_page, first_invoice.invoice_number)
        self.assertContains(invoice_page, "Send WhatsApp")
        self.assertContains(invoice_page, "Download PDF")
        self.assertContains(invoice_page, "Print PDF")
        self.assertEqual(invoice_download.status_code, 200)
        self.assertEqual(invoice_print.status_code, 200)
        self.assertEqual(invoice_download["Content-Type"], "application/pdf")
        self.assertEqual(invoice_print["Content-Type"], "application/pdf")
        self.assertIn(
            f'attachment; filename="{first_invoice.invoice_number}.pdf"',
            invoice_download["Content-Disposition"],
        )
        self.assertIn(
            f'inline; filename="{first_invoice.invoice_number}.pdf"',
            invoice_print["Content-Disposition"],
        )
        self.assertTrue(invoice_download.content.startswith(b"%PDF"))
        self.assertEqual(invoice_download.content, invoice_print.content)
        self.assertContains(manual_page, "Shared vehicle customer billing")
        second_transit = TransportRecord.objects.create(
            date=timezone.localdate(),
            vehicle="TRK-77",
            driver="Maria K.",
            origin="Mining Site",
            destination="Return Yard",
            distance_km=Decimal("250.00"),
            created_by=self.user,
        )
        self.assertTrue(second_transit.transit_number.startswith("TRS-"))
        self.assertNotEqual(record.transit_number, second_transit.transit_number)

        first_order.refresh_from_db()
        second_order.refresh_from_db()
        first_requisition.refresh_from_db()
        second_requisition.refresh_from_db()
        self.assertEqual(first_order.status, PurchaseOrder.Status.LOADED_FOR_TRANSPORT)
        self.assertEqual(second_order.status, PurchaseOrder.Status.LOADED_FOR_TRANSPORT)
        self.assertEqual(first_requisition.status, Requisition.Status.IN_TRANSPORT)
        self.assertEqual(second_requisition.status, Requisition.Status.IN_TRANSPORT)

    def test_transport_delivery_note_creates_business_document(self):
        order, requisition = self.create_purchase_order(
            "delivery-client", "Mine Logistics", "Replacement conveyor"
        )
        record = TransportRecord.objects.create(
            date=timezone.localdate(),
            vehicle="TRK-88",
            driver="Daniel O.",
            requisition=requisition,
            purchase_order=order,
            supplier=order.supplier,
            origin="Supplier Yard",
            destination="Mine Store",
            distance_km=Decimal("120.00"),
            freight=Decimal("250.00"),
            created_by=self.user,
        )
        record.customer_orders.create(
            customer_name="Kasese Minerals",
            purchase_order=order,
            cargo_description="Replacement conveyor",
            loading_point="Supplier Yard",
            offloading_point="Mine Store",
            loading_sequence=1,
            offloading_sequence=1,
            pieces=1,
        )
        for module in [
            UserModuleAccess.Module.TRANSPORT,
            UserModuleAccess.Module.COMMERCIAL_DOCUMENTS,
        ]:
            UserModuleAccess.objects.create(
                user=self.user,
                module=module,
                can_create=True,
                can_read=True,
            )
        self.client.login(username="transport", password="MiningERP2026!")

        page = self.client.get(f"/transport/{record.pk}/")
        create_page = self.client.get(f"/transport/{record.pk}/delivery-note/new/")
        response = self.client.post(
            f"/transport/{record.pk}/delivery-note/new/",
            {
                "document_type": CommercialDocument.DocumentType.DELIVERY_NOTE,
                "status": CommercialDocument.Status.ISSUED,
                "title": "Delivery note for conveyor",
                "client": "",
                "new_client_name": "Kasese Minerals",
                "new_client_contact": "Store Manager",
                "new_client_email": "store@example.com",
                "new_client_phone": "+256700000001",
                "requisition": str(requisition.pk),
                "purchase_order": str(order.pk),
                "transport": str(record.pk),
                "transport_invoice": "",
                "supplier": str(order.supplier.pk),
                "business_reference": record.transit_number,
                "document_date": str(timezone.localdate()),
                "due_date": "",
                "currency": "USD",
                "amount": "0.00",
                "description": "Replacement conveyor delivered",
                "notes": "Signed on arrival",
            },
        )

        self.assertContains(page, "Delivery note")
        self.assertContains(create_page, record.transit_number)
        self.assertEqual(response.status_code, 302)
        document = CommercialDocument.objects.get()
        self.assertEqual(
            document.document_type, CommercialDocument.DocumentType.DELIVERY_NOTE
        )
        self.assertEqual(document.transport, record)
        self.assertEqual(document.purchase_order, order)
        self.assertEqual(document.requisition, requisition)
        self.assertEqual(document.display_client, "Kasese Minerals")
        self.assertTrue(BusinessClient.objects.filter(name="Kasese Minerals").exists())


class BusinessDocumentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="documents", password="MiningERP2026!"
        )
        UserModuleAccess.objects.create(
            user=self.user,
            module=UserModuleAccess.Module.COMMERCIAL_DOCUMENTS,
            can_create=True,
            can_read=True,
        )
        self.client.login(username="documents", password="MiningERP2026!")

    def test_manual_client_document_can_be_created_and_searched(self):
        response = self.client.post(
            "/documents/new/",
            {
                "document_type": CommercialDocument.DocumentType.PROFORMA_INVOICE,
                "status": CommercialDocument.Status.ISSUED,
                "title": "Proforma invoice for drilling services",
                "client": "",
                "new_client_name": "Kilembe Smelter",
                "new_client_contact": "Accounts",
                "new_client_email": "accounts@example.com",
                "new_client_phone": "+256700000002",
                "requisition": "",
                "purchase_order": "",
                "transport": "",
                "transport_invoice": "",
                "supplier": "",
                "business_reference": "JOB-445",
                "document_date": str(timezone.localdate()),
                "due_date": "",
                "currency": "USD",
                "amount": "1500.00",
                "description": "Advance billing",
                "notes": "Pay before dispatch",
            },
        )

        self.assertEqual(response.status_code, 302)
        document = CommercialDocument.objects.get()
        self.assertTrue(document.document_number.startswith("DOC-"))
        self.assertEqual(document.display_client, "Kilembe Smelter")
        self.assertEqual(document.business_reference, "JOB-445")
        list_page = self.client.get("/documents/?q=JOB-445")
        detail_page = self.client.get(f"/documents/{document.pk}/")
        self.assertContains(list_page, document.document_number)
        self.assertContains(detail_page, "Proforma Invoice")
        self.assertContains(detail_page, "Kilembe Smelter")


class FinancialReportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="finance", password="MiningERP2026!"
        )
        UserModuleAccess.objects.create(
            user=self.user,
            module=UserModuleAccess.Module.FINANCIAL_REPORTS,
            can_create=True,
            can_read=True,
        )
        self.client.login(username="finance", password="MiningERP2026!")

    def create_record(self, record_type, amount, description):
        return FinancialRecord.objects.create(
            record_type=record_type,
            record_date=timezone.localdate(),
            description=description,
            amount=Decimal(amount),
            recorded_by=self.user,
        )

    def test_financial_report_summarizes_cash_in_cash_out_and_loss(self):
        self.create_record(
            FinancialRecord.RecordType.CASH_IN, "1000.00", "Customer receipt"
        )
        self.create_record(
            FinancialRecord.RecordType.CASH_OUT, "250.00", "Fuel expense"
        )
        self.create_record(
            FinancialRecord.RecordType.LOSS, "75.00", "Damaged stock loss"
        )

        response = self.client.get("/finance/")

        self.assertContains(response, "Cash movement report")
        self.assertContains(response, "1000.00")
        self.assertContains(response, "325.00")
        self.assertContains(response, "75.00")
        self.assertContains(response, "675.00")

    def test_financial_record_create_records_expense_as_cash_out(self):
        response = self.client.post(
            "/finance/new/",
            {
                "record_type": FinancialRecord.RecordType.CASH_OUT,
                "record_date": str(timezone.localdate()),
                "description": "Road toll expense",
                "reference": "TOLL-88",
                "client": "",
                "supplier": "",
                "document": "",
                "amount": "40.00",
                "currency": "USD",
                "notes": "Paid at checkpoint",
            },
        )

        self.assertEqual(response.status_code, 302)
        record = FinancialRecord.objects.get()
        self.assertTrue(record.record_number.startswith("FIN-"))
        self.assertEqual(record.record_type, FinancialRecord.RecordType.CASH_OUT)
        self.assertEqual(record.cash_out_amount, Decimal("40.00"))
        self.assertEqual(record.cash_in_amount, Decimal("0"))


class FuelManagementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="fuel", password="MiningERP2026!"
        )
        UserModuleAccess.objects.create(
            user=self.user,
            module=UserModuleAccess.Module.FUEL,
            can_create=True,
            can_read=True,
        )
        self.client.login(username="fuel", password="MiningERP2026!")

    def test_fuel_batch_refills_deduct_available_litres(self):
        asset_response = self.client.post(
            "/fuel/assets/new/",
            {
                "name": "Excavator 01",
                "asset_type": "machine",
                "registration_number": "EX-01",
                "mine_line_name": "Line A",
                "engine_capacity": "320HP",
                "expected_consumption_per_hour": "12.500",
                "responsible_person": "Grace Operator",
                "active": "on",
            },
        )
        batch_response = self.client.post(
            "/fuel/batches/new/",
            {
                "fuel_type": "diesel",
                "received_date": "2026-07-10",
                "source_truck": "TRUCK-FUEL-01",
                "storage_method": "drums",
                "container_count": "4",
                "litres_received": "200.000",
                "notes": "Field delivery",
            },
        )
        asset = FuelAsset.objects.get()
        batch = FuelStockBatch.objects.get()
        issue_response = self.client.post(
            "/fuel/issues/new/",
            {
                "batch": str(batch.pk),
                "asset": str(asset.pk),
                "issue_date": "2026-07-10",
                "route_or_location": "Pit route A",
                "driver_operator": "Grace Operator",
                "fuel_before_refill": "0.000",
                "fuel_after_refill": "60.000",
                "litres_issued": "60.000",
                "operating_hours": "4.000",
                "odometer_or_hour_meter": "1410.000",
                "notes": "Morning refill",
            },
        )
        batch.refresh_from_db()
        dashboard_response = self.client.get("/fuel/")

        self.assertEqual(asset_response.status_code, 302)
        self.assertEqual(batch_response.status_code, 302)
        self.assertEqual(issue_response.status_code, 302)
        self.assertEqual(batch.available_litres, Decimal("140.000"))
        self.assertContains(dashboard_response, "140.000")
        self.assertEqual(FuelIssue.objects.get().expected_litres, Decimal("50.000000"))

    def test_fuel_batch_balance_page_shows_received_issued_and_available(self):
        asset = FuelAsset.objects.create(
            name="Water Pump", expected_consumption_per_hour=Decimal("6.000")
        )
        batch = FuelStockBatch.objects.create(
            fuel_type=FuelStockBatch.FuelType.DIESEL,
            received_date=timezone.localdate(),
            source_truck="TRUCK-FUEL-02",
            storage_method=FuelStockBatch.StorageMethod.DRUMS,
            container_count=3,
            litres_received=Decimal("150.000"),
            created_by=self.user,
        )
        FuelIssue.objects.create(
            batch=batch,
            asset=asset,
            issue_date=timezone.localdate(),
            driver_operator="Pump Operator",
            litres_issued=Decimal("45.000"),
            issued_by=self.user,
        )

        response = self.client.get("/fuel/batches/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Batch balances")
        self.assertContains(response, batch.batch_number)
        self.assertContains(response, "TRUCK-FUEL-02")
        self.assertContains(response, "150.000 L")
        self.assertContains(response, "45.000 L")
        self.assertContains(response, "105.000 L")

    def test_refill_cannot_exceed_batch_available_litres(self):
        asset = FuelAsset.objects.create(
            name="Loader", expected_consumption_per_hour=Decimal("5.000")
        )
        batch = FuelStockBatch.objects.create(
            fuel_type=FuelStockBatch.FuelType.DIESEL,
            received_date=timezone.localdate(),
            storage_method=FuelStockBatch.StorageMethod.JERRYCANS,
            container_count=2,
            litres_received=Decimal("20.000"),
            created_by=self.user,
        )
        response = self.client.post(
            "/fuel/issues/new/",
            {
                "batch": str(batch.pk),
                "asset": str(asset.pk),
                "issue_date": "2026-07-10",
                "route_or_location": "Line B",
                "driver_operator": "Loader Operator",
                "fuel_before_refill": "0.000",
                "fuel_after_refill": "30.000",
                "litres_issued": "30.000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only 20.000 litres are available")
        self.assertFalse(FuelIssue.objects.exists())


class VisaManagementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="visas", password="MiningERP2026!"
        )
        UserModuleAccess.objects.create(
            user=self.user,
            module=UserModuleAccess.Module.VISAS,
            can_create=True,
            can_read=True,
        )
        self.client.login(username="visas", password="MiningERP2026!")

    def test_visa_record_shows_expiry_alerts_and_renewal_details(self):
        embassy_response = self.client.post(
            "/visas/embassies/new/",
            {
                "name": "Embassy of Kenya",
                "country": "Kenya",
                "contact_person": "Visa Desk",
                "email": "visa@example.com",
                "phone": "+254700000000",
                "address": "Nairobi",
                "renewal_requirements": "Passport, work permit letter, photos",
                "standard_fee": "250.00",
                "currency": "USD",
                "processing_days": "10",
            },
        )
        expatriate_response = self.client.post(
            "/visas/expatriates/new/",
            {
                "first_name": "Lin",
                "last_name": "Wei",
                "nationality": "Chinese",
                "passport_number": "P1234567",
                "passport_expiry_date": "2027-07-10",
                "job_title": "Mining Engineer",
                "department": "Operations",
                "phone": "+256700000000",
                "email": "lin@example.com",
                "emergency_contact": "Chen Wei",
                "status": "active",
                "notes": "Key site engineer",
            },
        )
        embassy = VisaEmbassy.objects.get()
        expatriate = Expatriate.objects.get()
        expiry_date = timezone.localdate() + timedelta(days=14)
        visa_response = self.client.post(
            "/visas/records/new/",
            {
                "expatriate": str(expatriate.pk),
                "embassy": str(embassy.pk),
                "visa_type": "work",
                "visa_reference": "WORK-2026-01",
                "issue_date": "2026-01-10",
                "expiry_date": str(expiry_date),
                "renewal_status": "preparing",
                "renewal_requirements": "Passport, work permit letter, photos",
                "renewal_fee": "250.00",
                "fee_currency": "USD",
                "reminder_owner": "HR Officer",
                "reminder_email": "hr@example.com",
                "notes": "Start renewal early",
            },
        )
        dashboard_response = self.client.get("/visas/")
        alerts_response = self.client.get("/visas/alerts/")

        self.assertEqual(embassy_response.status_code, 302)
        self.assertEqual(expatriate_response.status_code, 302)
        self.assertEqual(visa_response.status_code, 302)
        self.assertContains(dashboard_response, "Expatriate visa control")
        self.assertContains(dashboard_response, "Lin Wei")
        self.assertContains(dashboard_response, "14 days")
        self.assertContains(dashboard_response, "hr@example.com")
        self.assertContains(dashboard_response, "USD 250.00")
        self.assertContains(alerts_response, "Passport, work permit letter, photos")
        self.assertEqual(ExpatriateVisa.objects.get().expiry_alert, "14 days")

    def test_visa_expiry_date_cannot_precede_issue_date(self):
        embassy = VisaEmbassy.objects.create(name="Embassy", country="Uganda")
        expatriate = Expatriate.objects.create(
            first_name="Amina",
            last_name="Stone",
            nationality="South African",
            passport_number="SA123",
            created_by=self.user,
        )
        response = self.client.post(
            "/visas/records/new/",
            {
                "expatriate": str(expatriate.pk),
                "embassy": str(embassy.pk),
                "visa_type": "work",
                "issue_date": "2026-07-10",
                "expiry_date": "2026-07-01",
                "renewal_status": "not_started",
                "renewal_fee": "0.00",
                "fee_currency": "USD",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Expiry date cannot be before the issue date")
        self.assertFalse(ExpatriateVisa.objects.exists())

    def test_visa_email_reminder_command_sends_due_reminders_once(self):
        embassy = VisaEmbassy.objects.create(
            name="Embassy of Kenya",
            country="Kenya",
            renewal_requirements="Passport, work permit letter, photos",
        )
        expatriate = Expatriate.objects.create(
            first_name="Lin",
            last_name="Wei",
            nationality="Chinese",
            passport_number="P1234567",
            email="lin@example.com",
            created_by=self.user,
        )
        visa = ExpatriateVisa.objects.create(
            expatriate=expatriate,
            embassy=embassy,
            visa_type=ExpatriateVisa.VisaType.WORK,
            issue_date=timezone.localdate() - timedelta(days=120),
            expiry_date=timezone.localdate() + timedelta(days=7),
            renewal_status=ExpatriateVisa.RenewalStatus.PREPARING,
            renewal_fee=Decimal("250.00"),
            fee_currency="USD",
            reminder_owner="HR Officer",
            reminder_email="hr@example.com",
            created_by=self.user,
        )
        output = StringIO()

        call_command("send_visa_renewal_reminders", stdout=output)
        visa.refresh_from_db()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["hr@example.com"])
        self.assertIn("7 days", mail.outbox[0].subject)
        self.assertIn("Passport, work permit letter, photos", mail.outbox[0].body)
        self.assertEqual(visa.last_reminder_stage, "7 days")
        self.assertIn("sent: 1", output.getvalue())

        call_command("send_visa_renewal_reminders")

        self.assertEqual(len(mail.outbox), 1)


# Create your tests here.
