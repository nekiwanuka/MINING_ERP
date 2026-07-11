from rest_framework import permissions, viewsets
from django.utils import timezone

from .access import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_READ,
    ACTION_UPDATE,
    PROCUREMENT_GROUP,
    TRANSPORT_GROUP,
    can_edit_requisition,
    has_module_access,
    user_in_groups,
)
from .models import (
    PurchaseInquiry,
    PurchaseOrder,
    PurchaseReceipt,
    Requisition,
    Supplier,
    SupplierInvoice,
    TransportAttachment,
    TransportGovernmentCharge,
    TransportRecord,
    UserModuleAccess,
)
from .services import sync_transport_procurement_status
from .serializers import (
    PurchaseInquirySerializer,
    PurchaseOrderSerializer,
    PurchaseReceiptSerializer,
    RequisitionSerializer,
    SupplierInvoiceSerializer,
    SupplierSerializer,
    TransportAttachmentSerializer,
    TransportGovernmentChargeSerializer,
    TransportRecordSerializer,
)


class DepartmentWritePermission(permissions.BasePermission):
    action_by_method = {
        "GET": ACTION_READ,
        "HEAD": ACTION_READ,
        "OPTIONS": ACTION_READ,
        "POST": ACTION_CREATE,
        "PUT": ACTION_UPDATE,
        "PATCH": ACTION_UPDATE,
        "DELETE": ACTION_DELETE,
    }

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not request.user.is_staff:
            return False
        module = getattr(view, "module", None)
        if module is None:
            return True
        action = self.action_by_method[request.method]
        if (
            action == ACTION_UPDATE
            and module == UserModuleAccess.Module.REQUISITIONS
            and getattr(view, "allow_pending_owner_update", False)
            and has_module_access(request.user, module, ACTION_CREATE)
            and has_module_access(request.user, module, ACTION_READ)
        ):
            return True
        return has_module_access(request.user, module, action)

    def has_object_permission(self, request, view, obj):
        if (
            not request.user
            or not request.user.is_authenticated
            or not request.user.is_staff
        ):
            return False
        module = getattr(view, "module", None)
        if module is None:
            return True
        action = self.action_by_method[request.method]
        if action == ACTION_READ:
            return has_module_access(request.user, module, ACTION_READ)
        if (
            action == ACTION_UPDATE
            and module == UserModuleAccess.Module.REQUISITIONS
            and getattr(view, "allow_pending_owner_update", False)
        ):
            return can_edit_requisition(request.user, obj)
        return has_module_access(request.user, module, action)


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [DepartmentWritePermission]
    module = UserModuleAccess.Module.SUPPLIERS


class RequisitionViewSet(viewsets.ModelViewSet):
    serializer_class = RequisitionSerializer
    permission_classes = [DepartmentWritePermission]
    module = UserModuleAccess.Module.REQUISITIONS
    allow_pending_owner_update = True

    def get_queryset(self):
        queryset = Requisition.objects.select_related("requester")
        if (
            self.request.user.is_superuser
            or has_module_access(
                self.request.user, UserModuleAccess.Module.REQUISITIONS, ACTION_UPDATE
            )
            or user_in_groups(self.request.user, [PROCUREMENT_GROUP, TRANSPORT_GROUP])
        ):
            return queryset
        return queryset.filter(requester=self.request.user)

    def perform_create(self, serializer):
        serializer.save(requester=self.request.user)


class PurchaseInquiryViewSet(viewsets.ModelViewSet):
    queryset = PurchaseInquiry.objects.select_related(
        "requisition", "supplier", "sent_by"
    )
    serializer_class = PurchaseInquirySerializer
    permission_classes = [DepartmentWritePermission]
    module = UserModuleAccess.Module.PURCHASE_INQUIRIES

    def perform_create(self, serializer):
        inquiry = serializer.save(
            sent_by=self.request.user,
            status=PurchaseInquiry.Status.SENT,
            sent_at=timezone.now(),
        )
        inquiry.requisition.status = Requisition.Status.INQUIRIES_SENT
        inquiry.requisition.save(update_fields=["status", "updated_at"])


class SupplierInvoiceViewSet(viewsets.ModelViewSet):
    queryset = SupplierInvoice.objects.select_related(
        "inquiry",
        "inquiry__requisition",
        "inquiry__supplier",
        "supplier",
        "uploaded_by",
    )
    serializer_class = SupplierInvoiceSerializer
    permission_classes = [DepartmentWritePermission]
    module = UserModuleAccess.Module.SUPPLIER_INVOICES

    def perform_create(self, serializer):
        inquiry = serializer.validated_data["inquiry"]
        supplier = serializer.validated_data.get("supplier") or inquiry.supplier
        invoice = serializer.save(
            uploaded_by=self.request.user,
            requisition_number=inquiry.requisition.requisition_number,
            supplier=supplier,
            supplier_name=supplier.name,
        )
        if inquiry.supplier_id != supplier.id:
            inquiry.supplier = supplier
        invoice.inquiry.status = PurchaseInquiry.Status.INVOICE_LOADED
        invoice.inquiry.save(update_fields=["supplier", "status", "updated_at"])


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.select_related("inquiry", "supplier", "created_by")
    serializer_class = PurchaseOrderSerializer
    permission_classes = [DepartmentWritePermission]
    module = UserModuleAccess.Module.PURCHASE_ORDERS

    def perform_create(self, serializer):
        inquiry = serializer.validated_data["inquiry"]
        order = serializer.save(created_by=self.request.user, supplier=inquiry.supplier)
        inquiry.status = PurchaseInquiry.Status.ORDERED
        inquiry.save(update_fields=["status", "updated_at"])
        inquiry.requisition.status = Requisition.Status.PURCHASED
        inquiry.requisition.save(update_fields=["status", "updated_at"])


class PurchaseReceiptViewSet(viewsets.ModelViewSet):
    queryset = PurchaseReceipt.objects.select_related("purchase_order", "uploaded_by")
    serializer_class = PurchaseReceiptSerializer
    permission_classes = [DepartmentWritePermission]
    module = UserModuleAccess.Module.PURCHASE_RECEIPTS

    def perform_create(self, serializer):
        receipt = serializer.save(uploaded_by=self.request.user)
        receipt.purchase_order.status = PurchaseOrder.Status.RECEIPT_UPLOADED
        receipt.purchase_order.save(update_fields=["status", "updated_at"])


class TransportRecordViewSet(viewsets.ModelViewSet):
    queryset = TransportRecord.objects.select_related(
        "requisition", "purchase_order", "supplier", "created_by"
    ).prefetch_related("customer_orders__purchase_order", "transit_points")
    serializer_class = TransportRecordSerializer
    permission_classes = [DepartmentWritePermission]
    module = UserModuleAccess.Module.TRANSPORT

    def perform_create(self, serializer):
        record = serializer.save(created_by=self.request.user)
        sync_transport_procurement_status(record)

    def perform_update(self, serializer):
        record = serializer.save()
        sync_transport_procurement_status(record)


class TransportGovernmentChargeViewSet(viewsets.ModelViewSet):
    queryset = TransportGovernmentCharge.objects.select_related("transport")
    serializer_class = TransportGovernmentChargeSerializer
    permission_classes = [DepartmentWritePermission]
    module = UserModuleAccess.Module.TRANSPORT


class TransportAttachmentViewSet(viewsets.ModelViewSet):
    queryset = TransportAttachment.objects.select_related("transport", "uploaded_by")
    serializer_class = TransportAttachmentSerializer
    permission_classes = [DepartmentWritePermission]
    module = UserModuleAccess.Module.TRANSPORT

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)
