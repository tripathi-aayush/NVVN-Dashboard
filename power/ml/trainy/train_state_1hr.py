import os
import pandas as pd
from power.ml.models.xgb_model import train_xgb_model
from power.ml.progress import log_progress
from power.ml.trainy.common import clean_outliers, merge_live_weather
from power.models import StateLoad5Min, Weather
from power.utils.logger import get_logger
from power.utils.metadata import add_calendar_features

# ----------------------------------
# PEAK + INTERACTION FEATURES
# ----------------------------------
def add_peak_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["hour"] = df["ds"].dt.hour
    df["is_peak"] = df["hour"].between(18, 23).astype(int)
    df["temp_x_hour"] = df["temperature_c"] * df["hour"]
    if "humidity_pct" in df.columns:
        df["humidity_x_hour"] = df["humidity_pct"] * df["hour"]
    if "wind_speed_ms" in df.columns:
        df["wind_x_hour"] = df["wind_speed_ms"] * df["hour"]
    return df

# ----------------------------------
# SAMPLE WEIGHT
# ----------------------------------
def add_sample_weight(df: pd.DataFrame) -> pd.DataFrame:
    df["sample_weight"] = df["is_peak"].map(lambda x: 3.0 if x == 1 else 1.0)
    return df


# ----------------------------------
# TRAIN FUNCTION
# ----------------------------------
def train_state_1hr_model(state: str):
    logger = get_logger(f"TRAIN-1H-{state}")
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
    # RESAMPLE TO 1 HOUR
    # -----------------------------
    df = (
        raw.set_index("datetime")
        .resample("1H")
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
            frequency="hourly",
        )
        weather_objects = [
            Weather(
                state=state,
                datetime=row["ds"],
                frequency="hourly",
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
    weather["ds"] = pd.to_datetime(weather["ds"])

    df = pd.merge_asof(
        df.sort_values("ds"),
        weather.sort_values("ds"),
        on="ds",
        direction="nearest",
        tolerance=pd.Timedelta("1h"),
    )

    # -----------------------------
    # CALENDAR + PEAK
    # -----------------------------
    df = add_calendar_features(df)
    df = add_peak_features(df)

    # -----------------------------
    # SLOT + DATE PROFILE
    # -----------------------------
    df["slot"] = df["ds"].dt.hour
    df["mmdd"] = df["ds"].dt.strftime("%m-%d")

    profile = (
        df.groupby(["mmdd", "slot"])["y"]
        .mean()
        .reset_index()
        .rename(columns={"y": "profile_y"})
    )

    df = df.merge(profile, on=["mmdd", "slot"], how="left")

    # -----------------------------
    # OUTLIERS
    # -----------------------------
    df = clean_outliers(df)

    # -----------------------------
    # LAGS FOR 1 HOUR
    # -----------------------------
    for i in range(1, 4): # Last 3 hours
        df[f"y_lag_{i}"] = df["y"].shift(i)

    df["y_lag_24h"] = df["y"].shift(24)
    df["y_lag_7d"] = df["y"].shift(168)

    df = add_sample_weight(df)
    
    feature_cols = [
        "y", "temperature_c", "humidity_pct", "rain_mm", "wind_speed_ms",
        "hour", "is_peak", "temp_x_hour", "humidity_x_hour", "wind_x_hour",
        "is_weekend", "is_holiday", "season", "profile_y",
        *[f"y_lag_{i}" for i in range(1, 4)], "y_lag_24h", "y_lag_7d", "sample_weight"
    ]
    df = df.dropna(subset=feature_cols).reset_index(drop=True)

    print("TRAIN ROWS 1H:", len(df), "COLS:", df.shape[1])

    # -----------------------------
    # TRAIN
    # -----------------------------
    log_progress(logger, "Training started", "xgboost", 60)
    model = train_xgb_model(df, feature_cols=feature_cols)
    model.frequency = "1hr"
    log_progress(logger, "Training completed", "xgboost", 100)

    return model
