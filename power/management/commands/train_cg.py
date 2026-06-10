"""
Management command: train_cg
-----------------------------
Trains the XGBoost 5-minute load forecasting model for Chhattisgarh (CG)
and saves it as state_5min_CG.pkl.

Prerequisites:
  - Run `python manage.py ingest_cg` first to populate StateLoad5Min + Weather tables.

Usage:
  python manage.py train_cg
"""

import time
from django.core.management.base import BaseCommand
from power.ml.trainy.train_state_5min import train_state_5min_model
from power.ml.model_store import save_model, PATH
import os


STATE     = "CG"
MODEL_FILE = f"state_5min_{STATE}.pkl"


class Command(BaseCommand):
    help = "Train XGBoost 5-min demand forecast model for Chhattisgarh (CG)"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("\n══════════════════════════════════"))
        self.stdout.write(self.style.SUCCESS("  CG Model Training — NVVN Backend"))
        self.stdout.write(self.style.SUCCESS("══════════════════════════════════\n"))

        # ---- pre-flight checks -------------------------------------------
        from power.models import StateLoad5Min, Weather
        demand_count = StateLoad5Min.objects.filter(state=STATE).count()
        weather_count = Weather.objects.filter(state=STATE).count()

        self.stdout.write(f"📊  DB check:")
        self.stdout.write(f"   StateLoad5Min (CG) : {demand_count:,} rows")
        self.stdout.write(f"   Weather (CG)       : {weather_count:,} rows\n")

        if demand_count == 0:
            self.stdout.write(self.style.ERROR(
                "❌  No demand data found for CG.\n"
                "    Run: python manage.py ingest_cg --skip-weather\n"
            ))
            return

        if weather_count == 0:
            self.stdout.write(self.style.WARNING(
                "⚠️   No weather data in DB for CG.\n"
                "    Training will attempt to fetch from Open-Meteo (slow).\n"
                "    Recommended: run `python manage.py ingest_cg --skip-demand` first.\n"
            ))

        # ---- train -------------------------------------------------------
        self.stdout.write("🚀  Starting XGBoost training …")
        self.stdout.write("   (watch for TRAIN ROWS + COLS output below)\n")

        t_start = time.time()

        try:
            model = train_state_5min_model(STATE)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n❌  Training failed: {e}"))
            raise

        elapsed = time.time() - t_start

        # ---- save --------------------------------------------------------
        save_model(MODEL_FILE, model)
        save_path = os.path.join(PATH, MODEL_FILE)
        size_mb = os.path.getsize(save_path) / 1_048_576

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"✅  Model trained in {elapsed:.1f}s"))
        self.stdout.write(self.style.SUCCESS(f"💾  Saved → {save_path}"))
        self.stdout.write(self.style.SUCCESS(f"📦  File size: {size_mb:.2f} MB"))
        self.stdout.write(self.style.SUCCESS(f"\n🎉  {MODEL_FILE} is ready!\n"))
