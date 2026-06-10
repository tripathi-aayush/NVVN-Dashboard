import os
import pandas as pd
from power.ml.models.xgb_model import train_xgb_model
from power.ml.progress import log_progress
from power.ml.trainy.common import clean_outliers, merge_live_weather
from power.models import StateLoad5Min, Weather
from power.utils.logger import get_logger
from power.utils.metadata import add_calendar_features

# ----------------------------------
# SAMPLE WEIGHT
# ----------------------------------
def add_sample_weight(df: pd.DataFrame) -> pd.DataFrame:
    # Give slight weight to winter vs summer if needed, here just 1.0
    df["sample_weight"] = 1.0
    return df


# ----------------------------------
# TRAIN FUNCTION
# ----------------------------------
def train_state_24hr_model(state: str):
    logger = get_logger(f"TRAIN-24H-{state}")
    log_progress(logger, "Fetching raw data", "xgboost", 5)

    raw = pd.DataFrame(
        StateLoad5Min.objects
        .filter(state=state)
        .values("datetime", "load_mw", "brpl", "bypl", "ndpl", "ndmc", "mes")
        .order_by("datetime")
    )

    if raw.empty:
        raise ValueError(f"No data for state={state}")
    
    raw = raw.sort_values("datetime")
    raw["datetime"] = pd.to_datetime(raw["datetime"])

    # -----------------------------
    # TARGET
    # -----------------------------
    discoms = ["brpl", "bypl", "ndpl", "ndmc", "mes"]
    raw["y"] = raw["load_mw"]
    raw.loc[raw["y"].isna(), "y"] = raw[discoms].sum(axis=1)

    # -----------------------------
    # RESAMPLE TO 24 HOURS (DAILY)
    # -----------------------------
    df = (
        raw.set_index("datetime")
        .resample("24H")
        .mean()
        .interpolate()
        .reset_index()
        .rename(columns={"datetime": "ds"})
    )

    # -----------------------------
    # WEATHER (DB BASED)
    # -----------------------------
    log_progress(logger, "Preparing weather", "xgboost", 30)

    start_dt = df["ds"].min()
    end_dt = df["ds"].max()

    weather_qs = Weather.objects.filter(
        state=state,
        datetime__gte=start_dt,
        datetime__lte=end_dt,
    ).order_by("datetime")

    if not weather_qs.exists():
        weather = merge_live_weather(
            start_date=start_dt.date(),
            end_date=end_dt.date(),
            state=state,
            frequency="daily",
        )
        weather_objects = [
            Weather(
                state=state,
                datetime=row["ds"],
                frequency="daily",
                temperature_c=row["temperature_c"],
                humidity_pct=row.get("humidity_pct"),
                rain_mm=row.get("rain_mm"),
                wind_speed_ms=row.get("wind_speed_ms"),
                source="open-meteo",
            )
            for _, row in weather.iterrows()
        ]
        Weather.objects.bulk_create(weather_objects, ignore_conflicts=True)

    weather = pd.DataFrame(
        Weather.objects.filter(
            state=state,
            datetime__gte=start_dt,
            datetime__lte=end_dt,
        )
        .order_by("datetime")
        .values(
            "datetime",
            "temperature_c",
            "humidity_pct",
            "rain_mm",
            "wind_speed_ms",
        )
    )

    weather = weather.rename(columns={"datetime": "ds"})
    weather["ds"] = pd.to_datetime(weather["ds"]).dt.tz_localize(None)

    # resample weather to daily just to be safe
    weather = weather.set_index("ds").resample("24H").mean().reset_index()

    df["ds"] = df["ds"].dt.tz_localize(None)

    df = pd.merge_asof(
        df.sort_values("ds"),
        weather.sort_values("ds"),
        on="ds",
        direction="nearest",
        tolerance=pd.Timedelta("24h"),
    )

    # -----------------------------
    # CALENDAR
    # -----------------------------
    df = add_calendar_features(df)

    # -----------------------------
    # DATE PROFILE
    # -----------------------------
    df["month"] = df["ds"].dt.month

    profile = (
        df.groupby(["month"])["y"]
        .mean()
        .reset_index()
        .rename(columns={"y": "profile_y"})
    )

    df = df.merge(profile, on=["month"], how="left")

    # -----------------------------
    # OUTLIERS
    # -----------------------------
    df = clean_outliers(df)

    # -----------------------------
    # LAGS FOR 24 HOUR
    # -----------------------------
    df["y_lag_1d"] = df["y"].shift(1)
    df["y_lag_2d"] = df["y"].shift(2)
    df["y_lag_7d"] = df["y"].shift(7)

    df = add_sample_weight(df)
    
    feature_cols = [
        "y", "temperature_c", "humidity_pct", "rain_mm", "wind_speed_ms",
        "is_weekend", "is_holiday", "season", "profile_y",
        "y_lag_1d", "y_lag_2d", "y_lag_7d", "sample_weight"
    ]
    df = df.dropna(subset=feature_cols).reset_index(drop=True)

    print("TRAIN ROWS 24H:", len(df), "COLS:", df.shape[1])

    # -----------------------------
    # TRAIN
    # -----------------------------
    log_progress(logger, "Training started", "xgboost", 60)
    model = train_xgb_model(df, feature_cols=feature_cols)
    model.frequency = "24hr"
    log_progress(logger, "Training completed", "xgboost", 100)

    return model
