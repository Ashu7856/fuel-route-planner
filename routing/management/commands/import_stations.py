"""Load the OPIS fuel price CSV into the database.

* drops non-US rows (the file includes Canadian provinces),
* collapses duplicate truckstop IDs (keeping the lowest listed price),
* geocodes each station offline by city/state (the CSV has no coordinates).
"""
import csv
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from routing.models import FuelStation
from routing.services.gazetteer import lookup

US_STATES = set(
    "AL AR AZ CA CO CT DE FL GA IA ID IL IN KS KY LA MA MD ME MI MN MO MS MT NC ND NE "
    "NH NJ NM NV NY OH OK OR PA RI SC SD TN TX UT VA VT WA WI WV WY DC".split()
)


class Command(BaseCommand):
    help = "Import fuel stations from the OPIS CSV"

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_path", nargs="?",
            default=str(Path(settings.BASE_DIR) / "data" / "fuel-prices-for-be-assessment.csv"),
        )

    @transaction.atomic
    def handle(self, csv_path, **opts):
        best: dict[int, dict] = {}
        skipped_non_us = skipped_geo = 0
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                state = row["State"].strip().upper()
                if state not in US_STATES:
                    skipped_non_us += 1
                    continue
                oid = int(row["OPIS Truckstop ID"])
                price = Decimal(row["Retail Price"]).quantize(Decimal("0.001"))
                if oid in best and best[oid]["price"] <= price:
                    continue
                pt = lookup(row["City"], state)
                if pt is None:
                    skipped_geo += 1
                    continue
                best[oid] = dict(
                    opis_id=oid, name=row["Truckstop Name"].strip(), address=row["Address"].strip(),
                    city=row["City"].strip(), state=state, price=price, lat=pt[0], lng=pt[1],
                )
        FuelStation.objects.all().delete()
        FuelStation.objects.bulk_create(FuelStation(**d) for d in best.values())
        self.stdout.write(self.style.SUCCESS(
            f"Imported {len(best)} stations (skipped {skipped_non_us} non-US rows, "
            f"{skipped_geo} un-geocodable)."))
