from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def prefixed_number(prefix):
    return f"{prefix}-{uuid4().hex[:8].upper()}"


def requisition_number():
    return prefixed_number("REQ")


def inquiry_number():
    return prefixed_number("PI")


def purchase_order_number():
    return prefixed_number("PO")


def transport_number():
    return prefixed_number("TRN")


def transit_number():
    return prefixed_number("TRS")


def transport_invoice_number():
    return prefixed_number("TINV")


def commercial_document_number():
    return prefixed_number("DOC")


def financial_record_number():
    return prefixed_number("FIN")


def fuel_batch_number():
    return prefixed_number("FB")


def fuel_issue_number():
    return prefixed_number("FI")


def visa_number():
    return prefixed_number("VISA")


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Supplier(TimeStampedModel):
    name = models.CharField(max_length=160, unique=True)
    contact_person = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=60, blank=True)
    country = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        ordering = ["name"]

    def __str__(self):
        return self.name


class ApplicationSetting(TimeStampedModel):
    class Theme(models.TextChoices):
        MINING_GREEN = "mining-green", "Mining Green"
        COPPER = "copper", "Copper"
        SLATE = "slate", "Slate"

    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        FRENCH = "fr", "French"
        CHINESE = "zh", "Chinese"

    application_name = models.CharField(max_length=120, default="Mining ERP")
    logo = models.ImageField(upload_to="branding/", blank=True)
    address = models.TextField(blank=True)
    theme = models.CharField(
        max_length=32, choices=Theme.choices, default=Theme.MINING_GREEN
    )
    default_language = models.CharField(
        max_length=8, choices=Language.choices, default=Language.ENGLISH
    )
    enable_language_switcher = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Application setting"
        verbose_name_plural = "Application settings"

    def __str__(self):
        return self.application_name

    @classmethod
    def load(cls):
        setting, _created = cls.objects.get_or_create(pk=1)
        return setting


class Requisition(TimeStampedModel):
    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        CHINESE = "zh", "Chinese"
        FRENCH = "fr", "French"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        ACCEPTED = "accepted", "Accepted by Procurement"
        INQUIRIES_SENT = "inquiries_sent", "Purchase Inquiries Sent"
        PURCHASED = "purchased", "Purchased"
        IN_TRANSPORT = "in_transport", "In Transportation"
        DELIVERED = "delivered", "Delivered"

    requisition_number = models.CharField(
        max_length=32,
        unique=True,
        default=requisition_number,
        editable=False,
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requisitions"
    )
    item_description = models.TextField()
    language = models.CharField(
        max_length=2, choices=Language.choices, default=Language.ENGLISH
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    urgent = models.BooleanField(default=False)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.SUBMITTED
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.requisition_number

    @property
    def item_summary(self):
        item_lines = [
            f"{item.description} ({item.pieces} pcs)" for item in self.items.all()
        ]
        if item_lines:
            return "; ".join(item_lines)
        return self.item_description

    @property
    def total_pieces(self):
        pieces = sum((item.pieces for item in self.items.all()), 0)
        if pieces:
            return pieces
        return self.quantity


class RequisitionItem(TimeStampedModel):
    requisition = models.ForeignKey(
        Requisition, on_delete=models.CASCADE, related_name="items"
    )
    description = models.TextField()
    pieces = models.PositiveIntegerField()

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.description} ({self.pieces} pcs)"


class UserModuleAccess(TimeStampedModel):
    class Module(models.TextChoices):
        REQUISITIONS = "requisitions", "Requisitions"
        PROCUREMENT = "procurement", "Procurement Dashboard"
        SUPPLIERS = "suppliers", "Suppliers"
        PURCHASE_INQUIRIES = "purchase_inquiries", "Purchase Inquiries"
        SUPPLIER_INVOICES = "supplier_invoices", "Supplier Invoices"
        PURCHASE_ORDERS = "purchase_orders", "Purchase Orders"
        PURCHASE_RECEIPTS = "purchase_receipts", "Purchase Receipts"
        TRANSPORT = "transport", "Transport"
        TRANSPORT_REPORTS = "transport_reports", "Transport Reports"
        COMMERCIAL_DOCUMENTS = "commercial_documents", "Business Documents"
        FINANCIAL_REPORTS = "financial_reports", "Financial Reports"
        FUEL = "fuel", "Fuel Department"
        VISAS = "visas", "Visa Department"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="module_access"
    )
    module = models.CharField(max_length=40, choices=Module.choices)
    can_create = models.BooleanField(default=False)
    can_read = models.BooleanField(default=False)
    can_update = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)

    class Meta:
        ordering = ["user__username", "module"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "module"], name="unique_user_module_access"
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.get_module_display()}"

    @property
    def enabled_actions(self):
        actions = []
        if self.can_create:
            actions.append("Create")
        if self.can_read:
            actions.append("Read")
        if self.can_update:
            actions.append("Update")
        if self.can_delete:
            actions.append("Delete")
        return ", ".join(actions) if actions else "No access"


class PurchaseInquiry(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent to Supplier"
        INVOICE_LOADED = "invoice_loaded", "Invoice Loaded"
        ORDERED = "ordered", "Purchase Order Created"

    inquiry_number = models.CharField(
        max_length=32,
        unique=True,
        default=inquiry_number,
        editable=False,
    )
    requisition = models.ForeignKey(
        Requisition, on_delete=models.CASCADE, related_name="inquiries"
    )
    requisition_item = models.ForeignKey(
        RequisitionItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_inquiries",
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="purchase_inquiries"
    )
    description = models.TextField()
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.SENT
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_inquiries",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.inquiry_number


class SupplierInvoice(TimeStampedModel):
    inquiry = models.ForeignKey(
        PurchaseInquiry, on_delete=models.CASCADE, related_name="supplier_invoices"
    )
    requisition_number = models.CharField(max_length=32, blank=True, default="")
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_invoices",
    )
    supplier_name = models.CharField(max_length=160, blank=True, default="")
    invoice_number = models.CharField(max_length=80)
    invoice_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    attachment = models.FileField(upload_to="supplier-invoices/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_supplier_invoices",
    )

    class Meta:
        ordering = ["-invoice_date", "-created_at"]

    def __str__(self):
        return self.invoice_number


class PurchaseOrder(TimeStampedModel):
    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        RECEIPT_UPLOADED = "receipt_uploaded", "Receipt Uploaded"
        LOADED_FOR_TRANSPORT = "loaded_for_transport", "Loaded for Transport"

    class DeliveryMethod(models.TextChoices):
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"
        PRINT = "print", "Print"

    order_number = models.CharField(
        max_length=32,
        unique=True,
        default=purchase_order_number,
        editable=False,
    )
    inquiry = models.ForeignKey(
        PurchaseInquiry, on_delete=models.PROTECT, related_name="purchase_orders"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="purchase_orders"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    order_date = models.DateField()
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.ISSUED
    )
    delivery_method = models.CharField(
        max_length=24, choices=DeliveryMethod.choices, default=DeliveryMethod.EMAIL
    )
    supplier_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_purchase_orders",
    )

    class Meta:
        ordering = ["-order_date", "-created_at"]

    def __str__(self):
        return self.order_number


class PurchaseReceipt(TimeStampedModel):
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="receipts"
    )
    receipt_number = models.CharField(max_length=80)
    receipt_date = models.DateField()
    attachment = models.FileField(upload_to="purchase-receipts/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_purchase_receipts",
    )

    class Meta:
        ordering = ["-receipt_date", "-created_at"]

    def __str__(self):
        return self.receipt_number


class BusinessClient(TimeStampedModel):
    name = models.CharField(max_length=160, unique=True)
    contact_person = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=60, blank=True)
    country = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CommercialDocument(TimeStampedModel):
    class DocumentType(models.TextChoices):
        QUOTATION = "quotation", "Quotation"
        PROFORMA_INVOICE = "proforma_invoice", "Proforma Invoice"
        INVOICE = "invoice", "Invoice"
        RECEIPT = "receipt", "Receipt"
        DELIVERY_NOTE = "delivery_note", "Delivery Note"
        CREDIT_NOTE = "credit_note", "Credit Note"
        DEBIT_NOTE = "debit_note", "Debit Note"
        PAYMENT_VOUCHER = "payment_voucher", "Payment Voucher"
        STATEMENT = "statement", "Account Statement"
        WAYBILL = "waybill", "Waybill"
        CONTRACT = "contract", "Contract / Agreement"
        OTHER = "other", "Other Document"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    document_number = models.CharField(
        max_length=32,
        unique=True,
        default=commercial_document_number,
        editable=False,
    )
    document_type = models.CharField(
        max_length=32, choices=DocumentType.choices, default=DocumentType.QUOTATION
    )
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.DRAFT
    )
    title = models.CharField(max_length=180)
    client = models.ForeignKey(
        BusinessClient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    client_name = models.CharField(max_length=160, blank=True)
    client_contact = models.CharField(max_length=120, blank=True)
    client_email = models.EmailField(blank=True)
    client_phone = models.CharField(max_length=60, blank=True)
    requisition = models.ForeignKey(
        Requisition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commercial_documents",
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commercial_documents",
    )
    transport = models.ForeignKey(
        "TransportRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commercial_documents",
    )
    transport_invoice = models.ForeignKey(
        "TransportCustomerInvoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commercial_documents",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commercial_documents",
    )
    business_reference = models.CharField(
        max_length=160,
        blank=True,
        help_text="Manual reference for any other business or external file.",
    )
    document_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=12, default="USD")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="commercial-documents/", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_commercial_documents",
    )

    class Meta:
        ordering = ["-document_date", "-created_at"]

    def __str__(self):
        return self.document_number

    @property
    def display_client(self):
        if self.client:
            return self.client.name
        return self.client_name or "Unassigned client"


class FinancialRecord(TimeStampedModel):
    class RecordType(models.TextChoices):
        CASH_IN = "cash_in", "Cash in"
        CASH_OUT = "cash_out", "Cash out"
        LOSS = "loss", "Loss"

    record_number = models.CharField(
        max_length=32,
        unique=True,
        default=financial_record_number,
        editable=False,
    )
    record_type = models.CharField(max_length=24, choices=RecordType.choices)
    record_date = models.DateField(default=timezone.localdate)
    description = models.CharField(max_length=220)
    reference = models.CharField(max_length=120, blank=True)
    client = models.ForeignKey(
        BusinessClient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_records",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_records",
    )
    document = models.ForeignKey(
        CommercialDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_records",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=12, default="USD")
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="financial_records",
    )

    class Meta:
        ordering = ["-record_date", "-created_at"]

    def __str__(self):
        return self.record_number

    @property
    def cash_in_amount(self):
        return (
            self.amount if self.record_type == self.RecordType.CASH_IN else Decimal("0")
        )

    @property
    def cash_out_amount(self):
        if self.record_type in {self.RecordType.CASH_OUT, self.RecordType.LOSS}:
            return self.amount
        return Decimal("0")


class FuelAsset(TimeStampedModel):
    class AssetType(models.TextChoices):
        MACHINE = "machine", "Machine"
        VEHICLE = "vehicle", "Car / Truck"
        MINE_LINE = "mine_line", "Mine line"
        GENERATOR = "generator", "Generator"
        OTHER = "other", "Other"

    name = models.CharField(max_length=160)
    asset_type = models.CharField(
        max_length=32, choices=AssetType.choices, default=AssetType.MACHINE
    )
    registration_number = models.CharField(max_length=80, blank=True)
    mine_line_name = models.CharField(max_length=160, blank=True)
    engine_capacity = models.CharField(
        max_length=80,
        blank=True,
        help_text="Engine size/capacity, for example 2.5L or 320HP.",
    )
    expected_consumption_per_hour = models.DecimalField(
        max_digits=10, decimal_places=3, default=0, blank=True
    )
    responsible_person = models.CharField(max_length=160, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class FuelStockBatch(TimeStampedModel):
    class FuelType(models.TextChoices):
        DIESEL = "diesel", "Diesel"
        PETROL = "petrol", "Petrol"
        KEROSENE = "kerosene", "Kerosene"
        OTHER = "other", "Other"

    class StorageMethod(models.TextChoices):
        DRUMS = "drums", "Drums"
        JERRYCANS = "jerrycans", "Jerrycans"
        TANK = "tank", "Tank"
        MIXED = "mixed", "Mixed storage"

    batch_number = models.CharField(
        max_length=32, unique=True, default=fuel_batch_number, editable=False
    )
    fuel_type = models.CharField(
        max_length=24, choices=FuelType.choices, default=FuelType.DIESEL
    )
    received_date = models.DateField(default=timezone.localdate)
    source_truck = models.CharField(max_length=120, blank=True)
    storage_method = models.CharField(
        max_length=24, choices=StorageMethod.choices, default=StorageMethod.DRUMS
    )
    container_count = models.PositiveIntegerField(default=0, blank=True)
    litres_received = models.DecimalField(max_digits=14, decimal_places=3)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_fuel_batches",
    )

    class Meta:
        ordering = ["-received_date", "-created_at"]

    def __str__(self):
        return self.batch_number

    @property
    def issued_litres(self):
        return sum((issue.litres_issued for issue in self.issues.all()), Decimal("0"))

    @property
    def available_litres(self):
        return self.litres_received - self.issued_litres


class FuelIssue(TimeStampedModel):
    issue_number = models.CharField(
        max_length=32, unique=True, default=fuel_issue_number, editable=False
    )
    batch = models.ForeignKey(
        FuelStockBatch, on_delete=models.PROTECT, related_name="issues"
    )
    asset = models.ForeignKey(
        FuelAsset, on_delete=models.PROTECT, related_name="fuel_issues"
    )
    issue_date = models.DateField(default=timezone.localdate)
    route_or_location = models.CharField(max_length=180, blank=True)
    driver_operator = models.CharField(max_length=160)
    fuel_before_refill = models.DecimalField(
        max_digits=10, decimal_places=3, default=0, blank=True
    )
    fuel_after_refill = models.DecimalField(
        max_digits=10, decimal_places=3, default=0, blank=True
    )
    litres_issued = models.DecimalField(max_digits=14, decimal_places=3)
    operating_hours = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    odometer_or_hour_meter = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_fuel_records",
    )

    class Meta:
        ordering = ["-issue_date", "-created_at"]

    def __str__(self):
        return self.issue_number

    @property
    def expected_litres(self):
        if self.operating_hours is None:
            return Decimal("0")
        return self.operating_hours * self.asset.expected_consumption_per_hour

    @property
    def variance_litres(self):
        if self.operating_hours is None or not self.asset.expected_consumption_per_hour:
            return Decimal("0")
        return self.litres_issued - self.expected_litres

    def clean(self):
        if not self.batch_id or self.litres_issued is None:
            return
        issued_before = Decimal("0")
        if self.pk:
            issued_before = FuelIssue.objects.get(pk=self.pk).litres_issued
        available = self.batch.available_litres + issued_before
        if self.litres_issued > available:
            raise ValidationError(
                {
                    "litres_issued": f"Only {available} litres are available in this batch."
                }
            )


class VisaEmbassy(TimeStampedModel):
    name = models.CharField(max_length=180)
    country = models.CharField(max_length=100)
    contact_person = models.CharField(max_length=140, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)
    renewal_requirements = models.TextField(
        blank=True,
        help_text="Documents and steps usually needed by this embassy for renewal.",
    )
    standard_fee = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, blank=True
    )
    currency = models.CharField(max_length=12, default="USD")
    processing_days = models.PositiveIntegerField(default=0, blank=True)

    class Meta:
        ordering = ["country", "name"]
        verbose_name_plural = "Visa embassies"

    def __str__(self):
        return f"{self.name} ({self.country})"


class Expatriate(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ON_LEAVE = "on_leave", "On leave"
        EXITED = "exited", "Exited"

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    nationality = models.CharField(max_length=100)
    passport_number = models.CharField(max_length=80, unique=True)
    passport_expiry_date = models.DateField(null=True, blank=True)
    job_title = models.CharField(max_length=140, blank=True)
    department = models.CharField(max_length=140, blank=True)
    phone = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)
    emergency_contact = models.CharField(max_length=180, blank=True)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.ACTIVE
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_expatriates",
    )

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class ExpatriateVisa(TimeStampedModel):
    class VisaType(models.TextChoices):
        WORK = "work", "Work visa"
        RESIDENCE = "residence", "Residence permit"
        BUSINESS = "business", "Business visa"
        VISITOR = "visitor", "Visitor visa"
        OTHER = "other", "Other"

    class RenewalStatus(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        PREPARING = "preparing", "Preparing documents"
        SUBMITTED = "submitted", "Submitted to embassy"
        APPROVED = "approved", "Approved / renewed"
        REJECTED = "rejected", "Rejected"

    record_number = models.CharField(
        max_length=32, unique=True, default=visa_number, editable=False
    )
    expatriate = models.ForeignKey(
        Expatriate, on_delete=models.PROTECT, related_name="visas"
    )
    embassy = models.ForeignKey(
        VisaEmbassy, on_delete=models.PROTECT, related_name="visas"
    )
    visa_type = models.CharField(
        max_length=32, choices=VisaType.choices, default=VisaType.WORK
    )
    visa_reference = models.CharField(max_length=120, blank=True)
    issue_date = models.DateField()
    expiry_date = models.DateField()
    renewal_status = models.CharField(
        max_length=32, choices=RenewalStatus.choices, default=RenewalStatus.NOT_STARTED
    )
    renewal_requirements = models.TextField(blank=True)
    renewal_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fee_currency = models.CharField(max_length=12, default="USD")
    reminder_owner = models.CharField(max_length=140, blank=True)
    reminder_email = models.EmailField(
        blank=True,
        help_text="Email address that receives renewal reminders. Falls back to the expatriate email if blank.",
    )
    last_reminder_stage = models.CharField(max_length=24, blank=True)
    last_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_visa_records",
    )

    class Meta:
        ordering = ["expiry_date", "expatriate__last_name"]

    def __str__(self):
        return self.record_number

    @property
    def days_until_expiry(self):
        return (self.expiry_date - timezone.localdate()).days

    @property
    def expiry_alert(self):
        days = self.days_until_expiry
        if days < 0:
            return "Expired"
        if days <= 3:
            return "3 days"
        if days <= 7:
            return "7 days"
        if days <= 14:
            return "14 days"
        if days <= 30:
            return "30 days"
        return "Valid"

    @property
    def reminder_dates(self):
        return {
            "30 days": self.expiry_date - timedelta(days=30),
            "14 days": self.expiry_date - timedelta(days=14),
            "7 days": self.expiry_date - timedelta(days=7),
            "3 days": self.expiry_date - timedelta(days=3),
        }

    @property
    def reminder_recipient(self):
        return self.reminder_email or self.expatriate.email

    @property
    def email_reminder_stage(self):
        days = self.days_until_expiry
        if days in {30, 14, 7, 3}:
            return f"{days} days"
        if days < 0:
            return "Expired"
        return ""

    @property
    def needs_email_reminder(self):
        stage = self.email_reminder_stage
        return bool(
            stage and self.reminder_recipient and self.last_reminder_stage != stage
        )

    def clean(self):
        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            raise ValidationError(
                {"expiry_date": "Expiry date cannot be before the issue date."}
            )


class TransportRecord(TimeStampedModel):
    transport_number = models.CharField(
        max_length=32,
        unique=True,
        default=transport_number,
        editable=False,
    )
    date = models.DateField()
    vehicle = models.CharField(max_length=80)
    driver = models.CharField(max_length=120)
    container_number = models.CharField(max_length=80, blank=True)
    transit_number = models.CharField(
        max_length=80,
        unique=True,
        default=transit_number,
        editable=False,
    )
    requisition = models.ForeignKey(
        Requisition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transport_records",
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transport_records",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transport_records",
    )
    origin = models.CharField(max_length=160)
    destination = models.CharField(max_length=160)
    distance_km = models.DecimalField(max_digits=12, decimal_places=2)
    weight_tons = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    freight = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    fuel = models.DecimalField(max_digits=14, decimal_places=2, default=0, blank=True)
    driver_allowance = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    road_toll = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    border_charges = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    taxes = models.DecimalField(max_digits=14, decimal_places=2, default=0, blank=True)
    insurance = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    escort_fees = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    handling_charges = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    loading = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    offloading = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    storage = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    demurrage = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    miscellaneous = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    length = models.DecimalField(max_digits=10, decimal_places=3, default=0, blank=True)
    width = models.DecimalField(max_digits=10, decimal_places=3, default=0, blank=True)
    height = models.DecimalField(max_digits=10, decimal_places=3, default=0, blank=True)
    cbm_quantity = models.PositiveIntegerField(default=1)
    custom_tax = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    import_duty = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    vat = models.DecimalField(max_digits=14, decimal_places=2, default=0, blank=True)
    excise_duty = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    other_government_charges = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_transport_records",
    )

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return self.transport_number

    @property
    def cbm(self):
        return self.length * self.width * self.height * Decimal(self.cbm_quantity)

    @property
    def cost_total(self):
        fields = [
            self.freight,
            self.fuel,
            self.driver_allowance,
            self.road_toll,
            self.border_charges,
            self.taxes,
            self.insurance,
            self.escort_fees,
            self.handling_charges,
            self.loading,
            self.offloading,
            self.storage,
            self.demurrage,
            self.miscellaneous,
        ]
        return sum(fields, Decimal("0"))

    @property
    def tax_total(self):
        fields = [
            self.custom_tax,
            self.import_duty,
            self.vat,
            self.excise_duty,
            self.other_government_charges,
        ]
        return sum(fields, Decimal("0")) + self.custom_government_charges_total

    @property
    def custom_government_charges_total(self):
        return sum(
            (charge.amount for charge in self.custom_government_charges.all()),
            Decimal("0"),
        )

    @property
    def customer_charge_total(self):
        return sum(
            (
                customer_order.charge_total
                for customer_order in self.customer_orders.all()
            ),
            Decimal("0"),
        )

    @property
    def transit_point_total(self):
        return sum(
            (transit_point.total_amount for transit_point in self.transit_points.all()),
            Decimal("0"),
        )

    @property
    def total_cost(self):
        return (
            self.cost_total
            + self.tax_total
            + self.customer_charge_total
            + self.transit_point_total
        )

    @property
    def average_cost_per_ton(self):
        if not self.weight_tons:
            return None
        return self.total_cost / self.weight_tons

    @property
    def average_cost_per_cbm(self):
        if not self.cbm:
            return None
        return self.total_cost / self.cbm

    @property
    def customer_names_summary(self):
        names = [
            customer_order.customer_name
            for customer_order in self.customer_orders.all()
            if customer_order.customer_name
        ]
        return ", ".join(dict.fromkeys(names))

    @property
    def purchase_orders_summary(self):
        order_numbers = [
            customer_order.purchase_order.order_number
            for customer_order in self.customer_orders.all()
            if customer_order.purchase_order_id
        ]
        if not order_numbers and self.purchase_order_id:
            order_numbers = [self.purchase_order.order_number]
        return ", ".join(dict.fromkeys(order_numbers))

    @property
    def supplier_names_summary(self):
        supplier_names = [
            customer_order.purchase_order.supplier.name
            for customer_order in self.customer_orders.all()
            if customer_order.purchase_order_id
        ]
        if not supplier_names and self.supplier_id:
            supplier_names = [self.supplier.name]
        return ", ".join(dict.fromkeys(supplier_names))

    @property
    def transit_points_summary(self):
        places = [
            transit_point.place_name
            for transit_point in self.transit_points.all()
            if transit_point.place_name
        ]
        return ", ".join(dict.fromkeys(places))


class TransportCustomerOrder(TimeStampedModel):
    transport = models.ForeignKey(
        TransportRecord,
        on_delete=models.CASCADE,
        related_name="customer_orders",
    )
    customer_name = models.CharField(max_length=160, blank=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_transport_orders",
    )
    cargo_description = models.TextField(blank=True)
    package_type = models.CharField(max_length=80, blank=True)
    loading_point = models.CharField(max_length=160, blank=True)
    offloading_point = models.CharField(max_length=160, blank=True)
    loading_sequence = models.PositiveIntegerField(null=True, blank=True)
    offloading_sequence = models.PositiveIntegerField(null=True, blank=True)
    billable_distance_km = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, blank=True
    )
    pieces = models.PositiveIntegerField(default=0, blank=True)
    weight_tons = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, blank=True
    )
    length = models.DecimalField(max_digits=10, decimal_places=3, default=0, blank=True)
    width = models.DecimalField(max_digits=10, decimal_places=3, default=0, blank=True)
    height = models.DecimalField(max_digits=10, decimal_places=3, default=0, blank=True)
    cbm_quantity = models.PositiveIntegerField(default=1, blank=True)
    cargo_charge = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    handling_charge = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    loading_charge = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    offloading_charge = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    storage_charge = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    miscellaneous_charge = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        if self.customer_name and self.purchase_order_id:
            return f"{self.customer_name} - {self.purchase_order}"
        return self.customer_name or str(self.purchase_order)

    @property
    def cargo_cbm(self):
        return self.length * self.width * self.height * Decimal(self.cbm_quantity)

    @property
    def charge_total(self):
        fields = [
            self.cargo_charge,
            self.handling_charge,
            self.loading_charge,
            self.offloading_charge,
            self.storage_charge,
            self.miscellaneous_charge,
        ]
        return sum(fields, Decimal("0"))

    @property
    def chargeable_units(self):
        if self.weight_tons:
            return self.weight_tons
        cargo_cbm = self.cargo_cbm
        if cargo_cbm:
            return cargo_cbm
        if self.pieces:
            return Decimal(self.pieces)
        return Decimal("1")

    @property
    def billing_distance_km(self):
        if self.billable_distance_km:
            return self.billable_distance_km
        return self.transport.distance_km or Decimal("0")


class TransportTransitPoint(TimeStampedModel):
    class PointType(models.TextChoices):
        BORDER = "border", "Border"
        ROAD_TOLL = "road_toll", "Road Toll"
        TAX_CHECKPOINT = "tax_checkpoint", "Tax Checkpoint"
        CUSTOMS = "customs", "Customs"
        WEIGHBRIDGE = "weighbridge", "Weighbridge"
        CHECKPOINT = "checkpoint", "Checkpoint"
        OTHER = "other", "Other"

    class FeeCategory(models.TextChoices):
        FEE = "fee", "Fee"
        BORDER_FEE = "border_fee", "Border Fee"
        TOLL = "toll", "Toll"
        TAX = "tax", "Tax"
        DUTY = "duty", "Duty"
        PERMIT = "permit", "Permit"
        OTHER = "other", "Other"

    transport = models.ForeignKey(
        TransportRecord,
        on_delete=models.CASCADE,
        related_name="transit_points",
    )
    point_type = models.CharField(
        max_length=32, choices=PointType.choices, default=PointType.BORDER
    )
    fee_category = models.CharField(
        max_length=32, choices=FeeCategory.choices, default=FeeCategory.FEE
    )
    fee_name = models.CharField(max_length=120, blank=True)
    place_name = models.CharField(max_length=160)
    reference_number = models.CharField(max_length=80, blank=True)
    sequence = models.PositiveIntegerField(null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, blank=True)
    charge_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    tax_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, blank=True
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        fee_name = self.fee_name or self.get_fee_category_display()
        return f"{self.place_name} - {fee_name}"

    @property
    def total_amount(self):
        if self.amount:
            return self.amount
        return self.charge_amount + self.tax_amount


class TransportCustomerInvoice(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        FINALIZED = "finalized", "Finalized"

    invoice_number = models.CharField(
        max_length=32,
        unique=True,
        default=transport_invoice_number,
        editable=False,
    )
    transport = models.ForeignKey(
        TransportRecord,
        on_delete=models.CASCADE,
        related_name="customer_invoices",
    )
    customer_order = models.ForeignKey(
        TransportCustomerOrder,
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    customer_name = models.CharField(max_length=160)
    invoice_date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.DRAFT
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_transport_customer_invoices",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-invoice_date", "invoice_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["transport", "customer_order"],
                name="unique_transport_customer_invoice",
            )
        ]

    def __str__(self):
        return self.invoice_number

    @property
    def total_amount(self):
        return sum((line.amount for line in self.lines.all()), Decimal("0"))


class TransportCustomerInvoiceLine(TimeStampedModel):
    class LineType(models.TextChoices):
        DIRECT = "direct", "Direct Customer Charge"
        SHARED = "shared", "Shared Fleet Charge"
        TRANSIT = "transit", "Transit/Government Fee"
        ADJUSTMENT = "adjustment", "Adjustment"

    invoice = models.ForeignKey(
        TransportCustomerInvoice,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    line_type = models.CharField(max_length=24, choices=LineType.choices)
    description = models.CharField(max_length=240)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.description} - {self.amount}"


class TransportGovernmentCharge(TimeStampedModel):
    transport = models.ForeignKey(
        TransportRecord,
        on_delete=models.CASCADE,
        related_name="custom_government_charges",
    )
    name = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} - {self.amount}"


class TransportAttachment(TimeStampedModel):
    class DocumentType(models.TextChoices):
        DELIVERY_NOTE = "delivery_note", "Delivery Note"
        INVOICE = "invoice", "Invoice"
        WAYBILL = "waybill", "Waybill"
        BILL_OF_LADING = "bill_of_lading", "Bill of Lading"
        CUSTOMS_DECLARATION = "customs_declaration", "Customs Declaration"
        TRANSIT_PERMIT = "transit_permit", "Transit Permit"
        PROOF_OF_DELIVERY = "proof_of_delivery", "Proof of Delivery"

    transport = models.ForeignKey(
        TransportRecord, on_delete=models.CASCADE, related_name="attachments"
    )
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    file = models.FileField(upload_to="transport-attachments/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_transport_attachments",
    )

    class Meta:
        ordering = ["document_type", "-created_at"]

    def __str__(self):
        return self.get_document_type_display()
