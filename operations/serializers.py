from rest_framework import serializers

from .models import (
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
)


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = "__all__"


class RequisitionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequisitionItem
        fields = ["id", "description", "pieces", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class RequisitionSerializer(serializers.ModelSerializer):
    requester = serializers.StringRelatedField(read_only=True)
    items = RequisitionItemSerializer(many=True, required=False)
    item_summary = serializers.CharField(read_only=True)
    total_pieces = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = Requisition
        fields = [
            "id",
            "requisition_number",
            "requester",
            "language",
            "urgent",
            "status",
            "items",
            "item_description",
            "quantity",
            "item_summary",
            "total_pieces",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "requisition_number",
            "requester",
            "status",
            "item_description",
            "quantity",
            "item_summary",
            "total_pieces",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        if self.instance is None and not attrs.get("items"):
            raise serializers.ValidationError(
                {"items": "Add at least one item to the requisition."}
            )
        return attrs

    def create(self, validated_data):
        items_data = validated_data.pop("items")
        validated_data["item_description"] = self._item_summary(items_data)
        validated_data["quantity"] = self._item_quantity(items_data)
        requisition = Requisition.objects.create(**validated_data)
        for item in items_data:
            RequisitionItem.objects.create(requisition=requisition, **item)
        return requisition

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if items_data is not None:
            instance.items.all().delete()
            instance.item_description = self._item_summary(items_data)
            instance.quantity = self._item_quantity(items_data)
            for item in items_data:
                RequisitionItem.objects.create(requisition=instance, **item)
        instance.save()
        return instance

    def _item_summary(self, items_data):
        return "\n".join(
            f"{item['description']} ({item['pieces']} pcs)" for item in items_data
        )

    def _item_quantity(self, items_data):
        return sum((item["pieces"] for item in items_data), 0)


class PurchaseInquirySerializer(serializers.ModelSerializer):
    sent_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = PurchaseInquiry
        fields = "__all__"
        read_only_fields = [
            "inquiry_number",
            "sent_by",
            "status",
            "created_at",
            "updated_at",
        ]


class SupplierInvoiceSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = SupplierInvoice
        fields = "__all__"
        read_only_fields = ["uploaded_by", "created_at", "updated_at"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField(read_only=True)
    supplier = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = "__all__"
        read_only_fields = [
            "order_number",
            "supplier",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]


class PurchaseReceiptSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = PurchaseReceipt
        fields = "__all__"
        read_only_fields = ["uploaded_by", "created_at", "updated_at"]


class TransportGovernmentChargeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransportGovernmentCharge
        fields = "__all__"


class TransportAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = TransportAttachment
        fields = "__all__"
        read_only_fields = ["uploaded_by", "created_at", "updated_at"]


class TransportCustomerOrderSerializer(serializers.ModelSerializer):
    cargo_cbm = serializers.DecimalField(
        max_digits=18, decimal_places=3, read_only=True
    )
    charge_total = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    class Meta:
        model = TransportCustomerOrder
        fields = [
            "id",
            "customer_name",
            "purchase_order",
            "cargo_description",
            "package_type",
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
            "cargo_cbm",
            "charge_total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "cargo_cbm",
            "charge_total",
            "created_at",
            "updated_at",
        ]


class TransportTransitPointSerializer(serializers.ModelSerializer):
    total_amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    class Meta:
        model = TransportTransitPoint
        fields = [
            "id",
            "point_type",
            "fee_category",
            "fee_name",
            "place_name",
            "reference_number",
            "amount",
            "total_amount",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "total_amount", "created_at", "updated_at"]


class TransportRecordSerializer(serializers.ModelSerializer):
    cbm = serializers.DecimalField(max_digits=18, decimal_places=3, read_only=True)
    cost_total = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    tax_total = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    total_cost = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    average_cost_per_ton = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    average_cost_per_cbm = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    created_by = serializers.StringRelatedField(read_only=True)
    custom_government_charges = TransportGovernmentChargeSerializer(
        many=True, read_only=True
    )
    attachments = TransportAttachmentSerializer(many=True, read_only=True)
    customer_orders = TransportCustomerOrderSerializer(many=True, required=False)
    transit_points = TransportTransitPointSerializer(many=True, required=False)

    class Meta:
        model = TransportRecord
        fields = "__all__"
        read_only_fields = [
            "transport_number",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        customer_orders_data = validated_data.pop("customer_orders", [])
        transit_points_data = validated_data.pop("transit_points", [])
        record = TransportRecord.objects.create(**validated_data)
        for customer_order_data in customer_orders_data:
            TransportCustomerOrder.objects.create(
                transport=record, **customer_order_data
            )
        for transit_point_data in transit_points_data:
            TransportTransitPoint.objects.create(transport=record, **transit_point_data)
        return record

    def update(self, instance, validated_data):
        customer_orders_data = validated_data.pop("customer_orders", None)
        transit_points_data = validated_data.pop("transit_points", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if customer_orders_data is not None:
            instance.customer_orders.all().delete()
            for customer_order_data in customer_orders_data:
                TransportCustomerOrder.objects.create(
                    transport=instance, **customer_order_data
                )
        if transit_points_data is not None:
            instance.transit_points.all().delete()
            for transit_point_data in transit_points_data:
                TransportTransitPoint.objects.create(
                    transport=instance, **transit_point_data
                )
        return instance
