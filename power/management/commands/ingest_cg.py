"""
Management command: ingest_cg
------------------------------
Loads Chhattisgarh (CG) power demand and weather data into the database.

Steps:
  1. Reads Demand_2023_2026_Fixed.xlsx  →  StateLoad5Min (state='CG')
  2. Reads cg_weather_combined.csv      →  Weather        (state='CG')

Usage:
  python manage.py ingest_cg
  python manage.py ingest_cg --skip-demand     (only weather)
  python manage.py ingest_cg --skip-weather    (only demand)
"""

import os
import pandas as pd
from django.core.management.base import BaseCommand
from power.models import StateLoad5Min, Weather


# ─── File paths ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(  # NVVN-backend/
    os.path.dirname(          # power/
        os.path.dirname(      # management/
            os.path.dirname(  # commands/
                os.path.abspath(__file__)
            )
        )
    )
)

DEMAND_FILE  = os.path.join(BASE_DIR, "Demand_2023_2026_Fixed.xlsx")
WEATHER_FILE = os.path.join(BASE_DIR, "cg_weather_combined.csv")

STATE        = "CG"
BATCH_SIZE   = 5000   # rows per bulk_create call — safe for SQLite


# ──────────────────────────────────────────────────────────────────────────────
class Command(BaseCommand):
    help = "Ingest CG demand (XLSX) and weather (CSV) into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-demand",
            action="store_true",
            help="Skip demand ingestion (only load weather)",
        )
        parser.add_argument(
            "--skip-weather",
            action="store_true",
            help="Skip weather ingestion (only load demand)",
        )

    # ── entry point ────────────────────────────────────────────────────────
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("\n══════════════════════════════════"))
        self.stdout.write(self.style.SUCCESS("  CG Data Ingestion — NVVN Backend"))
        self.stdout.write(self.style.SUCCESS("══════════════════════════════════\n"))

        if not options["skip_demand"]:
            self._ingest_demand()
        else:
            self.stdout.write("⏭  Skipping demand ingestion.\n")

        if not options["skip_weather"]:
            self._ingest_weather()
        else:
            self.stdout.write("⏭  Skipping weather ingestion.\n")

        self.stdout.write(self.style.SUCCESS("\n✅  All done!\n"))

    # ── demand ──────────────────────────────────────────────────────────────
    def _ingest_demand(self):
        self.stdout.write("📂 [1/2] Loading demand file …")
        self.stdout.write(f"   {DEMAND_FILE}\n")

        if not os.path.exists(DEMAND_FILE):
            self.stdout.write(self.style.ERROR(f"   ❌  File not found: {DEMAND_FILE}"))
            return

        df = pd.read_excel(DEMAND_FILE)
        df.columns = df.columns.str.strip()

        # Normalise column names (XLSX has 'Datetime', 'Demand_MW')
        df = df.rename(columns={"Datetime": "datetime", "Demand_MW": "load_mw"})
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.dropna(subset=["datetime", "load_mw"]).sort_values("datetime").reset_index(drop=True)

        total = len(df)
        self.stdout.write(f"   Found  : {total:,} rows")
        self.stdout.write(f"   Range  : {df['datetime'].min()} → {df['datetime'].max()}")
        self.stdout.write(f"   Demand : {df['load_mw'].min():.1f} – {df['load_mw'].max():.1f} MW\n")

        # ---- build ORM objects (fast, vectorised) -------------------------
        datetimes = df["datetime"].tolist()
        load_mws  = df["load_mw"].tolist()

        records = [
            StateLoad5Min(
                state=STATE,
                datetime=dt,
                load_mw=float(mw),
                brpl=None, bypl=None, ndpl=None, ndmc=None, mes=None,
            )
            for dt, mw in zip(datetimes, load_mws)
        ]

        # ---- bulk insert in batches, ignore duplicates -------------------
        inserted = 0
        for i in range(0, total, BATCH_SIZE):
            chunk = records[i : i + BATCH_SIZE]
            StateLoad5Min.objects.bulk_create(chunk, ignore_conflicts=True, batch_size=BATCH_SIZE)
            inserted += len(chunk)
            pct = inserted / total * 100
            self.stdout.write(f"   Demand → {inserted:>7,}/{total:,}  ({pct:.1f}%)", ending="\r")
            self.stdout.flush()

        self.stdout.write("")   # newline after \r
        self.stdout.write(self.style.SUCCESS(f"   ✅  Demand: {inserted:,} rows saved (state=CG)\n"))

    # ── weather ─────────────────────────────────────────────────────────────
    def _ingest_weather(self):
        self.stdout.write("🌤  [2/2] Loading weather file …")
        self.stdout.write(f"   {WEATHER_FILE}\n")

        if not os.path.exists(WEATHER_FILE):
            self.stdout.write(self.style.ERROR(f"   ❌  File not found: {WEATHER_FILE}"))
            return

        df = pd.read_csv(WEATHER_FILE)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.dropna(subset=["datetime", "temperature_c"]).sort_values("datetime").reset_index(drop=True)

        total = len(df)
        self.stdout.write(f"   Found  : {total:,} rows")
        self.stdout.write(f"   Range  : {df['datetime'].min()} → {df['datetime'].max()}")
        self.stdout.write(f"   Temp   : {df['temperature_c'].min():.1f} – {df['temperature_c'].max():.1f} °C\n")

        # ---- build ORM objects -------------------------------------------
        inserted = 0
        for i in range(0, total, BATCH_SIZE):
            chunk = df.iloc[i : i + BATCH_SIZE]

            objects = [
                Weather(
                    state=STATE,
                    datetime=row.datetime,
                    frequency="hourly",
                    temperature_c=float(row.temperature_c),
                    humidity_pct=float(row.humidity_pct)  if pd.notna(row.humidity_pct)  else None,
                    rain_mm=float(row.rain_mm)            if pd.notna(row.rain_mm)        else None,
                    wind_speed_ms=float(row.wind_speed_ms) if pd.notna(row.wind_speed_ms) else None,
                    source="open_meteo",
                )
                for row in chunk.itertuples(index=False)
            ]

            Weather.objects.bulk_create(objects, ignore_conflicts=True, batch_size=BATCH_SIZE)
            inserted += len(objects)
            pct = inserted / total * 100
            self.stdout.write(f"   Weather → {inserted:>7,}/{total:,}  ({pct:.1f}%)", ending="\r")
            self.stdout.flush()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"   ✅  Weather: {inserted:,} rows saved (state=CG)\n"))
