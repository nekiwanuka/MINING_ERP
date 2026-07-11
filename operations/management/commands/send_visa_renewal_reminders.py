from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from operations.models import ExpatriateVisa


class Command(BaseCommand):
    help = (
        "Send visa renewal reminder emails for the 30, 14, 7, 3 day and expired stages."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show reminders that would be sent without sending email or updating records.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        visas = ExpatriateVisa.objects.select_related("expatriate", "embassy").all()
        sent_count = 0
        skipped_count = 0

        for visa in visas:
            if not visa.needs_email_reminder:
                skipped_count += 1
                continue

            stage = visa.email_reminder_stage
            recipient = visa.reminder_recipient
            subject = f"Visa renewal reminder: {visa.expatriate.full_name} - {stage}"
            message = self.build_message(visa, stage)

            if dry_run:
                self.stdout.write(
                    f"Would send {stage} reminder to {recipient}: {visa.record_number}"
                )
            else:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [recipient],
                    fail_silently=False,
                )
                visa.last_reminder_stage = stage
                visa.last_reminder_sent_at = timezone.now()
                visa.save(
                    update_fields=[
                        "last_reminder_stage",
                        "last_reminder_sent_at",
                        "updated_at",
                    ]
                )
            sent_count += 1

        action = "would send" if dry_run else "sent"
        self.stdout.write(
            self.style.SUCCESS(
                f"Visa renewal reminders {action}: {sent_count}. Skipped: {skipped_count}."
            )
        )

    def build_message(self, visa, stage):
        requirements = (
            visa.renewal_requirements
            or visa.embassy.renewal_requirements
            or "Not recorded"
        )
        owner = visa.reminder_owner or "Not assigned"
        return "\n".join(
            [
                f"Visa renewal reminder stage: {stage}",
                "",
                f"Expatriate: {visa.expatriate.full_name}",
                f"Nationality: {visa.expatriate.nationality}",
                f"Passport: {visa.expatriate.passport_number}",
                f"Visa record: {visa.record_number}",
                f"Visa type: {visa.get_visa_type_display()}",
                f"Embassy / authority: {visa.embassy.name} ({visa.embassy.country})",
                f"Expiry date: {visa.expiry_date}",
                f"Days until expiry: {visa.days_until_expiry}",
                f"Renewal status: {visa.get_renewal_status_display()}",
                f"Renewal fee: {visa.fee_currency} {visa.renewal_fee}",
                f"Reminder owner: {owner}",
                "",
                "Renewal requirements:",
                requirements,
                "",
                "Please start or update the renewal process in Mining ERP.",
            ]
        )
