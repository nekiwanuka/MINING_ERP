from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from operations.models import CommercialDocument, TransportRecord, TransportTransitCost
from operations.services import generate_transport_customer_invoices


class Command(BaseCommand):
    help = "Delete transport demo data and create fresh transport sample records."

    def handle(self, *args, **options):
        CommercialDocument.objects.filter(transport__isnull=False).delete()
        TransportRecord.objects.all().delete()

        user = get_user_model().objects.filter(username="admin").first()
        if not user:
            user = get_user_model().objects.create_superuser(
                username="admin",
                password="admin",
            )
        else:
            user.set_password("admin")
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=["password", "is_staff", "is_superuser"])

        delivered_trip = TransportRecord.objects.create(
            date=timezone.localdate(),
            vehicle="UAZ 910B",
            driver="Daniel K.",
            turn_boy="Musa P.",
            container_number="CONT-1001",
            origin="Kampala Depot",
            destination="Kilembe Mine",
            distance_km=Decimal("420.00"),
            overall_charge=Decimal("1000000.00"),
            status=TransportRecord.Status.DELIVERED,
            created_by=user,
        )
        delivered_customers = [
            {
                "customer_name": "Kasese Minerals",
                "destination": "Kasese Store",
                "cargo_description": "Crusher liners and service tools",
                "package_type": "Crates",
                "loading_point": "Kampala Depot",
                "offloading_point": "Kasese Store",
                "pieces": 2,
                "loading_charge": Decimal("0.00"),
                "offloading_charge": Decimal("0.00"),
                "cargo_charge": Decimal("500000.00"),
            },
            {
                "customer_name": "Kilembe Smelter",
                "destination": "Mine Workshop",
                "cargo_description": "Drill rods and electrical cable",
                "package_type": "Bundles",
                "loading_point": "Kampala Depot",
                "offloading_point": "Mine Workshop",
                "pieces": 2,
                "loading_charge": Decimal("0.00"),
                "offloading_charge": Decimal("0.00"),
                "cargo_charge": Decimal("500000.00"),
            },
        ]
        for customer in delivered_customers:
            delivered_trip.customer_orders.create(**customer)
        self.create_expenses(
            delivered_trip,
            [
                (
                    TransportTransitCost.CostType.FUEL,
                    "Fuel",
                    Decimal("420000.00"),
                    "Fuel receipts",
                ),
                (
                    TransportTransitCost.CostType.DRIVER,
                    "Driver allowance",
                    Decimal("120000.00"),
                    "Driver trip allowance",
                ),
                (
                    TransportTransitCost.CostType.TAX,
                    "Road tax",
                    Decimal("160000.00"),
                    "Road and council taxes",
                ),
                (
                    TransportTransitCost.CostType.OTHER,
                    "Loading support",
                    Decimal("100000.00"),
                    "Casual loading support",
                ),
            ],
        )
        delivered_invoices = generate_transport_customer_invoices(delivered_trip, user)

        in_transit_trip = TransportRecord.objects.create(
            date=timezone.localdate(),
            vehicle="UBG 442Q",
            driver="Sarah N.",
            turn_boy="Peter O.",
            container_number="CONT-2044",
            origin="Mombasa Port",
            destination="Kolwezi Site",
            distance_km=Decimal("1180.00"),
            overall_charge=Decimal("2400000.00"),
            status=TransportRecord.Status.IN_TRANSIT,
            created_by=user,
        )
        in_transit_customers = [
            {
                "customer_name": "Kolwezi Copper",
                "destination": "Kolwezi Stores",
                "cargo_description": "Mill spares and pumps",
                "package_type": "Pallets",
                "loading_point": "Mombasa Port",
                "offloading_point": "Kolwezi Stores",
                "pieces": 4,
                "loading_charge": Decimal("0.00"),
                "offloading_charge": Decimal("0.00"),
                "cargo_charge": Decimal("1200000.00"),
            },
            {
                "customer_name": "Likasi Engineering",
                "destination": "Likasi Yard",
                "cargo_description": "Hydraulic hoses and workshop consumables",
                "package_type": "Cartons",
                "loading_point": "Mombasa Port",
                "offloading_point": "Likasi Yard",
                "pieces": 3,
                "loading_charge": Decimal("0.00"),
                "offloading_charge": Decimal("0.00"),
                "cargo_charge": Decimal("900000.00"),
            },
        ]
        for customer in in_transit_customers:
            in_transit_trip.customer_orders.create(**customer)
        self.create_expenses(
            in_transit_trip,
            [
                (
                    TransportTransitCost.CostType.FUEL,
                    "Fuel at Malaba",
                    Decimal("350000.00"),
                    "Ongoing fuel actual",
                ),
                (
                    TransportTransitCost.CostType.BORDER,
                    "Border parking",
                    Decimal("85000.00"),
                    "Border parking and handling",
                ),
            ],
        )

        draft_trip = TransportRecord.objects.create(
            date=timezone.localdate(),
            vehicle="UGX 221T",
            driver="Grace A.",
            origin="Kampala Depot",
            destination="Mbarara Warehouse",
            distance_km=Decimal("270.00"),
            overall_charge=Decimal("750000.00"),
            status=TransportRecord.Status.DRAFT,
            created_by=user,
        )
        draft_trip.customer_orders.create(
            customer_name="Mbarara Quarry",
            destination="Mbarara Warehouse",
            cargo_description="Safety gear and small tools",
            package_type="Boxes",
            loading_point="Kampala Depot",
            offloading_point="Mbarara Warehouse",
            pieces=1,
            cargo_charge=Decimal("750000.00"),
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Reset transport data and created fresh seed trips: "
                f"{delivered_trip.transport_number} ({len(delivered_customers)} customers, {len(delivered_invoices)} invoices), "
                f"{in_transit_trip.transport_number} (in transit), and {draft_trip.transport_number} (draft)."
            )
        )

    def create_expenses(self, record, expenses):
        for cost_type, name, amount, notes in expenses:
            TransportTransitCost.objects.create(
                transport=record,
                cost_type=cost_type,
                custom_name=name,
                amount=amount,
                cost_date=timezone.localdate(),
                transit_point="Route actual",
                allocation_method=TransportTransitCost.AllocationMethod.INTERNAL_ONLY,
                notes=notes,
            )
