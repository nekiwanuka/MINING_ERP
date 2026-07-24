from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import (
    PurchaseOrder,
    Requisition,
    TransportCustomerInvoice,
    TransportCustomerInvoiceLine,
    TransportTransitCost,
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


def customer_is_onboard_at_km(customer_order, km_location):
    if km_location is None:
        return True
    return (
        customer_order.transport.route_start_km
        <= km_location
        <= customer_order.effective_delivery_km
    )


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


def planned_shared_transit_costs(record):
    return [
        ("Fuel", record.fuel),
        ("Driver allowance", record.driver_allowance),
        ("Turn boy allowance", record.turn_boy_allowance),
        ("Vehicle operating allowance", record.vehicle_operating_allowance),
        ("Planned road tolls", record.road_toll),
        ("Planned ferry fees", record.planned_ferry_fees),
        ("Planned border charges", record.border_charges),
        ("Planned taxes", record.taxes),
        ("Escort fees", record.escort_fees),
        ("Handling charges", record.handling_charges),
        ("Storage", record.storage),
        ("Demurrage", record.demurrage),
        ("Planned miscellaneous", record.miscellaneous),
    ]


def route_segments(record, customer_orders):
    start_km = record.route_start_km
    common_end_km = max(record.route_common_end_km, start_km)
    final_km = max(
        record.route_final_km,
        common_end_km,
        *(order.effective_delivery_km for order in customer_orders),
    )
    split_points = {start_km, common_end_km, final_km}
    split_points.update(
        order.effective_delivery_km
        for order in customer_orders
        if start_km < order.effective_delivery_km < final_km
    )
    points = sorted(split_points)
    segments = []
    for index in range(len(points) - 1):
        segment_start = points[index]
        segment_end = points[index + 1]
        if segment_end <= segment_start:
            continue
        onboard_orders = [
            order
            for order in customer_orders
            if order.effective_delivery_km > segment_start
        ]
        if onboard_orders:
            segments.append(
                {
                    "distance": segment_end - segment_start,
                    "zone": (
                        "common" if segment_end <= common_end_km else "distribution"
                    ),
                    "orders": onboard_orders,
                }
            )
    return segments


def allocate_route_occupancy(amount, customer_order, customer_orders):
    amount = money(amount)
    allocation = {"common": Decimal("0.00"), "distribution": Decimal("0.00")}
    if not amount or not customer_orders:
        return allocation
    segments = route_segments(customer_order.transport, customer_orders)
    total_distance = sum((segment["distance"] for segment in segments), Decimal("0"))
    if not total_distance:
        return allocation
    for segment in segments:
        if customer_order not in segment["orders"]:
            continue
        segment_amount = amount * segment["distance"] / total_distance
        allocation[segment["zone"]] += money(
            segment_amount / Decimal(len(segment["orders"]))
        )
    return allocation


def direct_charge_lines(customer_order):
    charge_fields = [
        ("Transport charge", customer_order.transport_charge),
        ("Loading charge", customer_order.loading_charge),
        ("Offloading charge", customer_order.offloading_charge),
        ("Government / document charge", customer_order.document_charge),
        (
            customer_order.other_charge_label or "Other customer charge",
            customer_order.miscellaneous_charge,
        ),
    ]
    lines = []
    for label, amount in charge_fields:
        amount = money(amount)
        if amount:
            lines.append((TransportCustomerInvoiceLine.LineType.DIRECT, label, amount))
    return lines


def distance_weight(customer_order):
    return customer_order.billing_distance_km


def onboard_orders_at_km(customer_orders, km_location):
    if not km_location:
        return customer_orders
    return [
        order
        for order in customer_orders
        if customer_is_onboard_at_km(order, km_location)
    ]


def transit_cost_invoice_amount(cost, customer_order, customer_orders):
    if cost.allocation_method == TransportTransitCost.AllocationMethod.INTERNAL_ONLY:
        return Decimal("0.00")
    if cost.allocation_method == TransportTransitCost.AllocationMethod.CLIENT_SPECIFIC:
        if cost.customer_order_id == customer_order.id:
            return money(cost.amount)
        return Decimal("0.00")
    if cost.allocation_method == TransportTransitCost.AllocationMethod.MANUAL:
        if cost.customer_order_id == customer_order.id:
            return money(cost.manual_client_amount)
        return Decimal("0.00")
    if cost.km_location:
        eligible_orders = onboard_orders_at_km(customer_orders, cost.km_location)
        if customer_order not in eligible_orders:
            return Decimal("0.00")
        return money(cost.amount / Decimal(len(eligible_orders)))
    eligible_orders = [order for order in customer_orders if order.billing_distance_km]
    if not eligible_orders:
        eligible_orders = customer_orders
    return allocate_amount(
        cost.amount, customer_order, eligible_orders, distance_weight
    )


def transit_point_invoice_amount(transit_point, customer_order, customer_orders):
    if transit_point.km_location:
        eligible_orders = onboard_orders_at_km(
            customer_orders, transit_point.km_location
        )
    else:
        eligible_orders = [
            order
            for order in customer_orders
            if customer_is_onboard(order, transit_point.sequence)
        ]
    if customer_order not in eligible_orders:
        return Decimal("0.00")
    if transit_point.km_location:
        return money(transit_point.total_amount / Decimal(len(eligible_orders)))
    return allocate_amount(
        transit_point.total_amount,
        customer_order,
        eligible_orders,
        distance_weight,
    )


def generate_transport_customer_invoices(record, generated_by=None):
    customer_orders = list(record.customer_orders.all())
    transit_points = list(record.transit_points.all())
    transit_costs = list(record.transit_costs.all())
    invoices = []
    if not customer_orders:
        return invoices

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

            common_total = Decimal("0.00")
            distribution_total = Decimal("0.00")
            for _label, amount in planned_shared_transit_costs(record):
                allocation = allocate_route_occupancy(
                    amount, customer_order, customer_orders
                )
                common_total += allocation["common"]
                distribution_total += allocation["distribution"]
            if common_total:
                TransportCustomerInvoiceLine.objects.create(
                    invoice=invoice,
                    line_type=TransportCustomerInvoiceLine.LineType.SHARED,
                    description="Allocated common route costs",
                    amount=money(common_total),
                    sort_order=sort_order,
                )
                sort_order += 1
            if distribution_total:
                TransportCustomerInvoiceLine.objects.create(
                    invoice=invoice,
                    line_type=TransportCustomerInvoiceLine.LineType.SHARED,
                    description="Allocated distribution route costs",
                    amount=money(distribution_total),
                    sort_order=sort_order,
                )
                sort_order += 1

            for transit_point in transit_points:
                transit_amount = transit_point_invoice_amount(
                    transit_point, customer_order, customer_orders
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

            for transit_cost in transit_costs:
                transit_amount = transit_cost_invoice_amount(
                    transit_cost, customer_order, customer_orders
                )
                if not transit_amount:
                    continue
                TransportCustomerInvoiceLine.objects.create(
                    invoice=invoice,
                    line_type=TransportCustomerInvoiceLine.LineType.TRANSIT,
                    description=transit_cost.display_name,
                    amount=transit_amount,
                    sort_order=sort_order,
                )
                sort_order += 1

            invoices.append(invoice)
    return invoices
