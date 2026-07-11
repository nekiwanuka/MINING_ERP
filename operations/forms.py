from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.forms import formset_factory, inlineformset_factory

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
    TransportGovernmentCharge,
    TransportRecord,
    TransportTransitPoint,
    UserModuleAccess,
    VisaEmbassy,
)

DATE_WIDGET = forms.DateInput(attrs={"type": "date"})
MONEY_WIDGET = forms.NumberInput(attrs={"step": "0.01", "min": "0"})
MEASURE_WIDGET = forms.NumberInput(attrs={"step": "0.001", "min": "0"})


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = field.widget.attrs.get("class", "")
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = f"{css_class} checkbox-control".strip()
            else:
                field.widget.attrs["class"] = f"{css_class} field-control".strip()


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = field.widget.attrs.get("class", "")
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = f"{css_class} checkbox-control".strip()
            else:
                field.widget.attrs["class"] = f"{css_class} field-control".strip()


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
        for field in self.fields.values():
            css_class = field.widget.attrs.get("class", "")
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = f"{css_class} checkbox-control".strip()
            else:
                field.widget.attrs["class"] = f"{css_class} field-control".strip()


ModuleAccessFormSet = formset_factory(ModuleAccessForm, extra=0)


class RequisitionForm(StyledModelForm):
    class Meta:
        model = Requisition
        fields = ["language", "urgent"]
        labels = {"language": "Description language", "urgent": "Urgent requisition"}


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
    extra=3,
    min_num=1,
    validate_min=True,
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


class FinancialRecordForm(StyledModelForm):
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

    def clean(self):
        cleaned_data = super().clean()
        batch = cleaned_data.get("batch")
        litres_issued = cleaned_data.get("litres_issued")
        if batch and litres_issued and litres_issued > batch.available_litres:
            self.add_error(
                "litres_issued",
                f"Only {batch.available_litres} litres are available in this batch.",
            )
        return cleaned_data


class VisaEmbassyForm(StyledModelForm):
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
    OPTIONAL_DECIMAL_FIELDS = [
        "weight_tons",
        "freight",
        "fuel",
        "driver_allowance",
        "road_toll",
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
        "length",
        "width",
        "height",
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
            "container_number",
            "requisition",
            "supplier",
            "origin",
            "destination",
            "distance_km",
            "weight_tons",
            "freight",
            "fuel",
            "driver_allowance",
            "road_toll",
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
            "length",
            "width",
            "height",
            "cbm_quantity",
            "custom_tax",
            "import_duty",
            "vat",
            "excise_duty",
            "other_government_charges",
        ]
        widgets = {
            "date": DATE_WIDGET,
            "distance_km": MONEY_WIDGET,
            "weight_tons": MONEY_WIDGET,
            "freight": MONEY_WIDGET,
            "fuel": MONEY_WIDGET,
            "driver_allowance": MONEY_WIDGET,
            "road_toll": MONEY_WIDGET,
            "border_charges": MONEY_WIDGET,
            "taxes": MONEY_WIDGET,
            "insurance": MONEY_WIDGET,
            "escort_fees": MONEY_WIDGET,
            "handling_charges": MONEY_WIDGET,
            "loading": MONEY_WIDGET,
            "offloading": MONEY_WIDGET,
            "storage": MONEY_WIDGET,
            "demurrage": MONEY_WIDGET,
            "miscellaneous": MONEY_WIDGET,
            "length": MEASURE_WIDGET,
            "width": MEASURE_WIDGET,
            "height": MEASURE_WIDGET,
            "custom_tax": MONEY_WIDGET,
            "import_duty": MONEY_WIDGET,
            "vat": MONEY_WIDGET,
            "excise_duty": MONEY_WIDGET,
            "other_government_charges": MONEY_WIDGET,
        }

    def clean(self):
        cleaned_data = super().clean()
        for field_name in self.OPTIONAL_DECIMAL_FIELDS:
            if cleaned_data.get(field_name) is None:
                cleaned_data[field_name] = Decimal("0")
        return cleaned_data


class TransportCustomerOrderForm(StyledModelForm):
    OPTIONAL_DECIMAL_FIELDS = [
        "weight_tons",
        "billable_distance_km",
        "length",
        "width",
        "height",
        "cargo_charge",
        "handling_charge",
        "loading_charge",
        "offloading_charge",
        "storage_charge",
        "miscellaneous_charge",
    ]

    class Meta:
        model = TransportCustomerOrder
        fields = [
            "customer_name",
            "purchase_order",
            "cargo_description",
            "package_type",
            "loading_point",
            "offloading_point",
            "loading_sequence",
            "offloading_sequence",
            "billable_distance_km",
            "pieces",
            "weight_tons",
            "length",
            "width",
            "height",
            "cbm_quantity",
            "cargo_charge",
            "handling_charge",
            "loading_charge",
            "offloading_charge",
            "storage_charge",
            "miscellaneous_charge",
        ]
        labels = {
            "customer_name": "Customer name",
            "purchase_order": "Purchase order",
            "cargo_description": "Cargo, luggage, parcels, or items",
            "package_type": "Package type",
            "loading_point": "Loading point",
            "offloading_point": "Offloading point",
            "loading_sequence": "Loading sequence",
            "offloading_sequence": "Offloading sequence",
            "billable_distance_km": "Billable distance km",
            "pieces": "Pieces / packages",
            "weight_tons": "Weight tons",
            "cbm_quantity": "CBM quantity",
            "cargo_charge": "Cargo charge",
            "handling_charge": "Handling charge",
            "loading_charge": "Loading charge",
            "offloading_charge": "Offloading charge",
            "storage_charge": "Storage charge",
            "miscellaneous_charge": "Other customer charge",
        }
        widgets = {
            "cargo_description": forms.Textarea(attrs={"rows": 3}),
            "loading_sequence": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "offloading_sequence": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "billable_distance_km": MONEY_WIDGET,
            "pieces": forms.NumberInput(attrs={"min": "0", "step": "1"}),
            "weight_tons": MONEY_WIDGET,
            "length": MEASURE_WIDGET,
            "width": MEASURE_WIDGET,
            "height": MEASURE_WIDGET,
            "cargo_charge": MONEY_WIDGET,
            "handling_charge": MONEY_WIDGET,
            "loading_charge": MONEY_WIDGET,
            "offloading_charge": MONEY_WIDGET,
            "storage_charge": MONEY_WIDGET,
            "miscellaneous_charge": MONEY_WIDGET,
        }

    def has_changed(self):
        if not super().has_changed():
            return False
        text_fields = [
            "customer_name",
            "purchase_order",
            "cargo_description",
            "package_type",
            "loading_point",
            "offloading_point",
        ]
        if any(
            self.data.get(self.add_prefix(field_name), "").strip()
            for field_name in text_fields
        ):
            return True
        if self._decimal_field_changed("pieces", "0"):
            return True
        if self._decimal_field_changed("loading_sequence", "0"):
            return True
        if self._decimal_field_changed("offloading_sequence", "0"):
            return True
        if self._decimal_field_changed("cbm_quantity", "1"):
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
        purchase_order = cleaned_data.get("purchase_order")
        for field_name in self.OPTIONAL_DECIMAL_FIELDS:
            if cleaned_data.get(field_name) is None:
                cleaned_data[field_name] = Decimal("0")
        if cleaned_data.get("pieces") is None:
            cleaned_data["pieces"] = 0
        if cleaned_data.get("cbm_quantity") is None:
            cleaned_data["cbm_quantity"] = 1

        has_cargo_or_charges = any(
            [
                purchase_order,
                cleaned_data.get("cargo_description", "").strip(),
                cleaned_data.get("package_type", "").strip(),
                cleaned_data.get("loading_point", "").strip(),
                cleaned_data.get("offloading_point", "").strip(),
                cleaned_data.get("loading_sequence"),
                cleaned_data.get("offloading_sequence"),
                cleaned_data.get("pieces"),
                *[
                    cleaned_data.get(field_name)
                    for field_name in self.OPTIONAL_DECIMAL_FIELDS
                ],
            ]
        )
        if has_cargo_or_charges and not customer_name:
            self.add_error(
                "customer_name",
                "Enter the customer name for this cargo row.",
            )
        return cleaned_data


TransportCustomerOrderFormSet = inlineformset_factory(
    TransportRecord,
    TransportCustomerOrder,
    form=TransportCustomerOrderForm,
    fields=(
        "customer_name",
        "purchase_order",
        "cargo_description",
        "package_type",
        "loading_point",
        "offloading_point",
        "loading_sequence",
        "offloading_sequence",
        "billable_distance_km",
        "pieces",
        "weight_tons",
        "length",
        "width",
        "height",
        "cbm_quantity",
        "cargo_charge",
        "handling_charge",
        "loading_charge",
        "offloading_charge",
        "storage_charge",
        "miscellaneous_charge",
    ),
    extra=3,
    min_num=1,
    validate_min=True,
    can_delete=False,
)


class TransportTransitPointForm(StyledModelForm):
    OPTIONAL_DECIMAL_FIELDS = ["amount"]

    class Meta:
        model = TransportTransitPoint
        fields = [
            "point_type",
            "fee_category",
            "fee_name",
            "place_name",
            "reference_number",
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
            "sequence": "Route sequence",
            "amount": "Amount",
        }
        widgets = {
            "sequence": forms.NumberInput(attrs={"min": "1", "step": "1"}),
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
