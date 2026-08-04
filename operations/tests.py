from datetime import timedelta
from io import StringIO
from decimal import Decimal

from django.core import mail
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
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
    TransportTransitCost,
    UserModuleAccess,
    VisaEmbassy,
)
from .services import generate_transport_customer_invoices


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

    def test_template_requisition_create_accepts_multiple_items_and_optional_supplier(
        self,
    ):
        self.client.login(username="requester", password="MiningERP2026!")
        response = self.client.post(
            "/requisitions/new/",
            {
                "requesting_company": "Kipushi Mining Center",
                "suggested_supplier_name": "Lubumbashi Industrial Supplies",
                "suggested_supplier_contact": "+243 970 000 111",
                "language": "fr",
                "urgent": "on",
                "items-TOTAL_FORMS": "6",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-description": "Pompe hydraulique",
                "items-0-pieces": "2",
                "items-1-description": "Tuyau haute pression",
                "items-1-pieces": "6",
                "items-2-description": "Courroie convoyeur",
                "items-2-pieces": "4",
                "items-3-description": "Raccords de securite",
                "items-3-pieces": "10",
                "items-4-description": "Filtres hydrauliques",
                "items-4-pieces": "5",
                "items-5-description": "",
                "items-5-pieces": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        requisition = Requisition.objects.prefetch_related("items").get()
        self.assertEqual(
            response.headers["Location"], f"/requisitions/{requisition.pk}/submitted/"
        )
        self.assertTrue(requisition.urgent)
        self.assertEqual(requisition.requesting_company, "Kipushi Mining Center")
        self.assertEqual(
            requisition.suggested_supplier_name, "Lubumbashi Industrial Supplies"
        )
        self.assertEqual(requisition.suggested_supplier_contact, "+243 970 000 111")
        self.assertEqual(requisition.items.count(), 5)
        self.assertEqual(requisition.total_pieces, 27)

    def test_text_entries_are_formatted_on_requisition_submit(self):
        self.client.login(username="requester", password="MiningERP2026!")

        response = self.client.post(
            "/requisitions/new/",
            {
                "requesting_company": "  kipushi mining center  ",
                "suggested_supplier_name": "lubumbashi industrial supplies",
                "suggested_supplier_contact": "+243 970 000 111",
                "language": "en",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-description": "  crusher spare parts  ",
                "items-0-pieces": "4",
            },
        )

        self.assertEqual(response.status_code, 302)
        requisition = Requisition.objects.prefetch_related("items").get()
        self.assertEqual(requisition.requesting_company, "Kipushi mining center")
        self.assertEqual(
            requisition.suggested_supplier_name, "Lubumbashi industrial supplies"
        )
        self.assertEqual(requisition.suggested_supplier_contact, "+243 970 000 111")
        self.assertEqual(requisition.items.first().description, "Crusher spare parts")

    def test_login_page_uses_control_panel_layout(self):
        response = self.client.get("/login/")

        self.assertContains(response, "cpanel-login-body")
        self.assertContains(response, "Control Panel")
        self.assertContains(response, "login-brand-mark")

    def test_requisition_submitted_page_offers_next_actions(self):
        requisition = self.create_requisition()
        self.client.login(username="requester", password="MiningERP2026!")

        response = self.client.get(f"/requisitions/{requisition.pk}/submitted/")

        self.assertContains(response, requisition.requisition_number)
        self.assertContains(response, "Download requisition")
        self.assertContains(response, "Send email")
        self.assertContains(response, "Send WhatsApp")
        self.assertContains(response, "Make another requisition")

    def test_requester_can_download_requisition_copy(self):
        requisition = self.create_requisition()
        self.client.login(username="requester", password="MiningERP2026!")

        response = self.client.get(f"/requisitions/{requisition.pk}/download/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(requisition.requisition_number, response["Content-Disposition"])

    def test_template_requisition_create_accepts_uploaded_document(self):
        self.client.login(username="requester", password="MiningERP2026!")
        upload = SimpleUploadedFile(
            "manual-requisition.txt", b"Manual requisition document"
        )

        response = self.client.post(
            "/requisitions/new/",
            {
                "requesting_company": "Kolwezi Mining Center",
                "uploaded_document": upload,
                "language": "en",
                "items-TOTAL_FORMS": "3",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-description": "",
                "items-0-pieces": "",
                "items-1-description": "",
                "items-1-pieces": "",
                "items-2-description": "",
                "items-2-pieces": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        requisition = Requisition.objects.prefetch_related("items").get()
        self.assertEqual(requisition.requesting_company, "Kolwezi Mining Center")
        self.assertTrue(requisition.uploaded_document.name)
        self.assertEqual(requisition.item_description, "Uploaded requisition document")
        self.assertEqual(requisition.items.count(), 0)

    def test_requester_can_download_uploaded_requisition_document(self):
        requisition = self.create_requisition()
        requisition.uploaded_document.save(
            "manual-requisition.txt",
            SimpleUploadedFile(
                "manual-requisition.txt", b"Manual requisition document"
            ),
        )
        self.client.login(username="requester", password="MiningERP2026!")

        response = self.client.get(f"/requisitions/{requisition.pk}/uploaded-document/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("manual-requisition", response["Content-Disposition"])

    def test_requester_only_sees_requisition_navigation(self):
        self.client.login(username="requester", password="MiningERP2026!")

        dashboard_response = self.client.get("/")
        requisition_response = self.client.get("/requisitions/")
        request_page_response = self.client.get("/requisitions/new/")
        restricted_response = self.client.get("/procurement/")
        content = request_page_response.content.decode()

        self.assertEqual(dashboard_response.status_code, 302)
        self.assertEqual(dashboard_response.headers["Location"], "/requisitions/new/")
        self.assertEqual(requisition_response.status_code, 302)
        self.assertEqual(requisition_response.headers["Location"], "/requisitions/new/")
        self.assertContains(request_page_response, "Requester quick guide")
        self.assertContains(request_page_response, "Request page")
        self.assertNotContains(request_page_response, "Procurement")
        self.assertNotContains(request_page_response, "Transport")
        self.assertNotContains(request_page_response, "Reports")
        self.assertNotContains(request_page_response, "View history")
        self.assertNotIn(">API<", content)
        self.assertEqual(restricted_response.status_code, 302)

    def test_procurement_can_upload_supplier_document_directly_to_requisition(self):
        requisition = self.create_requisition()
        procurement_user = get_user_model().objects.create_user(
            username="procurement", password="MiningERP2026!"
        )
        UserModuleAccess.objects.create(
            user=procurement_user,
            module=UserModuleAccess.Module.PROCUREMENT,
            can_read=True,
        )
        UserModuleAccess.objects.create(
            user=procurement_user,
            module=UserModuleAccess.Module.COMMERCIAL_DOCUMENTS,
            can_create=True,
            can_read=True,
        )
        upload = SimpleUploadedFile("supplier-proforma.txt", b"Proforma invoice")
        self.client.login(username="procurement", password="MiningERP2026!")

        response = self.client.post(
            f"/procurement/requisitions/{requisition.pk}/documents/new/",
            {
                "document_type": CommercialDocument.DocumentType.PROFORMA_INVOICE,
                "title": "Proforma from supplier",
                "new_supplier_name": "Direct Supplier Ltd",
                "new_supplier_contact": "+243 970 222 333",
                "document_date": "2026-01-15",
                "currency": "USD",
                "amount": "1250.00",
                "business_reference": "PF-1001",
                "description": "Supplier proforma before PI or PO",
                "attachment": upload,
            },
        )

        self.assertEqual(response.status_code, 302)
        document = CommercialDocument.objects.get(requisition=requisition)
        self.assertEqual(
            document.document_type, CommercialDocument.DocumentType.PROFORMA_INVOICE
        )
        self.assertEqual(document.supplier.name, "Direct Supplier Ltd")
        self.assertEqual(document.status, CommercialDocument.Status.ISSUED)
        self.assertFalse(
            PurchaseInquiry.objects.filter(requisition=requisition).exists()
        )

        process_response = self.client.get(
            f"/procurement/requisition-process/?q={requisition.requisition_number}"
        )
        self.assertContains(process_response, "Direct requisition documents")
        self.assertContains(process_response, "Proforma from supplier")
        self.assertContains(process_response, "PF-1001")

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


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
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

    def test_transport_steps_save_trip_customers_expenses_and_invoices(self):
        UserModuleAccess.objects.create(
            user=self.user,
            module=UserModuleAccess.Module.TRANSPORT,
            can_create=True,
            can_read=True,
            can_update=True,
        )
        self.client.login(username="transport", password="MiningERP2026!")
        purchase_order, requisition = self.create_purchase_order(
            requester_username="transport-requester",
            supplier_name="Kasese Supplier",
            description="Crusher liners and bolts",
        )

        response = self.client.post(
            "/transport/new/",
            {
                "date": str(timezone.localdate()),
                "vehicle": "TRK-77",
                "driver": "Maria K.",
                "container_number": "",
                "origin": "Border Depot",
                "destination": "Mining Site",
                "distance_km": "400.00",
                "overall_charge": "500.00",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/customers/", response["Location"])
        record = TransportRecord.objects.prefetch_related(
            "customer_orders", "transit_costs", "customer_invoices__lines"
        ).get(vehicle="TRK-77")
        self.assertEqual(record.overall_charge, Decimal("500.00"))
        self.assertEqual(record.customer_orders.count(), 0)
        self.assertEqual(record.transit_costs.count(), 0)
        customer_step_page = self.client.get(f"/transport/{record.pk}/customers/")
        self.assertContains(customer_step_page, "Attach requisition")
        self.assertContains(customer_step_page, "Next: in-transit charges")

        first_customer_response = self.client.post(
            f"/transport/{record.pk}/customers/",
            {
                "customer_name": "Kasese Minerals",
                "requisition": str(requisition.pk),
                "cargo_description": "Crusher liners and bolts",
                "package_type": "Crates",
                "destination": "Mine Store",
                "loading_point": "Border Depot",
                "offloading_point": "Mine Store",
                "pieces": "4",
                "loading_charge": "10.00",
                "offloading_charge": "15.00",
                "cargo_charge": "120.00",
            },
        )
        second_customer_response = self.client.post(
            f"/transport/{record.pk}/customers/",
            {
                "customer_name": "Kilembe Smelter",
                "cargo_description": "Drill rods",
                "package_type": "Bundles",
                "destination": "Mpondwe Border",
                "loading_point": "Border Depot",
                "offloading_point": "Mpondwe Border",
                "pieces": "2",
                "loading_charge": "5.00",
                "offloading_charge": "8.00",
                "cargo_charge": "80.00",
            },
        )
        self.assertEqual(first_customer_response.status_code, 302)
        self.assertEqual(second_customer_response.status_code, 302)

        fuel_response = self.client.post(
            f"/transport/{record.pk}/transit-costs/",
            {
                "cost_type": "fuel",
                "custom_name": "Fuel actual",
                "amount": "42.00",
                "cost_date": str(timezone.localdate()),
                "transit_point": "Mpondwe Border",
                "notes": "Fuel receipt",
            },
        )
        tax_response = self.client.post(
            f"/transport/{record.pk}/transit-costs/",
            {
                "cost_type": "tax",
                "custom_name": "Road tax",
                "amount": "33.00",
                "cost_date": str(timezone.localdate()),
                "transit_point": "Kasumbalesa Border",
                "notes": "Tax receipt",
            },
        )
        self.assertEqual(fuel_response.status_code, 302)
        self.assertEqual(tax_response.status_code, 302)

        record.refresh_from_db()
        customer_orders = list(record.customer_orders.order_by("id"))
        transit_costs = list(record.transit_costs.order_by("id"))
        self.assertEqual(len(customer_orders), 2)
        self.assertEqual(len(transit_costs), 2)
        self.assertEqual(
            [customer_order.customer_name for customer_order in customer_orders],
            ["Kasese Minerals", "Kilembe Smelter"],
        )
        self.assertEqual(
            customer_orders[0].cargo_description, "Crusher liners and bolts"
        )
        self.assertEqual(customer_orders[0].requisition, requisition)
        self.assertEqual(customer_orders[0].cargo_cbm, Decimal("0"))
        self.assertEqual(customer_orders[0].calculated_weight_tons, Decimal("0"))
        self.assertEqual(customer_orders[0].chargeable_units, Decimal("4"))
        self.assertEqual(customer_orders[0].transport_charge, Decimal("120.00"))
        self.assertEqual(customer_orders[0].charge_total, Decimal("120.00"))
        self.assertEqual(customer_orders[1].charge_total, Decimal("80.00"))
        self.assertEqual(record.distance_km, Decimal("400.00"))
        self.assertTrue(record.transit_number.startswith("TRS-"))
        self.assertEqual(
            record.customer_names_summary, "Kasese Minerals, Kilembe Smelter"
        )
        self.assertEqual(transit_costs[0].display_name, "Fuel actual")
        self.assertEqual(
            transit_costs[0].allocation_method,
            TransportTransitCost.AllocationMethod.INTERNAL_ONLY,
        )
        self.assertEqual(transit_costs[1].display_name, "Road tax")
        self.assertEqual(record.customer_charge_total, Decimal("200.00"))
        self.assertEqual(record.transit_cost_total, Decimal("75.00"))
        self.assertEqual(record.overall_charge_balance, Decimal("425.00"))
        expense_step_page = self.client.get(f"/transport/{record.pk}/transit-costs/")
        self.assertContains(expense_step_page, "Save in-transit charge")
        in_transit_response = self.client.post(
            f"/transport/{record.pk}/status/in_transit/"
        )
        self.assertEqual(in_transit_response.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.status, TransportRecord.Status.IN_TRANSIT)
        invoice_response = self.client.post(
            f"/transport/{record.pk}/invoices/generate/"
        )
        self.assertEqual(invoice_response.status_code, 302)
        self.assertIn("/transport/invoices/", invoice_response["Location"])
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
        self.assertEqual(first_invoice.total_amount, Decimal("120.00"))
        self.assertEqual(second_invoice.total_amount, Decimal("80.00"))
        first_descriptions = [line.description for line in first_invoice.lines.all()]
        second_descriptions = [line.description for line in second_invoice.lines.all()]
        self.assertNotIn("Shared fleet charges", " ".join(first_descriptions))
        self.assertEqual(first_descriptions, ["Transit & Logistics Fees"])
        self.assertEqual(second_descriptions, ["Transit & Logistics Fees"])
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
        self.assertContains(invoice_page, "Items / goods")
        self.assertContains(invoice_page, "Type of goods")
        self.assertContains(invoice_page, "Crusher liners and bolts")
        self.assertContains(invoice_page, "Package type")
        self.assertContains(invoice_page, "Crates")
        self.assertContains(invoice_page, "Space used")
        self.assertContains(invoice_page, "4")
        self.assertContains(invoice_page, "Send WhatsApp")
        self.assertContains(invoice_page, "Download PDF")
        self.assertContains(invoice_page, "Print PDF")
        self.assertEqual(invoice_download.status_code, 200)
        self.assertEqual(invoice_print.status_code, 200)
        self.assertEqual(invoice_download["Content-Type"], "application/pdf")
        self.assertEqual(invoice_print["Content-Type"], "application/pdf")
        self.assertIn(
            f'attachment; filename="Transport-Invoice-{first_invoice.invoice_number}.pdf"',
            invoice_download["Content-Disposition"],
        )
        self.assertIn(
            f'inline; filename="Transport-Invoice-{first_invoice.invoice_number}.pdf"',
            invoice_print["Content-Disposition"],
        )
        self.assertTrue(invoice_download.content.startswith(b"%PDF"))
        self.assertEqual(invoice_download.content, invoice_print.content)
        self.assertContains(manual_page, "Simplified transport billing")
        detail_page = self.client.get(f"/transport/{record.pk}/")
        self.assertContains(detail_page, "Customer invoice entries")
        self.assertContains(detail_page, "In-transit charges")
        self.assertContains(detail_page, "GR - Goods Reached")
        self.assertContains(detail_page, "Profit / balance")
        self.assertNotContains(detail_page, "Internal cost breakdown")
        delivered_response = self.client.post(
            f"/transport/{record.pk}/status/delivered/"
        )
        self.assertEqual(delivered_response.status_code, 302)
        delivered_response = self.client.get(delivered_response["Location"])
        self.assertEqual(delivered_response.status_code, 302)
        document = CommercialDocument.objects.get(transport=record)
        self.assertIn(
            f"/transport/{record.pk}/delivery-notes/{document.pk}/",
            delivered_response["Location"],
        )
        delivery_note_page = self.client.get(delivered_response["Location"])
        self.assertContains(delivery_note_page, "Delivery Note")
        self.assertContains(delivery_note_page, "Send WhatsApp")
        record.refresh_from_db()
        self.assertEqual(record.status, TransportRecord.Status.DELIVERED)
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

    def test_transit_costs_track_internal_deductions_and_client_billable_costs(self):
        record = TransportRecord.objects.create(
            date=timezone.localdate(),
            vehicle="TRK-90",
            driver="Sarah K.",
            origin="Depot",
            destination="Mine",
            distance_km=Decimal("300.00"),
            transit_start_km=Decimal("0.00"),
            common_route_end_km=Decimal("100.00"),
            final_destination_km=Decimal("200.00"),
            fuel=Decimal("120.00"),
            driver_allowance=Decimal("80.00"),
            created_by=self.user,
        )
        first = record.customer_orders.create(
            customer_name="Alpha Mine",
            cargo_description="Parts",
            loading_point="Depot",
            offloading_point="Mine A",
            delivery_km=Decimal("200.00"),
            rate_per_km=Decimal("1.00"),
            loading_charge=Decimal("10.00"),
        )
        second = record.customer_orders.create(
            customer_name="Beta Mine",
            cargo_description="Tools",
            loading_point="Depot",
            offloading_point="Mine B",
            delivery_km=Decimal("100.00"),
            rate_per_km=Decimal("1.50"),
        )
        TransportTransitCost.objects.create(
            transport=record,
            cost_type=TransportTransitCost.CostType.FUEL,
            amount=Decimal("90.00"),
            allocation_method=TransportTransitCost.AllocationMethod.INTERNAL_ONLY,
        )
        TransportTransitCost.objects.create(
            transport=record,
            cost_type=TransportTransitCost.CostType.GOVERNMENT_DOCUMENT,
            custom_name="Border document",
            amount=Decimal("60.00"),
            allocation_method=TransportTransitCost.AllocationMethod.DISTANCE_SHARED,
        )
        TransportTransitCost.objects.create(
            transport=record,
            cost_type=TransportTransitCost.CostType.TAX,
            custom_name="Client tax",
            amount=Decimal("25.00"),
            allocation_method=TransportTransitCost.AllocationMethod.CLIENT_SPECIFIC,
            customer_order=second,
        )

        invoices = generate_transport_customer_invoices(record, self.user)

        first_invoice = next(
            invoice for invoice in invoices if invoice.customer_order_id == first.id
        )
        second_invoice = next(
            invoice for invoice in invoices if invoice.customer_order_id == second.id
        )
        self.assertEqual(first.billing_distance_km, Decimal("150.00"))
        self.assertEqual(second.billing_distance_km, Decimal("50.00"))
        self.assertEqual(first_invoice.total_amount, Decimal("150.00"))
        self.assertEqual(second_invoice.total_amount, Decimal("75.00"))
        self.assertEqual(
            first_invoice.status, TransportCustomerInvoice.Status.FINALIZED
        )
        self.assertEqual(second_invoice.get_status_display(), "Issued")
        first_descriptions = [line.description for line in first_invoice.lines.all()]
        second_descriptions = [line.description for line in second_invoice.lines.all()]
        self.assertEqual(first_descriptions, ["Transit & Logistics Fees"])
        self.assertEqual(second_descriptions, ["Transit & Logistics Fees"])
        self.assertEqual(record.transit_cost_total, Decimal("175.00"))
        self.assertEqual(record.internal_deduction_total, Decimal("375.00"))
        self.assertEqual(record.invoice_revenue_total, Decimal("225.00"))
        self.assertEqual(record.remaining_balance, Decimal("-150.00"))

    def test_transport_reports_show_trip_drilldown_and_transit_action_pages(self):
        UserModuleAccess.objects.create(
            user=self.user,
            module=UserModuleAccess.Module.TRANSPORT,
            can_create=True,
            can_read=True,
            can_update=True,
        )
        UserModuleAccess.objects.create(
            user=self.user,
            module=UserModuleAccess.Module.TRANSPORT_REPORTS,
            can_read=True,
        )
        self.client.login(username="transport", password="MiningERP2026!")
        record = TransportRecord.objects.create(
            date=timezone.localdate(),
            vehicle="TRK-100",
            driver="Report Driver",
            origin="Depot",
            destination="Mine",
            distance_km=Decimal("100.00"),
            overall_charge=Decimal("1000000.00"),
            status=TransportRecord.Status.IN_TRANSIT,
            created_by=self.user,
        )
        record.customer_orders.create(
            customer_name="Client One",
            cargo_description="Copper parts",
            cargo_charge=Decimal("500000.00"),
        )
        record.customer_orders.create(
            customer_name="Client Two",
            cargo_description="Mine tools",
            cargo_charge=Decimal("500000.00"),
        )
        TransportTransitCost.objects.create(
            transport=record,
            cost_type=TransportTransitCost.CostType.FUEL,
            custom_name="Fuel and road expenses",
            amount=Decimal("800000.00"),
            allocation_method=TransportTransitCost.AllocationMethod.INTERNAL_ONLY,
        )
        generate_transport_customer_invoices(record, self.user)

        report_page = self.client.get("/transport/reports/")
        detail_page = self.client.get(f"/transport/reports/{record.pk}/")
        in_transit_page = self.client.get("/transport/in-transit/")
        gr_page = self.client.get("/transport/goods-reached/")

        self.assertContains(report_page, "Trip records")
        self.assertContains(report_page, record.transit_number)
        self.assertContains(report_page, "USD 1000000")
        self.assertContains(report_page, "USD 800000")
        self.assertContains(report_page, "USD 200000")
        self.assertContains(detail_page, "Financial summary")
        self.assertContains(detail_page, "Trip charge not matched to customer invoices")
        self.assertContains(detail_page, "Client One")
        self.assertContains(detail_page, "Client Two")
        self.assertContains(detail_page, "USD 500000")
        self.assertContains(detail_page, "Fuel and road expenses")
        self.assertContains(in_transit_page, "Record charge")
        self.assertContains(in_transit_page, record.transit_number)
        self.assertContains(gr_page, "Mark reached and generate delivery note")
        self.assertContains(gr_page, "Client One")

        currency_response = self.client.post(
            "/currency/",
            {"currency": "UGX", "exchange_rate": "4000", "next": "/transport/reports/"},
        )
        self.assertEqual(currency_response.status_code, 302)
        ugx_report_page = self.client.get("/transport/reports/")
        self.assertContains(ugx_report_page, "UGX 4000000000")

    def test_transit_point_costs_are_shared_by_customers_onboard_at_km(self):
        record = TransportRecord.objects.create(
            date=timezone.localdate(),
            vehicle="TRK-91",
            driver="Sarah K.",
            origin="Kampala",
            destination="Final Mine",
            distance_km=Decimal("378.00"),
            transit_start_km=Decimal("0.00"),
            common_route_end_km=Decimal("300.00"),
            final_destination_km=Decimal("378.00"),
            fuel=Decimal("300.00"),
            created_by=self.user,
        )
        first = record.customer_orders.create(
            customer_name="Customer A",
            delivery_km=Decimal("330.00"),
            rate_per_km=Decimal("1.00"),
        )
        second = record.customer_orders.create(
            customer_name="Customer B",
            delivery_km=Decimal("350.00"),
            rate_per_km=Decimal("1.00"),
        )
        third = record.customer_orders.create(
            customer_name="Customer C",
            delivery_km=Decimal("378.00"),
            rate_per_km=Decimal("1.00"),
        )
        record.transit_points.create(
            point_type="road_toll",
            fee_category="toll",
            fee_name="Road toll",
            place_name="Distribution toll",
            km_location=Decimal("340.00"),
            amount=Decimal("60.00"),
        )

        invoices = generate_transport_customer_invoices(record, self.user)

        totals = {
            invoice.customer_order_id: invoice.total_amount for invoice in invoices
        }
        self.assertEqual(totals[first.id], Decimal("130.00"))
        self.assertEqual(totals[second.id], Decimal("150.00"))
        self.assertEqual(totals[third.id], Decimal("178.00"))
        self.assertEqual(record.transit_expense_total, Decimal("360.00"))
        self.assertEqual(record.invoice_revenue_total, Decimal("458.00"))
        self.assertEqual(record.transit_profit, Decimal("98.00"))

    def test_customer_billing_uses_first_branch_off_distance(self):
        record = TransportRecord.objects.create(
            date=timezone.localdate(),
            vehicle="TRK-92",
            driver="Sarah K.",
            origin="Depot",
            destination="Final Mine",
            distance_km=Decimal("400.00"),
            transit_start_km=Decimal("0.00"),
            common_route_end_km=Decimal("240.00"),
            final_destination_km=Decimal("400.00"),
            created_by=self.user,
        )
        martha = record.customer_orders.create(
            customer_name="Martha",
            delivery_km=Decimal("240.00"),
            rate_per_km=Decimal("1.00"),
        )
        peter = record.customer_orders.create(
            customer_name="Peter",
            delivery_km=Decimal("389.00"),
            rate_per_km=Decimal("1.00"),
        )
        kresto = record.customer_orders.create(
            customer_name="Kresto",
            delivery_km=Decimal("400.00"),
            rate_per_km=Decimal("1.00"),
        )

        self.assertEqual(martha.billing_distance_km, Decimal("80.00"))
        self.assertEqual(peter.billing_distance_km, Decimal("229.00"))
        self.assertEqual(kresto.billing_distance_km, Decimal("240.00"))

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
        UserModuleAccess.objects.create(
            user=self.user,
            module=UserModuleAccess.Module.TRANSPORT,
            can_create=True,
            can_read=True,
            can_update=True,
        )
        self.client.login(username="transport", password="MiningERP2026!")

        page = self.client.get(f"/transport/{record.pk}/")
        create_page = self.client.get(f"/transport/{record.pk}/delivery-note/new/")

        self.assertContains(page, "Customer invoice entries")
        self.assertEqual(create_page.status_code, 302)
        document = CommercialDocument.objects.get()
        self.assertEqual(
            document.document_type, CommercialDocument.DocumentType.DELIVERY_NOTE
        )
        self.assertEqual(document.transport, record)
        self.assertEqual(document.purchase_order, order)
        self.assertEqual(document.requisition, requisition)
        self.assertEqual(document.display_client, "Kasese Minerals")
        self.assertIn(
            f"/transport/{record.pk}/delivery-notes/{document.pk}/",
            create_page["Location"],
        )
        note_page = self.client.get(create_page["Location"])
        self.assertContains(note_page, "Delivery Note")
        self.assertContains(note_page, "Send WhatsApp")


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

    def test_refill_litres_are_calculated_from_before_and_after_levels(self):
        asset = FuelAsset.objects.create(
            name="Dozer", expected_consumption_per_hour=Decimal("7.500")
        )
        batch = FuelStockBatch.objects.create(
            fuel_type=FuelStockBatch.FuelType.DIESEL,
            received_date=timezone.localdate(),
            storage_method=FuelStockBatch.StorageMethod.TANK,
            litres_received=Decimal("100.000"),
            created_by=self.user,
        )

        form_page = self.client.get("/fuel/issues/new/")
        response = self.client.post(
            "/fuel/issues/new/",
            {
                "batch": str(batch.pk),
                "asset": str(asset.pk),
                "issue_date": "2026-07-10",
                "driver_operator": "Dozer Operator",
                "fuel_before_refill": "15.000",
                "fuel_after_refill": "65.000",
            },
        )

        issue = FuelIssue.objects.get()
        batch.refresh_from_db()
        self.assertContains(form_page, "data-fuel-litres-issued")
        self.assertContains(form_page, "readonly")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(issue.litres_issued, Decimal("50.000"))
        self.assertEqual(batch.available_litres, Decimal("50.000"))


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
