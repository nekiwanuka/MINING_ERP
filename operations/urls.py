from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .api import (
    PurchaseInquiryViewSet,
    PurchaseOrderViewSet,
    PurchaseReceiptViewSet,
    RequisitionViewSet,
    SupplierInvoiceViewSet,
    SupplierViewSet,
    TransportAttachmentViewSet,
    TransportGovernmentChargeViewSet,
    TransportRecordViewSet,
)

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("requisitions", RequisitionViewSet, basename="requisition")
router.register(
    "purchase-inquiries", PurchaseInquiryViewSet, basename="purchase-inquiry"
)
router.register(
    "supplier-invoices", SupplierInvoiceViewSet, basename="supplier-invoice"
)
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register(
    "purchase-receipts", PurchaseReceiptViewSet, basename="purchase-receipt"
)
router.register(
    "transport-records", TransportRecordViewSet, basename="transport-record"
)
router.register(
    "transport-government-charges",
    TransportGovernmentChargeViewSet,
    basename="transport-government-charge",
)
router.register(
    "transport-attachments", TransportAttachmentViewSet, basename="transport-attachment"
)

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("language/", views.language_change, name="language_change"),
    path("requisitions/", views.requisition_list, name="requisition_list"),
    path("requisitions/new/", views.requisition_create, name="requisition_create"),
    path(
        "requisitions/<int:pk>/edit/", views.requisition_edit, name="requisition_edit"
    ),
    path("procurement/", views.procurement_dashboard, name="procurement_dashboard"),
    path(
        "procurement/requisition-process/",
        views.requisition_process_list,
        name="requisition_process_list",
    ),
    path(
        "procurement/manual/",
        views.procurement_workflow_manual,
        name="procurement_workflow_manual",
    ),
    path("procurement/suppliers/new/", views.supplier_create, name="supplier_create"),
    path(
        "procurement/requisitions/<int:pk>/review/",
        views.procurement_requisition_review,
        name="procurement_requisition_review",
    ),
    path(
        "procurement/requisitions/<int:pk>/accept/",
        views.requisition_accept,
        name="requisition_accept",
    ),
    path(
        "procurement/requisitions/<int:requisition_id>/inquiries/new/",
        views.inquiry_create,
        name="inquiry_create",
    ),
    path(
        "procurement/requisition-items/<int:item_id>/inquiries/new/",
        views.item_inquiry_create,
        name="item_inquiry_create",
    ),
    path(
        "procurement/requisition-items/<int:item_id>/purchase-order/",
        views.item_purchase_order_create,
        name="item_purchase_order_create",
    ),
    path(
        "procurement/inquiries/<int:inquiry_id>/invoice/",
        views.supplier_invoice_upload,
        name="supplier_invoice_upload",
    ),
    path(
        "procurement/inquiries/<int:inquiry_id>/purchase-order/",
        views.purchase_order_create,
        name="purchase_order_create",
    ),
    path(
        "procurement/orders/<int:order_id>/",
        views.purchase_order_detail,
        name="purchase_order_detail",
    ),
    path(
        "procurement/orders/<int:order_id>/download/",
        views.purchase_order_download,
        name="purchase_order_download",
    ),
    path(
        "procurement/orders/<int:order_id>/print/",
        views.purchase_order_print,
        name="purchase_order_print",
    ),
    path(
        "procurement/orders/<int:order_id>/receipt/",
        views.purchase_receipt_upload,
        name="purchase_receipt_upload",
    ),
    path("transport/", views.transport_list, name="transport_list"),
    path("transport/new/", views.transport_create, name="transport_create"),
    path(
        "transport/billing-manual/",
        views.transport_billing_manual,
        name="transport_billing_manual",
    ),
    path("transport/<int:pk>/", views.transport_detail, name="transport_detail"),
    path(
        "transport/<int:pk>/invoices/generate/",
        views.transport_invoices_generate,
        name="transport_invoices_generate",
    ),
    path(
        "transport/<int:pk>/delivery-note/new/",
        views.transport_delivery_note_create,
        name="transport_delivery_note_create",
    ),
    path(
        "transport/invoices/",
        views.transport_invoice_list,
        name="transport_invoice_list",
    ),
    path(
        "transport/invoices/<int:invoice_id>/",
        views.transport_invoice_detail,
        name="transport_invoice_detail",
    ),
    path(
        "transport/invoices/<int:invoice_id>/download/",
        views.transport_invoice_download,
        name="transport_invoice_download",
    ),
    path(
        "transport/invoices/<int:invoice_id>/print/",
        views.transport_invoice_print,
        name="transport_invoice_print",
    ),
    path(
        "transport/<int:pk>/attachments/",
        views.transport_attachment_add,
        name="transport_attachment_add",
    ),
    path(
        "transport/<int:pk>/government-charges/",
        views.transport_charge_add,
        name="transport_charge_add",
    ),
    path("transport/reports/", views.transport_reports, name="transport_reports"),
    path("documents/", views.commercial_document_list, name="commercial_document_list"),
    path(
        "documents/new/",
        views.commercial_document_create,
        name="commercial_document_create",
    ),
    path(
        "documents/<int:pk>/",
        views.commercial_document_detail,
        name="commercial_document_detail",
    ),
    path(
        "documents/clients/new/",
        views.business_client_create,
        name="business_client_create",
    ),
    path("finance/", views.financial_report, name="financial_report"),
    path("finance/new/", views.financial_record_create, name="financial_record_create"),
    path("fuel/", views.fuel_dashboard, name="fuel_dashboard"),
    path("fuel/batches/", views.fuel_batch_balance, name="fuel_batch_balance"),
    path("fuel/assets/new/", views.fuel_asset_create, name="fuel_asset_create"),
    path("fuel/batches/new/", views.fuel_batch_create, name="fuel_batch_create"),
    path("fuel/issues/new/", views.fuel_issue_create, name="fuel_issue_create"),
    path("visas/", views.visa_dashboard, name="visa_dashboard"),
    path("visas/alerts/", views.visa_alerts, name="visa_alerts"),
    path("visas/embassies/new/", views.visa_embassy_create, name="visa_embassy_create"),
    path("visas/expatriates/new/", views.expatriate_create, name="expatriate_create"),
    path(
        "visas/records/new/",
        views.expatriate_visa_create,
        name="expatriate_visa_create",
    ),
    path("access/users/", views.user_access_list, name="user_access_list"),
    path("access/users/new/", views.user_access_create, name="user_access_create"),
    path(
        "access/users/<int:user_id>/", views.user_access_edit, name="user_access_edit"
    ),
    path("setup/application/", views.application_setup, name="application_setup"),
    path("api/", include(router.urls)),
]
