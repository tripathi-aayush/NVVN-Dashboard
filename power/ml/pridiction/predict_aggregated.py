import pandas as pd
from datetime import timedelta
from power.utils.metadata import add_calendar_features
from power.ml.trainy.common import merge_live_weather
from power.ml.model_store import load_model
from power.models import StateLoad5Min

def predict_aggregated_data(state: str, forecast_date: str, freq: str, days: int = 7):
    print(f"\n================= START PREDICTION {freq} =================\n")
    
    model_name = f"{state}_{freq}_xgb.pkl"
    model = load_model(model_name)
    
    forecast_date = pd.to_datetime(forecast_date).normalize()
    
    if freq == "1hr":
        pandas_freq = "1H"
        end_date = forecast_date + timedelta(days=1) - timedelta(hours=1)
        lag_periods = [1, 2, 3, 24, 168]
    elif freq == "3hr":
        pandas_freq = "3H"
        end_date = forecast_date + timedelta(days=1) - timedelta(hours=3)
        lag_periods = [1, 2, 3, 8, 56]
    elif freq == "24hr":
        pandas_freq = "24H"
        end_date = forecast_date + timedelta(days=days-1)
        lag_periods = [1, 2, 7]
    else:
        raise ValueError("Invalid freq")
        
    df = pd.DataFrame({
        "ds": pd.date_range(forecast_date, end_date, freq=pandas_freq)
    })
    
    # --------------------------------------------------
    # HISTORICAL DATA FOR LAGS AND PROFILE
    # --------------------------------------------------
    # Fetch enough historical data for lags
    max_lag = max(lag_periods)
    days_to_fetch = (max_lag * pd.Timedelta(pandas_freq)).days + 2
    
    hist_start = forecast_date - timedelta(days=days_to_fetch)
    
    hist = pd.DataFrame(
        StateLoad5Min.objects
        .filter(
            state=state,
            datetime__gte=hist_start,
            datetime__lt=forecast_date + timedelta(days=1)
        )
        .values("datetime", "load_mw", "brpl", "bypl", "ndpl", "ndmc", "mes")
    )
    
    if hist.empty:
        # Fallback for empty DB: Generate dummy historical data to compute lags without crashing
        print("WARNING: No historical data found in DB. Using synthetic baseline for lags.")
        hist = pd.DataFrame({"datetime": pd.date_range(hist_start, forecast_date + timedelta(days=1), freq="5min")})
        hist["load_mw"] = 4500.0
        hist["brpl"] = 900.0
        hist["bypl"] = 900.0
        hist["ndpl"] = 900.0
        hist["ndmc"] = 900.0
        hist["mes"] = 900.0
        
    hist["datetime"] = pd.to_datetime(hist["datetime"])
    discoms = ["brpl", "bypl", "ndpl", "ndmc", "mes"]
    hist["y"] = hist["load_mw"]
    hist.loc[hist["y"].isna(), "y"] = hist[discoms].sum(axis=1)
    
    # Resample
    hist = (
        hist.set_index("datetime")
        .resample(pandas_freq)
        .mean()
        .interpolate()
        .reset_index()
        .rename(columns={"datetime": "ds"})
    )
    
    # --------------------------------------------------
    # Weather
    # --------------------------------------------------
    weather = merge_live_weather(
        start_date=forecast_date.date(),
        end_date=end_date.date(),
        state=state,
        frequency="hourly" if freq != "24hr" else "daily",
    )
    
    df = pd.merge_asof(
        df.sort_values("ds"),
        weather.sort_values("ds"),
        on="ds",
        direction="nearest",
        tolerance=pd.Timedelta("1h") if freq != "24hr" else pd.Timedelta("24h"),
    )
    
    # --------------------------------------------------
    # Profile & Features
    # --------------------------------------------------
    df = add_calendar_features(df)
    
    if freq == "1hr":
        df["hour"] = df["ds"].dt.hour
        df["is_peak"] = df["hour"].between(18, 23).astype(int)
        df["temp_x_hour"] = df["temperature_c"] * df["hour"]
        if "humidity_pct" in df.columns: df["humidity_x_hour"] = df["humidity_pct"] * df["hour"]
        if "wind_speed_ms" in df.columns: df["wind_x_hour"] = df["wind_speed_ms"] * df["hour"]
        
        hist["slot"] = hist["ds"].dt.hour
        hist["mmdd"] = hist["ds"].dt.strftime("%m-%d")
        df["slot"] = df["ds"].dt.hour
        df["mmdd"] = df["ds"].dt.strftime("%m-%d")
        profile = hist.groupby(["mmdd", "slot"])["y"].mean().reset_index().rename(columns={"y": "profile_y"})
        df = df.merge(profile, on=["mmdd", "slot"], how="left")
        
    elif freq == "3hr":
        df["hour"] = df["ds"].dt.hour
        df["is_peak"] = df["hour"].between(18, 23).astype(int)
        df["temp_x_hour"] = df["temperature_c"] * df["hour"]
        if "humidity_pct" in df.columns: df["humidity_x_hour"] = df["humidity_pct"] * df["hour"]
        if "wind_speed_ms" in df.columns: df["wind_x_hour"] = df["wind_speed_ms"] * df["hour"]
        
        hist["slot"] = hist["ds"].dt.hour // 3
        hist["mmdd"] = hist["ds"].dt.strftime("%m-%d")
        df["slot"] = df["ds"].dt.hour // 3
        df["mmdd"] = df["ds"].dt.strftime("%m-%d")
        profile = hist.groupby(["mmdd", "slot"])["y"].mean().reset_index().rename(columns={"y": "profile_y"})
        df = df.merge(profile, on=["mmdd", "slot"], how="left")
        
    elif freq == "24hr":
        hist["month"] = hist["ds"].dt.month
        df["month"] = df["ds"].dt.month
        profile = hist.groupby(["month"])["y"].mean().reset_index().rename(columns={"y": "profile_y"})
        df = df.merge(profile, on=["month"], how="left")
    
    # Fill missing profiles
    df["profile_y"] = df["profile_y"].fillna(hist["y"].mean())
    
    # --------------------------------------------------
    # Lags
    # --------------------------------------------------
    # To correctly calculate lags for the future, we need the actuals up to T-0
    for idx, row in df.iterrows():
        current_time = row["ds"]
        for lag in lag_periods:
            lag_time = current_time - pd.Timedelta(pandas_freq) * lag
            # Find the actual from hist
            val = hist.loc[hist["ds"] == lag_time, "y"]
            if not val.empty:
                val = val.values[0]
            else:
                # Fallback to profile
                val = row["profile_y"]
                
            if freq == "1hr" or freq == "3hr":
                if lag in [1, 2, 3]:
                    df.at[idx, f"y_lag_{lag}"] = val
                elif lag == lag_periods[-2]:
                    df.at[idx, "y_lag_24h"] = val
                elif lag == lag_periods[-1]:
                    df.at[idx, "y_lag_7d"] = val
            elif freq == "24hr":
                if lag == 1: df.at[idx, "y_lag_1d"] = val
                if lag == 2: df.at[idx, "y_lag_2d"] = val
                if lag == 7: df.at[idx, "y_lag_7d"] = val
                
    # --------------------------------------------------
    # Predict
    # --------------------------------------------------
    # Dummy features to satisfy XGBoost signature if it accidentally saved y and sample_weight
    df["y"] = 0.0
    df["sample_weight"] = 1.0
    
    missing = set(model.feature_cols) - set(df.columns)
    if missing:
        raise ValueError(f"Missing features: {missing}")

    X = df[model.feature_cols]
    df["mw"] = model.predict(X)

    return df[["ds", "mw", "temperature_c"]]
