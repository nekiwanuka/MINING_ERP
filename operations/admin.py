from django.contrib import admin

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
    PurchaseReceipt,
    Requisition,
    RequisitionItem,
    Supplier,
    SupplierInvoice,
    TransportAttachment,
    TransportCustomerInvoice,
    TransportCustomerInvoiceLine,
    TransportCustomerOrder,
    TransportGovernmentCharge,
    TransportRecord,
    TransportTransitCost,
    TransportTransitPoint,
    UserModuleAccess,
    VisaEmbassy,
)


class TransportGovernmentChargeInline(admin.TabularInline):
    model = TransportGovernmentCharge
    extra = 1


class TransportAttachmentInline(admin.TabularInline):
    model = TransportAttachment
    extra = 1


class TransportCustomerOrderInline(admin.TabularInline):
    model = TransportCustomerOrder
    extra = 1


class TransportTransitPointInline(admin.TabularInline):
    model = TransportTransitPoint
    extra = 1


class TransportTransitCostInline(admin.TabularInline):
    model = TransportTransitCost
    extra = 1


class TransportCustomerInvoiceLineInline(admin.TabularInline):
    model = TransportCustomerInvoiceLine
    extra = 0
    readonly_fields = ("line_type", "description", "amount", "sort_order")
    can_delete = False


class RequisitionItemInline(admin.TabularInline):
    model = RequisitionItem
    extra = 1


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "email", "phone")
    search_fields = ("name", "country", "email", "phone")


@admin.register(ApplicationSetting)
class ApplicationSettingAdmin(admin.ModelAdmin):
    list_display = (
        "application_name",
        "theme",
        "default_language",
        "enable_language_switcher",
    )


@admin.register(Requisition)
class RequisitionAdmin(admin.ModelAdmin):
    list_display = (
        "requisition_number",
        "requesting_company",
        "uploaded_document",
        "requester",
        "language",
        "urgent",
        "quantity",
        "status",
        "created_at",
    )
    list_filter = ("language", "urgent", "status", "created_at")
    search_fields = (
        "requisition_number",
        "requesting_company",
        "item_description",
        "items__description",
        "requester__username",
    )
    inlines = [RequisitionItemInline]


@admin.register(PurchaseInquiry)
class PurchaseInquiryAdmin(admin.ModelAdmin):
    list_display = (
        "inquiry_number",
        "requisition",
        "supplier",
        "quantity",
        "status",
        "created_at",
    )
    list_filter = ("status", "supplier")
    search_fields = (
        "inquiry_number",
        "requisition__requisition_number",
        "supplier__name",
    )


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "requisition_number",
        "supplier_name",
        "inquiry",
        "amount",
        "invoice_date",
    )
    search_fields = (
        "invoice_number",
        "requisition_number",
        "supplier_name",
        "inquiry__inquiry_number",
    )


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "inquiry",
        "supplier",
        "amount",
        "delivery_method",
        "status",
        "order_date",
    )
    list_filter = ("status", "delivery_method", "supplier")
    search_fields = ("order_number", "inquiry__inquiry_number", "supplier__name")


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "purchase_order", "receipt_date")
    search_fields = ("receipt_number", "purchase_order__order_number")


@admin.register(BusinessClient)
class BusinessClientAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "email", "phone")
    search_fields = ("name", "country", "email", "phone")


@admin.register(CommercialDocument)
class CommercialDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "document_number",
        "document_type",
        "display_client",
        "status",
        "document_date",
        "amount",
    )
    list_filter = ("document_type", "status", "document_date")
    search_fields = (
        "document_number",
        "title",
        "client__name",
        "client_name",
        "business_reference",
        "transport__transit_number",
        "purchase_order__order_number",
        "requisition__requisition_number",
    )


@admin.register(FinancialRecord)
class FinancialRecordAdmin(admin.ModelAdmin):
    list_display = (
        "record_number",
        "record_type",
        "record_date",
        "description",
        "amount",
        "currency",
    )
    list_filter = ("record_type", "record_date", "currency")
    search_fields = (
        "record_number",
        "description",
        "reference",
        "client__name",
        "supplier__name",
    )


@admin.register(FuelAsset)
class FuelAssetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "asset_type",
        "registration_number",
        "mine_line_name",
        "expected_consumption_per_hour",
        "responsible_person",
        "active",
    )
    list_filter = ("asset_type", "active")
    search_fields = (
        "name",
        "registration_number",
        "mine_line_name",
        "responsible_person",
    )


@admin.register(FuelStockBatch)
class FuelStockBatchAdmin(admin.ModelAdmin):
    list_display = (
        "batch_number",
        "fuel_type",
        "received_date",
        "storage_method",
        "container_count",
        "litres_received",
        "available_litres",
    )
    list_filter = ("fuel_type", "storage_method", "received_date")
    search_fields = ("batch_number", "source_truck", "notes")


@admin.register(FuelIssue)
class FuelIssueAdmin(admin.ModelAdmin):
    list_display = (
        "issue_number",
        "batch",
        "asset",
        "issue_date",
        "driver_operator",
        "litres_issued",
        "route_or_location",
    )
    list_filter = ("issue_date", "batch__fuel_type", "asset__asset_type")
    search_fields = (
        "issue_number",
        "batch__batch_number",
        "asset__name",
        "driver_operator",
        "route_or_location",
    )


@admin.register(VisaEmbassy)
class VisaEmbassyAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "email", "phone", "standard_fee", "currency")
    list_filter = ("country", "currency")
    search_fields = ("name", "country", "email", "phone", "renewal_requirements")


@admin.register(Expatriate)
class ExpatriateAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "nationality",
        "passport_number",
        "passport_expiry_date",
        "job_title",
        "department",
        "status",
    )
    list_filter = ("nationality", "department", "status")
    search_fields = ("first_name", "last_name", "passport_number", "nationality")


@admin.register(ExpatriateVisa)
class ExpatriateVisaAdmin(admin.ModelAdmin):
    list_display = (
        "record_number",
        "expatriate",
        "visa_type",
        "embassy",
        "expiry_date",
        "expiry_alert",
        "renewal_status",
    )
    list_filter = ("visa_type", "renewal_status", "embassy__country", "expiry_date")
    search_fields = (
        "record_number",
        "visa_reference",
        "expatriate__first_name",
        "expatriate__last_name",
        "expatriate__passport_number",
        "embassy__name",
    )


@admin.register(TransportRecord)
class TransportRecordAdmin(admin.ModelAdmin):
    list_display = (
        "transport_number",
        "date",
        "vehicle",
        "driver",
        "transit_number",
        "origin",
        "destination",
    )
    list_filter = ("date", "supplier", "destination")
    search_fields = (
        "transport_number",
        "transit_number",
        "vehicle",
        "driver",
        "customer_orders__customer_name",
        "customer_orders__purchase_order__order_number",
        "transit_points__fee_name",
        "transit_points__place_name",
        "origin",
        "destination",
    )
    inlines = [
        TransportCustomerOrderInline,
        TransportTransitPointInline,
        TransportTransitCostInline,
        TransportGovernmentChargeInline,
        TransportAttachmentInline,
    ]


@admin.register(TransportCustomerInvoice)
class TransportCustomerInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "customer_name",
        "transport",
        "invoice_date",
        "status",
    )
    list_filter = ("status", "invoice_date")
    search_fields = (
        "invoice_number",
        "customer_name",
        "transport__transit_number",
        "transport__transport_number",
    )
    inlines = [TransportCustomerInvoiceLineInline]


@admin.register(UserModuleAccess)
class UserModuleAccessAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "module",
        "can_create",
        "can_read",
        "can_update",
        "can_delete",
    )
    list_filter = ("module", "can_create", "can_read", "can_update", "can_delete")
    search_fields = ("user__username", "user__email")
