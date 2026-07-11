from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import (
    PurchaseOrder,
    Requisition,
    TransportCustomerInvoice,
    TransportCustomerInvoiceLine,
)

MONEY_QUANT = Decimal("0.01")


def money(value):
    return Decimal(value or 0).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def transport_purchase_orders(record):
    orders = []
    seen = set()
    customer_orders = record.customer_orders.select_related(
        "purchase_order__supplier", "purchase_order__inquiry__requisition"
    )
    for customer_order in customer_orders:
        order = customer_order.purchase_order
        if order and order.pk not in seen:
            orders.append(order)
            seen.add(order.pk)
    if record.purchase_order_id and record.purchase_order_id not in seen:
        orders.append(record.purchase_order)
    return orders


def sync_transport_procurement_status(record):
    orders = transport_purchase_orders(record)
    if orders:
        first_order = orders[0]
        update_fields = []
        if record.purchase_order_id != first_order.pk:
            record.purchase_order = first_order
            update_fields.append("purchase_order")
        if not record.supplier_id:
            record.supplier = first_order.supplier
            update_fields.append("supplier")
        if not record.requisition_id:
            record.requisition = first_order.inquiry.requisition
            update_fields.append("requisition")
        if update_fields:
            record.save(update_fields=[*update_fields, "updated_at"])

    requisitions = {}
    for order in orders:
        if order.status != PurchaseOrder.Status.LOADED_FOR_TRANSPORT:
            order.status = PurchaseOrder.Status.LOADED_FOR_TRANSPORT
            order.save(update_fields=["status", "updated_at"])
        requisitions[order.inquiry.requisition_id] = order.inquiry.requisition
    if record.requisition_id:
        requisitions[record.requisition_id] = record.requisition
    for requisition in requisitions.values():
        if requisition.status != Requisition.Status.IN_TRANSPORT:
            requisition.status = Requisition.Status.IN_TRANSPORT
            requisition.save(update_fields=["status", "updated_at"])


def customer_is_onboard(customer_order, sequence):
    if not sequence:
        return True
    loading_sequence = customer_order.loading_sequence or 1
    offloading_sequence = customer_order.offloading_sequence
    if sequence < loading_sequence:
        return False
    if offloading_sequence and sequence > offloading_sequence:
        return False
    return True


def allocation_weight(customer_order):
    return customer_order.chargeable_units * customer_order.billing_distance_km


def allocate_amount(amount, customer_order, eligible_orders, weight_getter):
    amount = money(amount)
    if not amount or not eligible_orders:
        return Decimal("0.00")
    total_weight = sum(
        (weight_getter(order) for order in eligible_orders), Decimal("0")
    )
    if not total_weight:
        return money(amount / Decimal(len(eligible_orders)))
    return money(amount * weight_getter(customer_order) / total_weight)


def shared_fleet_total(record):
    fields = [
        record.freight,
        record.fuel,
        record.driver_allowance,
        record.insurance,
        record.escort_fees,
        record.handling_charges,
        record.loading,
        record.offloading,
        record.storage,
        record.demurrage,
        record.miscellaneous,
    ]
    return money(sum(fields, Decimal("0")))


def direct_charge_lines(customer_order):
    charge_fields = [
        ("Cargo charge", customer_order.cargo_charge),
        ("Handling charge", customer_order.handling_charge),
        ("Loading charge", customer_order.loading_charge),
        ("Offloading charge", customer_order.offloading_charge),
        ("Storage charge", customer_order.storage_charge),
        ("Other customer charge", customer_order.miscellaneous_charge),
    ]
    lines = []
    for label, amount in charge_fields:
        amount = money(amount)
        if amount:
            lines.append((TransportCustomerInvoiceLine.LineType.DIRECT, label, amount))
    return lines


def generate_transport_customer_invoices(record, generated_by=None):
    customer_orders = list(record.customer_orders.all())
    transit_points = list(record.transit_points.all())
    invoices = []
    if not customer_orders:
        return invoices

    shared_total = shared_fleet_total(record)
    shared_eligible_orders = [
        order for order in customer_orders if allocation_weight(order)
    ] or customer_orders

    with transaction.atomic():
        record.customer_invoices.all().delete()
        for customer_order in customer_orders:
            invoice = TransportCustomerInvoice.objects.create(
                transport=record,
                customer_order=customer_order,
                customer_name=customer_order.customer_name or "Unnamed customer",
                generated_by=generated_by,
            )
            sort_order = 1

            for line_type, description, amount in direct_charge_lines(customer_order):
                TransportCustomerInvoiceLine.objects.create(
                    invoice=invoice,
                    line_type=line_type,
                    description=description,
                    amount=amount,
                    sort_order=sort_order,
                )
                sort_order += 1

            shared_amount = allocate_amount(
                shared_total, customer_order, shared_eligible_orders, allocation_weight
            )
            if shared_amount:
                description = (
                    f"Shared fleet charges from {customer_order.loading_point or record.origin} "
                    f"to {customer_order.offloading_point or record.destination}"
                )
                TransportCustomerInvoiceLine.objects.create(
                    invoice=invoice,
                    line_type=TransportCustomerInvoiceLine.LineType.SHARED,
                    description=description,
                    amount=shared_amount,
                    sort_order=sort_order,
                )
                sort_order += 1

            for transit_point in transit_points:
                eligible_orders = [
                    order
                    for order in customer_orders
                    if customer_is_onboard(order, transit_point.sequence)
                ]
                if customer_order not in eligible_orders:
                    continue
                transit_amount = allocate_amount(
                    transit_point.total_amount,
                    customer_order,
                    eligible_orders,
                    lambda order: order.chargeable_units,
                )
                if not transit_amount:
                    continue
                fee_name = (
                    transit_point.fee_name or transit_point.get_fee_category_display()
                )
                description = f"{fee_name} at {transit_point.place_name}"
                TransportCustomerInvoiceLine.objects.create(
                    invoice=invoice,
                    line_type=TransportCustomerInvoiceLine.LineType.TRANSIT,
                    description=description,
                    amount=transit_amount,
                    sort_order=sort_order,
                )
                sort_order += 1

            invoices.append(invoice)
    return invoices
