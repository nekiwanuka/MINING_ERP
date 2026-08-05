from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.forms import formset_factory, inlineformset_factory
from PIL import Image, UnidentifiedImageError
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

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
    TransportCustomerOrder,
    TransportTransitCost,
    TransportGovernmentCharge,
    TransportRecord,
    TransportTransitPoint,
    UserModuleAccess,
    VisaEmbassy,
)

DATE_WIDGET = forms.DateInput(attrs={"type": "date"})
MONEY_WIDGET = forms.NumberInput(attrs={"step": "0.01", "min": "0"})
WHOLE_MONEY_WIDGET = forms.NumberInput(attrs={"step": "1", "min": "0"})
MEASURE_WIDGET = forms.NumberInput(attrs={"step": "0.001", "min": "0"})
PDF_UPLOAD_ACCEPT = "application/pdf,image/*,text/plain"

TEXT_FORMAT_EXCLUDED_NAMES = {
    "username",
    "password",
    "email",
    "client_email",
    "new_client_email",
    "new_supplier_email",
    "language",
    "currency",
    "status",
    "document_type",
    "record_type",
    "delivery_method",
    "module",
}

TEXT_FORMAT_EXCLUDED_PARTS = [
    "email",
    "phone",
    "number",
    "reference",
    "code",
    "url",
    "file",
    "attachment",
]


def should_format_text_entry(field_name, field):
    if field_name in TEXT_FORMAT_EXCLUDED_NAMES:
        return False
    if any(part in field_name for part in TEXT_FORMAT_EXCLUDED_PARTS):
        return False
    return isinstance(field, forms.CharField) and not isinstance(
        field, forms.EmailField
    )


def capitalize_first_letter(value):
    if not isinstance(value, str):
        return value
    value = value.strip()
    for index, character in enumerate(value):
        if character.isalpha():
            return f"{value[:index]}{character.upper()}{value[index + 1:]}"
    return value


def format_text_entry(value, preserve_lines=False):
    if not isinstance(value, str):
        return value
    if preserve_lines:
        lines = [" ".join(line.split()) for line in value.splitlines()]
        return "\n".join(capitalize_first_letter(line) for line in lines if line)
    return capitalize_first_letter(" ".join(value.split()))


def field_entry_tip(field_name, field):
    label = field.label or field_name.replace("_", " ").title()
    if field.help_text:
        return str(field.help_text)
    if "amount" in field_name or "charge" in field_name or "fee" in field_name:
        return f"Enter the amount for {label.lower()}."
    if isinstance(field, forms.DecimalField) and not any(
        word in field_name
        for word in ["km", "distance", "weight", "length", "width", "height", "cbm"]
    ):
        return f"Enter the amount for {label.lower()}."
    if isinstance(field.widget, forms.Select):
        return f"Select the correct {label.lower()}."
    if isinstance(field.widget, forms.CheckboxInput):
        return f"Tick this box if {label.lower()} applies."
    if isinstance(field.widget, forms.FileInput):
        return f"Upload the file for {label.lower()}."
    if isinstance(field.widget, forms.DateInput):
        return f"Enter the {label.lower()} using the calendar or YYYY-MM-DD format."
    if isinstance(field.widget, forms.TimeInput):
        return f"Enter the {label.lower()} using HH:MM format."
    if isinstance(field.widget, forms.NumberInput):
        return f"Enter the number for {label.lower()}."
    if isinstance(field.widget, forms.Textarea):
        return f"Enter the details for {label.lower()}."
    return f"Enter the {label.lower()}."


def pdf_upload_name(original_name):
    stem = Path(original_name or "uploaded-document").stem or "uploaded-document"
    clean_stem = "-".join(stem.strip().split()) or "uploaded-document"
    return f"{clean_stem}.pdf"


def upload_to_pdf(upload):
    if not isinstance(upload, UploadedFile):
        return upload

    content_type = (upload.content_type or "").lower()
    suffix = Path(upload.name or "").suffix.lower()
    if content_type == "application/pdf" or suffix == ".pdf":
        upload.name = pdf_upload_name(upload.name)
        return upload

    upload.seek(0)
    data = upload.read()
    upload.seek(0)
    output = BytesIO()
    pdf_name = pdf_upload_name(upload.name)

    if content_type.startswith("image/") or suffix in {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
    }:
        try:
            image = Image.open(BytesIO(data))
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.save(output, format="PDF", resolution=120.0)
        except UnidentifiedImageError as exc:
            raise ValidationError(
                "Upload a readable PDF, photo/image, or plain text file."
            ) from exc
        return ContentFile(output.getvalue(), name=pdf_name)

    if content_type.startswith("text/") or suffix in {".txt", ".csv"}:
        text = data.decode("utf-8", errors="replace")
        document = SimpleDocTemplate(output, pagesize=A4, title=pdf_name)
        styles = getSampleStyleSheet()
        story = []
        for line in text.splitlines() or [""]:
            story.append(Paragraph(escape(line) or "&nbsp;", styles["BodyText"]))
            story.append(Spacer(1, 6))
        document.build(story)
        return ContentFile(output.getvalue(), name=pdf_name)

    raise ValidationError(
        "Upload a PDF, photo/image, or plain text file. Export Word or Excel files to PDF before uploading."
    )


def convert_file_fields_to_pdf(form, cleaned_data):
    for field_name, field in form.fields.items():
        if not isinstance(field, forms.FileField) or isinstance(
            field, forms.ImageField
        ):
            continue
        upload = cleaned_data.get(field_name)
        if not upload:
            continue
        try:
            cleaned_data[field_name] = upload_to_pdf(upload)
        except ValidationError as exc:
            form.add_error(field_name, exc)
    return cleaned_data


def style_form_fields(fields):
    for field_name, field in fields.items():
        css_class = field.widget.attrs.get("class", "")
        if isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs["class"] = f"{css_class} checkbox-control".strip()
        else:
            field.widget.attrs["class"] = f"{css_class} field-control".strip()

        tip = field_entry_tip(field_name, field)
        if not field.help_text:
            field.help_text = tip
        if isinstance(field, forms.FileField) and not isinstance(
            field, forms.ImageField
        ):
            field.help_text = f"{field.help_text} PDFs, photos, images, and text files are saved as PDF."
            field.widget.attrs.setdefault("accept", PDF_UPLOAD_ACCEPT)
            field.widget.attrs.setdefault("capture", "environment")
        field.widget.attrs.setdefault("title", tip)
        field.widget.attrs.setdefault("aria-label", field.label or "Field")
        if should_format_text_entry(field_name, field):
            field.widget.attrs.setdefault(
                "autocapitalize",
                "sentences" if isinstance(field.widget, forms.Textarea) else "words",
            )


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_form_fields(self.fields)

    def clean(self):
        cleaned_data = super().clean()
        for field_name, field in self.fields.items():
            if field_name in cleaned_data and should_format_text_entry(
                field_name, field
            ):
                cleaned_data[field_name] = format_text_entry(
                    cleaned_data[field_name], isinstance(field.widget, forms.Textarea)
                )
        return convert_file_fields_to_pdf(self, cleaned_data)


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_form_fields(self.fields)

    def clean(self):
        cleaned_data = super().clean()
        for field_name, field in self.fields.items():
            if field_name in cleaned_data and should_format_text_entry(
                field_name, field
            ):
                cleaned_data[field_name] = format_text_entry(
                    cleaned_data[field_name], isinstance(field.widget, forms.Textarea)
                )
        return convert_file_fields_to_pdf(self, cleaned_data)


class ManagedUserForm(StyledModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Required for new users. Leave blank when editing to keep the current password.",
    )

    class Meta:
        model = get_user_model()
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "password",
            "is_active",
            "is_staff",
        ]
        labels = {
            "is_active": "Active account",
            "is_staff": "Can open Django admin",
        }

    def __init__(self, *args, require_password=False, **kwargs):
        self.require_password = require_password
        super().__init__(*args, **kwargs)
        if require_password:
            self.fields["password"].required = True

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user


class ApplicationSettingForm(StyledModelForm):
    class Meta:
        model = ApplicationSetting
        fields = [
            "application_name",
            "logo",
            "address",
            "theme",
            "default_language",
            "enable_language_switcher",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class ModuleAccessForm(forms.Form):
    module = forms.ChoiceField(
        choices=UserModuleAccess.Module.choices, widget=forms.HiddenInput
    )
    can_create = forms.BooleanField(required=False)
    can_read = forms.BooleanField(required=False)
    can_update = forms.BooleanField(required=False)
    can_delete = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_form_fields(self.fields)


ModuleAccessFormSet = formset_factory(ModuleAccessForm, extra=0)


class RequisitionForm(StyledModelForm):
    class Meta:
        model = Requisition
        fields = [
            "requesting_company",
            "suggested_supplier_name",
            "suggested_supplier_contact",
            "uploaded_document",
            "language",
            "urgent",
        ]
        labels = {
            "requesting_company": "Mining company / site",
            "suggested_supplier_name": "Supplier name (optional)",
            "suggested_supplier_contact": "Supplier contact (optional)",
            "uploaded_document": "Upload prepared requisition",
            "language": "Description language",
            "urgent": "Urgent requisition",
        }
        help_texts = {
            "requesting_company": "Use the requester company or mining center name. If the username is the company name, this is filled automatically.",
            "suggested_supplier_name": "Optional. Enter the supplier you recommend for this requisition.",
            "suggested_supplier_contact": "Optional. Enter the supplier phone, email, or contact person if known.",
            "uploaded_document": "Optional. Upload a prepared requisition instead of entering item lines below.",
        }


class RequisitionItemForm(StyledModelForm):
    class Meta:
        model = RequisitionItem
        fields = ["description", "pieces"]
        labels = {"description": "Item description", "pieces": "Number of pieces"}
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "English, Chinese, or French item details",
                }
            ),
            "pieces": forms.NumberInput(attrs={"min": "1", "step": "1"}),
        }


RequisitionItemFormSet = inlineformset_factory(
    Requisition,
    RequisitionItem,
    form=RequisitionItemForm,
    fields=("description", "pieces"),
    extra=1,
    min_num=0,
    validate_min=False,
    can_delete=False,
)


class SupplierForm(StyledModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "email", "phone", "country", "address"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class PurchaseInquiryForm(StyledModelForm):
    class Meta:
        model = PurchaseInquiry
        fields = ["supplier", "description", "quantity"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
        }


class SupplierInvoiceForm(StyledModelForm):
    requisition_number = forms.CharField(
        label="Requisition number",
        required=False,
        disabled=True,
    )
    new_supplier_name = forms.CharField(
        label="Or enter supplier name",
        required=False,
        help_text="Use this when the supplier is not registered yet.",
    )

    def __init__(self, *args, inquiry=None, **kwargs):
        self.inquiry = inquiry
        super().__init__(*args, **kwargs)
        self.fields["supplier"].required = False
        self.fields["supplier"].queryset = Supplier.objects.all()
        if inquiry:
            self.fields["requisition_number"].initial = (
                inquiry.requisition.requisition_number
            )
            self.fields["supplier"].initial = inquiry.supplier

    class Meta:
        model = SupplierInvoice
        fields = [
            "requisition_number",
            "supplier",
            "new_supplier_name",
            "invoice_number",
            "invoice_date",
            "amount",
            "attachment",
        ]
        widgets = {
            "invoice_date": DATE_WIDGET,
            "amount": MONEY_WIDGET,
        }

    def resolve_supplier(self):
        new_supplier_name = self.cleaned_data.get("new_supplier_name", "").strip()
        if new_supplier_name:
            supplier, _created = Supplier.objects.get_or_create(name=new_supplier_name)
            return supplier
        return self.cleaned_data.get("supplier") or self.inquiry.supplier


class PurchaseOrderForm(StyledModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["amount", "order_date"]
        widgets = {
            "amount": MONEY_WIDGET,
            "order_date": DATE_WIDGET,
        }


class DirectPurchaseOrderForm(StyledForm):
    fieldsets = [
        {
            "title": "Supplier",
            "helper": "Choose an existing supplier or create a new supplier contact for this order.",
            "fields": (
                "supplier",
                "new_supplier_name",
                "new_supplier_contact",
                "new_supplier_email",
                "new_supplier_phone",
            ),
        },
        {
            "title": "Order details",
            "helper": "Enter the item, quantity, amount, delivery method, and supplier message.",
            "fields": (
                "description",
                "quantity",
                "amount",
                "order_date",
                "delivery_method",
                "supplier_message",
            ),
        },
    ]

    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.all(),
        required=False,
        label="Existing supplier",
    )
    new_supplier_name = forms.CharField(
        required=False,
        label="Or enter new supplier name",
    )
    new_supplier_contact = forms.CharField(required=False, label="New supplier contact")
    new_supplier_email = forms.EmailField(required=False, label="New supplier email")
    new_supplier_phone = forms.CharField(required=False, label="New supplier phone")
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        label="Quantity to order now / split quantity",
    )
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.00"), widget=MONEY_WIDGET
    )
    order_date = forms.DateField(widget=DATE_WIDGET)
    delivery_method = forms.ChoiceField(choices=PurchaseOrder.DeliveryMethod.choices)
    supplier_message = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 4})
    )

    def __init__(self, *args, max_quantity=None, **kwargs):
        self.max_quantity = Decimal(max_quantity or 0)
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.all()
        if self.max_quantity:
            self.fields["quantity"].help_text = (
                f"Remaining quantity: {self.max_quantity}"
            )

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if self.max_quantity and quantity > self.max_quantity:
            raise forms.ValidationError(
                f"Quantity cannot exceed remaining quantity {self.max_quantity}."
            )
        return quantity

    def clean(self):
        cleaned_data = super().clean()
        supplier = cleaned_data.get("supplier")
        new_supplier_name = cleaned_data.get("new_supplier_name", "").strip()
        if not supplier and not new_supplier_name:
            raise forms.ValidationError(
                "Choose an existing supplier or enter a new supplier name."
            )
        return cleaned_data

    def resolve_supplier(self):
        new_supplier_name = self.cleaned_data.get("new_supplier_name", "").strip()
        if new_supplier_name:
            supplier, _created = Supplier.objects.get_or_create(name=new_supplier_name)
            update_fields = []
            field_map = {
                "contact_person": self.cleaned_data.get(
                    "new_supplier_contact", ""
                ).strip(),
                "email": self.cleaned_data.get("new_supplier_email", "").strip(),
                "phone": self.cleaned_data.get("new_supplier_phone", "").strip(),
            }
            for field_name, value in field_map.items():
                if value and getattr(supplier, field_name) != value:
                    setattr(supplier, field_name, value)
                    update_fields.append(field_name)
            if update_fields:
                supplier.save(update_fields=[*update_fields, "updated_at"])
            return supplier
        return self.cleaned_data["supplier"]


class PurchaseReceiptForm(StyledModelForm):
    class Meta:
        model = PurchaseReceipt
        fields = ["receipt_number", "receipt_date", "attachment"]
        widgets = {"receipt_date": DATE_WIDGET}


class BusinessClientForm(StyledModelForm):
    class Meta:
        model = BusinessClient
        fields = ["name", "contact_person", "email", "phone", "country", "address"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class CommercialDocumentForm(StyledModelForm):
    fieldsets = [
        {
            "title": "Document",
            "helper": "Classify the document and give it a clear title for search and reporting.",
            "fields": ("document_type", "status", "title", "business_reference"),
        },
        {
            "title": "Client and links",
            "helper": "Connect this file to a client and any related requisition, order, trip, invoice, or supplier.",
            "fields": (
                "client",
                "new_client_name",
                "new_client_contact",
                "new_client_email",
                "new_client_phone",
                "requisition",
                "purchase_order",
                "transport",
                "transport_invoice",
                "supplier",
            ),
        },
        {
            "title": "Values and file",
            "helper": "Add dates, amount, notes, and the original attachment.",
            "fields": (
                "document_date",
                "due_date",
                "currency",
                "amount",
                "description",
                "notes",
                "attachment",
            ),
        },
    ]

    new_client_name = forms.CharField(
        required=False,
        label="Or enter client / customer name",
        help_text="Use this when the client is not registered yet.",
    )
    new_client_contact = forms.CharField(required=False, label="New client contact")
    new_client_email = forms.EmailField(required=False, label="New client email")
    new_client_phone = forms.CharField(required=False, label="New client phone")

    class Meta:
        model = CommercialDocument
        fields = [
            "document_type",
            "status",
            "title",
            "client",
            "new_client_name",
            "new_client_contact",
            "new_client_email",
            "new_client_phone",
            "requisition",
            "purchase_order",
            "transport",
            "transport_invoice",
            "supplier",
            "business_reference",
            "document_date",
            "due_date",
            "currency",
            "amount",
            "description",
            "notes",
            "attachment",
        ]
        widgets = {
            "document_date": DATE_WIDGET,
            "due_date": DATE_WIDGET,
            "amount": MONEY_WIDGET,
            "description": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].required = False
        self.fields["client"].queryset = BusinessClient.objects.all()

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get("client")
        new_client_name = cleaned_data.get("new_client_name", "").strip()
        if not client and not new_client_name:
            self.add_error("new_client_name", "Select a client or enter one manually.")
        return cleaned_data

    def resolve_client(self):
        new_client_name = self.cleaned_data.get("new_client_name", "").strip()
        if new_client_name:
            client, _created = BusinessClient.objects.get_or_create(
                name=new_client_name
            )
            update_fields = []
            field_map = {
                "contact_person": self.cleaned_data.get(
                    "new_client_contact", ""
                ).strip(),
                "email": self.cleaned_data.get("new_client_email", "").strip(),
                "phone": self.cleaned_data.get("new_client_phone", "").strip(),
            }
            for field_name, value in field_map.items():
                if value and getattr(client, field_name) != value:
                    setattr(client, field_name, value)
                    update_fields.append(field_name)
            if update_fields:
                client.save(update_fields=[*update_fields, "updated_at"])
            return client
        return self.cleaned_data.get("client")


class RequisitionDocumentUploadForm(StyledModelForm):
    fieldsets = [
        {
            "title": "Supplier",
            "helper": "Select the supplier or enter a new supplier name for this document.",
            "fields": ("supplier", "new_supplier_name", "new_supplier_contact"),
        },
        {
            "title": "Document details",
            "helper": "Capture the reference, dates, amount, description, and file attachment.",
            "fields": (
                "document_type",
                "title",
                "document_date",
                "due_date",
                "currency",
                "amount",
                "business_reference",
                "description",
                "notes",
                "attachment",
            ),
        },
    ]

    new_supplier_name = forms.CharField(
        required=False,
        label="Or enter supplier name",
        help_text="Use this when the supplier is not registered yet.",
    )
    new_supplier_contact = forms.CharField(required=False, label="Supplier contact")

    class Meta:
        model = CommercialDocument
        fields = [
            "document_type",
            "title",
            "supplier",
            "new_supplier_name",
            "new_supplier_contact",
            "document_date",
            "due_date",
            "currency",
            "amount",
            "business_reference",
            "description",
            "notes",
            "attachment",
        ]
        labels = {
            "title": "Document title / number",
            "business_reference": "Supplier reference / invoice number",
            "attachment": "Upload document file",
        }
        widgets = {
            "document_date": DATE_WIDGET,
            "due_date": DATE_WIDGET,
            "amount": MONEY_WIDGET,
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].required = False
        self.fields["supplier"].queryset = Supplier.objects.all()

    def clean(self):
        cleaned_data = super().clean()
        supplier = cleaned_data.get("supplier")
        new_supplier_name = cleaned_data.get("new_supplier_name", "").strip()
        if not supplier and not new_supplier_name:
            self.add_error(
                "new_supplier_name", "Select a supplier or enter one manually."
            )
        return cleaned_data

    def resolve_supplier(self):
        new_supplier_name = self.cleaned_data.get("new_supplier_name", "").strip()
        if new_supplier_name:
            supplier, _created = Supplier.objects.get_or_create(name=new_supplier_name)
            contact = self.cleaned_data.get("new_supplier_contact", "").strip()
            if contact and supplier.contact_person != contact:
                supplier.contact_person = contact
                supplier.save(update_fields=["contact_person", "updated_at"])
            return supplier
        return self.cleaned_data.get("supplier")


class FinancialRecordForm(StyledModelForm):
    fieldsets = [
        {
            "title": "Record summary",
            "helper": "Define the transaction type, date, description, and reference.",
            "fields": ("record_type", "record_date", "description", "reference"),
        },
        {
            "title": "Parties and amount",
            "helper": "Link the client, supplier, document, amount, currency, and notes.",
            "fields": ("client", "supplier", "document", "amount", "currency", "notes"),
        },
    ]

    class Meta:
        model = FinancialRecord
        fields = [
            "record_type",
            "record_date",
            "description",
            "reference",
            "client",
            "supplier",
            "document",
            "amount",
            "currency",
            "notes",
        ]
        labels = {
            "record_type": "Record type",
            "record_date": "Date",
            "document": "Linked business document",
        }
        widgets = {
            "record_date": DATE_WIDGET,
            "amount": MONEY_WIDGET,
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class FuelAssetForm(StyledModelForm):
    class Meta:
        model = FuelAsset
        fields = [
            "name",
            "asset_type",
            "registration_number",
            "mine_line_name",
            "engine_capacity",
            "expected_consumption_per_hour",
            "responsible_person",
            "active",
        ]
        labels = {
            "name": "Fleet / machine name",
            "expected_consumption_per_hour": "Expected litres per hour",
        }
        widgets = {"expected_consumption_per_hour": MEASURE_WIDGET}


class FuelStockBatchForm(StyledModelForm):
    class Meta:
        model = FuelStockBatch
        fields = [
            "fuel_type",
            "received_date",
            "source_truck",
            "storage_method",
            "container_count",
            "litres_received",
            "notes",
        ]
        labels = {
            "source_truck": "Truck / delivery reference",
            "container_count": "Number of drums / jerrycans / tanks",
            "litres_received": "Total litres received on site",
        }
        widgets = {
            "received_date": DATE_WIDGET,
            "litres_received": MEASURE_WIDGET,
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class FuelIssueForm(StyledModelForm):
    fieldsets = [
        {
            "title": "Issue target",
            "helper": "Choose the fuel stock, asset, date, route, and responsible operator.",
            "fields": (
                "batch",
                "asset",
                "issue_date",
                "route_or_location",
                "driver_operator",
            ),
        },
        {
            "title": "Usage readings",
            "helper": "Enter refill readings and operating measurements for consumption tracking.",
            "fields": (
                "fuel_before_refill",
                "fuel_after_refill",
                "litres_issued",
                "operating_hours",
                "odometer_or_hour_meter",
                "notes",
            ),
        },
    ]

    class Meta:
        model = FuelIssue
        fields = [
            "batch",
            "asset",
            "issue_date",
            "route_or_location",
            "driver_operator",
            "fuel_before_refill",
            "fuel_after_refill",
            "litres_issued",
            "operating_hours",
            "odometer_or_hour_meter",
            "notes",
        ]
        labels = {
            "batch": "Fuel batch to deduct from",
            "asset": "Fleet / machine / mine line",
            "route_or_location": "Route, mine line, or field location",
            "driver_operator": "Responsible driver / operator",
            "fuel_before_refill": "Fuel before refilling",
            "fuel_after_refill": "Fuel after refilling",
            "litres_issued": "Litres refilled now",
            "operating_hours": "Hours worked for this refill",
            "odometer_or_hour_meter": "Odometer / hour meter reading",
        }
        widgets = {
            "issue_date": DATE_WIDGET,
            "fuel_before_refill": MEASURE_WIDGET,
            "fuel_after_refill": MEASURE_WIDGET,
            "litres_issued": MEASURE_WIDGET,
            "operating_hours": MEASURE_WIDGET,
            "odometer_or_hour_meter": MEASURE_WIDGET,
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = FuelAsset.objects.filter(active=True)
        self.fields["batch"].queryset = FuelStockBatch.objects.prefetch_related(
            "issues"
        )
        self.fields["fuel_before_refill"].widget.attrs[
            "data-fuel-before-refill"
        ] = "true"
        self.fields["fuel_after_refill"].widget.attrs["data-fuel-after-refill"] = "true"
        self.fields["litres_issued"].required = False
        self.fields["litres_issued"].help_text = (
            "Auto calculated as fuel after refilling minus fuel before refilling."
        )
        self.fields["litres_issued"].widget.attrs.update(
            {
                "data-fuel-litres-issued": "true",
                "readonly": "readonly",
            }
        )

    def clean(self):
        cleaned_data = super().clean()
        batch = cleaned_data.get("batch")
        fuel_before_refill = cleaned_data.get("fuel_before_refill")
        fuel_after_refill = cleaned_data.get("fuel_after_refill")
        litres_issued = cleaned_data.get("litres_issued")
        if fuel_before_refill is not None and fuel_after_refill is not None:
            if fuel_after_refill < fuel_before_refill:
                self.add_error(
                    "fuel_after_refill",
                    "Fuel after refilling cannot be less than fuel before refilling.",
                )
            else:
                litres_issued = fuel_after_refill - fuel_before_refill
                cleaned_data["litres_issued"] = litres_issued
        if litres_issued is None:
            self.add_error(
                "litres_issued",
                "Enter fuel before and after refilling to calculate litres refilled now.",
            )
        if batch and litres_issued and litres_issued > batch.available_litres:
            self.add_error(
                "litres_issued",
                f"Only {batch.available_litres} litres are available in this batch.",
            )
        return cleaned_data


class VisaEmbassyForm(StyledModelForm):
    fieldsets = [
        {
            "title": "Embassy contact",
            "helper": "Record contact details and address for visa follow-up.",
            "fields": (
                "name",
                "country",
                "contact_person",
                "email",
                "phone",
                "address",
            ),
        },
        {
            "title": "Processing rules",
            "helper": "Capture renewal requirements, standard fee, currency, and processing days.",
            "fields": (
                "renewal_requirements",
                "standard_fee",
                "currency",
                "processing_days",
            ),
        },
    ]

    class Meta:
        model = VisaEmbassy
        fields = [
            "name",
            "country",
            "contact_person",
            "email",
            "phone",
            "address",
            "renewal_requirements",
            "standard_fee",
            "currency",
            "processing_days",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "renewal_requirements": forms.Textarea(attrs={"rows": 4}),
            "standard_fee": MONEY_WIDGET,
        }


class ExpatriateForm(StyledModelForm):
    fieldsets = [
        {
            "title": "Identity",
            "helper": "Capture passport identity and nationality details.",
            "fields": (
                "first_name",
                "last_name",
                "nationality",
                "passport_number",
                "passport_expiry_date",
            ),
        },
        {
            "title": "Work and contact",
            "helper": "Add job details, contact information, emergency contact, status, and notes.",
            "fields": (
                "job_title",
                "department",
                "phone",
                "email",
                "emergency_contact",
                "status",
                "notes",
            ),
        },
    ]

    class Meta:
        model = Expatriate
        fields = [
            "first_name",
            "last_name",
            "nationality",
            "passport_number",
            "passport_expiry_date",
            "job_title",
            "department",
            "phone",
            "email",
            "emergency_contact",
            "status",
            "notes",
        ]
        labels = {"passport_expiry_date": "Passport expiry date"}
        widgets = {
            "passport_expiry_date": DATE_WIDGET,
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class ExpatriateVisaForm(StyledModelForm):
    fieldsets = [
        {
            "title": "Visa identity",
            "helper": "Choose the expatriate, embassy, visa type, reference, and validity dates.",
            "fields": (
                "expatriate",
                "embassy",
                "visa_type",
                "visa_reference",
                "issue_date",
                "expiry_date",
            ),
        },
        {
            "title": "Renewal tracking",
            "helper": "Record renewal status, requirements, fee, reminder owner, email, and notes.",
            "fields": (
                "renewal_status",
                "renewal_requirements",
                "renewal_fee",
                "fee_currency",
                "reminder_owner",
                "reminder_email",
                "notes",
            ),
        },
    ]

    class Meta:
        model = ExpatriateVisa
        fields = [
            "expatriate",
            "embassy",
            "visa_type",
            "visa_reference",
            "issue_date",
            "expiry_date",
            "renewal_status",
            "renewal_requirements",
            "renewal_fee",
            "fee_currency",
            "reminder_owner",
            "reminder_email",
            "notes",
        ]
        labels = {
            "visa_reference": "Visa / permit reference",
            "renewal_requirements": "Renewal requirements for this visa",
            "renewal_fee": "Renewal fee",
            "reminder_owner": "Responsible reminder owner",
            "reminder_email": "Reminder email address",
        }
        widgets = {
            "issue_date": DATE_WIDGET,
            "expiry_date": DATE_WIDGET,
            "renewal_requirements": forms.Textarea(attrs={"rows": 4}),
            "renewal_fee": MONEY_WIDGET,
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class TransportRecordForm(StyledModelForm):
    fieldsets = [
        {
            "title": "Trip route",
            "helper": "Set the date, truck, crew, container, origin, and destination.",
            "fields": (
                "date",
                "vehicle",
                "driver",
                "turn_boy",
                "container_number",
                "origin",
                "destination",
            ),
        },
        {
            "title": "Trip value",
            "helper": "Enter distance and total trip charge before adding customers and expenses.",
            "fields": ("distance_km", "overall_charge"),
        },
    ]

    OPTIONAL_DECIMAL_FIELDS = [
        "transit_start_km",
        "common_route_end_km",
        "final_destination_km",
        "overall_charge",
        "freight",
        "fuel",
        "driver_allowance",
        "turn_boy_allowance",
        "vehicle_operating_allowance",
        "road_toll",
        "planned_ferry_fees",
        "border_charges",
        "taxes",
        "insurance",
        "escort_fees",
        "handling_charges",
        "loading",
        "offloading",
        "storage",
        "demurrage",
        "miscellaneous",
        "custom_tax",
        "import_duty",
        "vat",
        "excise_duty",
        "other_government_charges",
    ]

    class Meta:
        model = TransportRecord
        fields = [
            "date",
            "vehicle",
            "driver",
            "turn_boy",
            "container_number",
            "origin",
            "destination",
            "distance_km",
            "overall_charge",
        ]
        widgets = {
            "date": DATE_WIDGET,
            "distance_km": MONEY_WIDGET,
            "overall_charge": WHOLE_MONEY_WIDGET,
        }
        labels = {
            "destination": "Final route / destination",
            "distance_km": "Total trip distance km",
            "overall_charge": "Total trip charge",
        }
        help_texts = {
            "distance_km": "Optional. Enter the total route distance if known.",
            "overall_charge": "Optional. Enter the total trip amount before in-transit expenses are deducted.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["distance_km"].required = False

    def clean(self):
        cleaned_data = super().clean()
        for field_name in self.OPTIONAL_DECIMAL_FIELDS:
            if cleaned_data.get(field_name) is None:
                cleaned_data[field_name] = Decimal("0")
        return cleaned_data


class TransportCustomerOrderForm(StyledModelForm):
    fieldsets = [
        {
            "title": "Customer and cargo",
            "helper": "Identify the customer, linked requisition, goods, delivery address, and route points.",
            "fields": (
                "customer_name",
                "requisition",
                "cargo_description",
                "package_type",
                "destination",
                "loading_point",
                "offloading_point",
            ),
        },
        {
            "title": "Space and invoice amount",
            "helper": "Enter the space used and the customer invoice amount. Loading and offloading fees remain internal notes.",
            "fields": ("pieces", "loading_charge", "offloading_charge", "cargo_charge"),
        },
    ]

    OPTIONAL_DECIMAL_FIELDS = [
        "cargo_charge",
    ]

    class Meta:
        model = TransportCustomerOrder
        fields = [
            "customer_name",
            "requisition",
            "cargo_description",
            "package_type",
            "destination",
            "loading_point",
            "offloading_point",
            "pieces",
            "loading_charge",
            "offloading_charge",
            "cargo_charge",
        ]
        labels = {
            "customer_name": "Customer name",
            "requisition": "Attach requisition",
            "cargo_description": "Type of goods",
            "package_type": "Goods / package type",
            "destination": "Customer address / destination",
            "loading_point": "Loading point",
            "offloading_point": "Offloading point",
            "pieces": "Space used",
            "loading_charge": "Loading fee (internal note)",
            "offloading_charge": "Offloading fee (internal note)",
            "cargo_charge": "Amount to show on invoice",
        }
        help_texts = {
            "requisition": "Optional. Link the customer cargo to a requisition.",
            "destination": "Enter the customer's delivery address, mine site, or branch.",
            "pieces": "Enter truck spaces, pallet spaces, or units used by this customer.",
            "loading_charge": "Optional internal note only. This amount is not added to the customer invoice.",
            "offloading_charge": "Optional internal note only. This amount is not added to the customer invoice.",
            "cargo_charge": "Enter the final customer invoice amount for Transit & Logistics Fees.",
        }
        widgets = {
            "cargo_description": forms.Textarea(attrs={"rows": 2}),
            "pieces": forms.NumberInput(attrs={"min": "0", "step": "1"}),
            "loading_charge": WHOLE_MONEY_WIDGET,
            "offloading_charge": WHOLE_MONEY_WIDGET,
            "cargo_charge": WHOLE_MONEY_WIDGET,
        }

    def has_changed(self):
        if not super().has_changed():
            return False
        text_fields = [
            "customer_name",
            "requisition",
            "cargo_description",
            "package_type",
            "loading_point",
            "offloading_point",
            "destination",
        ]
        if any(
            self.data.get(self.add_prefix(field_name), "").strip()
            for field_name in text_fields
        ):
            return True
        if self._decimal_field_changed("pieces", "0"):
            return True
        return any(
            self._decimal_field_changed(field_name, "0")
            for field_name in self.OPTIONAL_DECIMAL_FIELDS
        )

    def _decimal_field_changed(self, field_name, default_value):
        value = self.data.get(self.add_prefix(field_name), "").strip()
        if not value:
            return False
        try:
            return Decimal(value) != Decimal(default_value)
        except Exception:
            return True

    def clean(self):
        cleaned_data = super().clean()
        customer_name = cleaned_data.get("customer_name", "").strip()
        for field_name in self.OPTIONAL_DECIMAL_FIELDS:
            if cleaned_data.get(field_name) is None:
                cleaned_data[field_name] = Decimal("0")
        for field_name in ["loading_charge", "offloading_charge"]:
            if cleaned_data.get(field_name) is None:
                cleaned_data[field_name] = Decimal("0")
        if cleaned_data.get("pieces") is None:
            cleaned_data["pieces"] = 0

        has_customer_details = any(
            [
                cleaned_data.get("cargo_description", "").strip(),
                cleaned_data.get("package_type", "").strip(),
                cleaned_data.get("loading_point", "").strip(),
                cleaned_data.get("offloading_point", "").strip(),
                cleaned_data.get("destination", "").strip(),
                cleaned_data.get("pieces"),
                cleaned_data.get("loading_charge"),
                cleaned_data.get("offloading_charge"),
                *[
                    cleaned_data.get(field_name)
                    for field_name in self.OPTIONAL_DECIMAL_FIELDS
                ],
            ]
        )
        if has_customer_details and not customer_name:
            self.add_error(
                "customer_name",
                "Enter the customer name for this row.",
            )
        return cleaned_data


TransportCustomerOrderFormSet = inlineformset_factory(
    TransportRecord,
    TransportCustomerOrder,
    form=TransportCustomerOrderForm,
    fields=(
        "customer_name",
        "requisition",
        "cargo_description",
        "package_type",
        "destination",
        "loading_point",
        "offloading_point",
        "pieces",
        "loading_charge",
        "offloading_charge",
        "cargo_charge",
    ),
    extra=0,
    min_num=0,
    validate_min=False,
    can_delete=False,
)


class TransportInitialChargeForm(StyledForm):
    fieldsets = [
        {
            "title": "Charge type",
            "helper": "Name the expense, choose the internal cost type, and enter the amount.",
            "fields": ("cost_type", "custom_name", "amount"),
        },
        {
            "title": "Location and assignment",
            "helper": "Attach the charge to a route point, kilometre location, customer, and notes.",
            "fields": ("transit_point", "km_location", "charge_target", "notes"),
        },
    ]

    cost_type = forms.ChoiceField(
        choices=TransportTransitCost.CostType.choices,
        initial=TransportTransitCost.CostType.OTHER,
        label="Internal cost type",
        required=False,
        help_text="Select fuel, allowances, taxes, border fees, or Other for a custom internal deduction.",
    )
    custom_name = forms.CharField(
        required=False,
        label="Internal cost name",
        help_text="Enter a clear name such as Fuel, Driver allowance, Tax, Border charge, Ferry fee, or Parking.",
    )
    amount = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
        help_text="Enter the internal deduction amount. This does not appear as a separate customer invoice line.",
        widget=WHOLE_MONEY_WIDGET,
    )
    transit_point = forms.CharField(
        required=False,
        label="Transit point / place",
        help_text="Enter the road section, border, checkpoint, town, or place where this charge applies.",
    )
    km_location = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        label="KM location",
        help_text="Enter the kilometre point for the charge. For a common-route distance charge, use the common route end km or the point where the shared route ends.",
        widget=MONEY_WIDGET,
    )
    charge_target = forms.ChoiceField(
        required=False,
        label="Internal cost assignment",
        help_text="Use General trip cost for fuel, allowances, and taxes. Choose a customer only when the cost belongs to that customer's delivery for profit analysis.",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Add any extra explanation needed for this charge.",
    )

    def __init__(self, *args, customer_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("base", "General trip cost")]
        choices.extend(customer_choices or [])
        self.fields["charge_target"].choices = choices

    def has_changed(self):
        if not super().has_changed():
            return False
        text_fields = ["custom_name", "transit_point", "notes"]
        if any(
            self.data.get(self.add_prefix(field_name), "").strip()
            for field_name in text_fields
        ):
            return True
        if self.data.get(self.add_prefix("charge_target"), "base") != "base":
            return True
        return any(
            self._decimal_field_changed(field_name)
            for field_name in ["amount", "km_location"]
        )

    def _decimal_field_changed(self, field_name):
        value = self.data.get(self.add_prefix(field_name), "").strip()
        if not value:
            return False
        try:
            return Decimal(value) != Decimal("0")
        except Exception:
            return True

    def clean(self):
        cleaned_data = super().clean()
        amount = cleaned_data.get("amount") or Decimal("0")
        if not self.has_changed():
            return cleaned_data
        if not amount:
            self.add_error("amount", "Enter the charge amount.")
        if (
            cleaned_data.get("cost_type") == TransportTransitCost.CostType.OTHER
            and not cleaned_data.get("custom_name", "").strip()
        ):
            self.add_error("custom_name", "Enter the custom charge name.")
        return cleaned_data

    def save(self, transport, customer_orders_by_index):
        if not self.has_changed() or self.errors:
            return None
        target = self.cleaned_data.get("charge_target") or "base"
        customer_order = None
        allocation_method = TransportTransitCost.AllocationMethod.DISTANCE_SHARED
        if target.startswith("customer:"):
            customer_index = int(target.split(":", 1)[1])
            customer_order = customer_orders_by_index.get(customer_index)
            allocation_method = TransportTransitCost.AllocationMethod.CLIENT_SPECIFIC

        return TransportTransitCost.objects.create(
            transport=transport,
            cost_type=self.cleaned_data.get("cost_type")
            or TransportTransitCost.CostType.OTHER,
            custom_name=self.cleaned_data.get("custom_name", "").strip(),
            amount=self.cleaned_data.get("amount") or Decimal("0"),
            km_location=self.cleaned_data.get("km_location") or Decimal("0"),
            transit_point=self.cleaned_data.get("transit_point", "").strip(),
            allocation_method=allocation_method,
            customer_order=customer_order,
            notes=self.cleaned_data.get("notes", "").strip(),
        )


TransportInitialChargeFormSet = formset_factory(
    TransportInitialChargeForm,
    extra=3,
    min_num=0,
    validate_min=False,
)


class TransportTransitPointForm(StyledModelForm):
    OPTIONAL_DECIMAL_FIELDS = ["amount", "km_location"]

    class Meta:
        model = TransportTransitPoint
        fields = [
            "point_type",
            "fee_category",
            "fee_name",
            "place_name",
            "reference_number",
            "km_location",
            "sequence",
            "amount",
            "notes",
        ]
        labels = {
            "point_type": "Point type",
            "fee_category": "Fee category",
            "fee_name": "Fee / tax name",
            "place_name": "Point / place",
            "reference_number": "Receipt / reference",
            "km_location": "KM location",
            "sequence": "Route sequence",
            "amount": "Amount",
        }
        widgets = {
            "sequence": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "km_location": MONEY_WIDGET,
            "amount": MONEY_WIDGET,
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def has_changed(self):
        if not super().has_changed():
            return False
        text_fields = ["fee_name", "place_name", "reference_number", "notes"]
        if any(
            self.data.get(self.add_prefix(field_name), "").strip()
            for field_name in text_fields
        ):
            return True
        if self._decimal_field_changed("sequence", "0"):
            return True
        return any(
            self._decimal_field_changed(field_name, "0")
            for field_name in self.OPTIONAL_DECIMAL_FIELDS
        )

    def _decimal_field_changed(self, field_name, default_value):
        value = self.data.get(self.add_prefix(field_name), "").strip()
        if not value:
            return False
        try:
            return Decimal(value) != Decimal(default_value)
        except Exception:
            return True

    def clean(self):
        cleaned_data = super().clean()
        for field_name in self.OPTIONAL_DECIMAL_FIELDS:
            if cleaned_data.get(field_name) is None:
                cleaned_data[field_name] = Decimal("0")
        amount = cleaned_data.get("amount") or Decimal("0")
        fee_name = cleaned_data.get("fee_name", "").strip()
        if amount and not fee_name:
            self.add_error("fee_name", "Enter the fee or tax name.")
        return cleaned_data


TransportTransitPointFormSet = inlineformset_factory(
    TransportRecord,
    TransportTransitPoint,
    form=TransportTransitPointForm,
    fields=(
        "point_type",
        "fee_category",
        "fee_name",
        "place_name",
        "reference_number",
        "km_location",
        "sequence",
        "amount",
        "notes",
    ),
    extra=3,
    can_delete=False,
)


class TransportAttachmentForm(StyledModelForm):
    class Meta:
        model = TransportAttachment
        fields = ["document_type", "file"]


class TransportGovernmentChargeForm(StyledModelForm):
    class Meta:
        model = TransportGovernmentCharge
        fields = ["name", "amount"]
        widgets = {"amount": MONEY_WIDGET}


class TransportTransitCostForm(StyledModelForm):
    fieldsets = [
        {
            "title": "Expense type",
            "helper": "Choose the cost category, name the expense, and enter the amount and date.",
            "fields": ("cost_type", "custom_name", "amount", "cost_date"),
        },
        {
            "title": "Place and notes",
            "helper": "Add the road section, border, checkpoint, town, or explanation for this expense.",
            "fields": ("transit_point", "notes"),
        },
    ]

    class Meta:
        model = TransportTransitCost
        fields = [
            "cost_type",
            "custom_name",
            "amount",
            "cost_date",
            "transit_point",
            "notes",
        ]
        labels = {
            "custom_name": "Expense name",
            "cost_date": "Cost date",
            "transit_point": "Place / reference",
        }
        widgets = {
            "amount": WHOLE_MONEY_WIDGET,
            "cost_date": DATE_WIDGET,
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, transport=None, **kwargs):
        self.transport = transport
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        return cleaned_data
