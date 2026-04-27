from django.core.management.base import BaseCommand
from django.utils import timezone

from payouts.models import BankAccount, LedgerEntry, Merchant


MERCHANTS = [
    {
        "name": "Chai Point",
        "bank": {
            "account_number": "1234567890123456",
            "ifsc_code": "HDFC0001234",
            "account_holder_name": "Chai Point Beverages Pvt Ltd",
        },
        "credits": [
            (500000, "Customer order #1001"),
            (250000, "Customer order #1002"),
            (175000, "Customer order #1003"),
            (320000, "Customer order #1004"),
            (410000, "Customer order #1005"),
        ],
    },
    {
        "name": "BookBazaar",
        "bank": {
            "account_number": "9876543210987654",
            "ifsc_code": "ICIC0005678",
            "account_holder_name": "BookBazaar Online Retail LLP",
        },
        "credits": [
            (1200000, "Customer order #2001"),
            (890000, "Customer order #2002"),
            (340000, "Customer order #2003"),
        ],
    },
    {
        "name": "FreshKart",
        "bank": {
            "account_number": "5566778899001122",
            "ifsc_code": "SBIN0009012",
            "account_holder_name": "FreshKart Groceries Pvt Ltd",
        },
        "credits": [
            (750000, "Customer order #3001"),
            (620000, "Customer order #3002"),
            (480000, "Customer order #3003"),
            (150000, "Customer order #3004"),
        ],
    },
]


class Command(BaseCommand):
    help = "Seed database with test merchants, bank accounts, and credit history"

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all existing data before seeding",
        )

    def handle(self, *args, **options):
        if options["flush"]:
            self.stdout.write("Flushing existing payout data...")
            LedgerEntry.objects.all().delete()
            BankAccount.objects.all().delete()
            Merchant.objects.all().delete()

        for merchant_data in MERCHANTS:
            merchant, created = Merchant.objects.get_or_create(
                name=merchant_data["name"]
            )
            verb = "Created" if created else "Found existing"
            self.stdout.write(f"  {verb} merchant: {merchant.name}")

            bank_data = merchant_data["bank"]
            BankAccount.objects.get_or_create(
                merchant=merchant,
                account_number=bank_data["account_number"],
                defaults={
                    "ifsc_code": bank_data["ifsc_code"],
                    "account_holder_name": bank_data["account_holder_name"],
                },
            )

            if created:
                for amount_paise, description in merchant_data["credits"]:
                    LedgerEntry.objects.create(
                        merchant=merchant,
                        entry_type=LedgerEntry.EntryType.CREDIT,
                        amount_paise=amount_paise,
                        description=description,
                    )

            balance = merchant.get_balance()
            self.stdout.write(
                f"    Balance: {balance['available_balance_paise']}p "
                f"(₹{balance['available_balance_paise'] / 100:.2f})"
            )

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))
