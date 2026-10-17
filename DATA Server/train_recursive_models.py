import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor


# -------------------------------------------------
# Helper: convert freq string like "1s" to seconds
# -------------------------------------------------
def _freq_seconds(freq: str) -> int:
    freq = freq.strip().lower()
    if not freq.endswith("s"):
        raise ValueError(f"Only second-based freq supported, got {freq!r}")
    return int(freq[:-1])


# -------------------------------------------------
# Feature engineering – MUST match the logic used
# in your Streamlit/realtime code
# -------------------------------------------------
def _make_features_recursive(prepared: pd.DataFrame, freq: str, win_s: int, lags_s) -> pd.DataFrame:
    """
    prepared: DataFrame indexed by timestamp, numeric columns = raw sensor signals
    """
    df = prepared.copy()
    df = df.asfreq(freq)  # regular grid
    df = df.infer_objects(copy=False)

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if numeric_cols:
        df[numeric_cols] = df[numeric_cols].interpolate("time").ffill().bfill()

    base_cols = df.columns.tolist()

    def add_roll(col: str):
        df[f"{col}_mean"] = df[col].rolling(f"{win_s}s").mean()
        df[f"{col}_std"] = df[col].rolling(f"{win_s}s").std()
        df[f"{col}_slope"] = df[col].diff().rolling(f"{win_s}s").mean()

    for c in base_cols:
        add_roll(c)
        for lag_sec in lags_s:
            steps = int(lag_sec / _freq_seconds(freq))
            if steps <= 0:
                continue
            df[f"{c}_lag{lag_sec}s"] = df[c].shift(steps)

    df = df.dropna()
    df = df.reset_index().rename(columns={"index": "timestamp"})
    return df


# -------------------------------------------------
# Build training features + future targets
# -------------------------------------------------
def build_feature_frame(
    df_raw: pd.DataFrame,
    freq: str,
    win_s: int,
    lags_s,
    step_s: int,
    targets,
):
    """
    df_raw: CSV loaded frame with at least [timestamp] + target columns
    Returns:
      fe: full feature frame including target_<tgt> columns
      X_all: numeric feature matrix
      feature_cols: list of feature column names (for meta["columns"])
    """
    if "timestamp" not in df_raw.columns:
        raise ValueError("CSV must contain a 'timestamp' column.")

    df = df_raw.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"])
    df = df.sort_values("timestamp")

    # Use all non-timestamp columns as base signals
    base_cols = [c for c in df.columns if c != "timestamp"]
    if not base_cols:
        raise ValueError("No sensor columns found in CSV (besides timestamp).")

    df = df.set_index("timestamp")[base_cols]
    df = df.sort_index()

    # Build rolling + lag features
    fe = _make_features_recursive(df, freq=freq, win_s=win_s, lags_s=lags_s)

    # How many rows ahead corresponds to step_s?
    step_rows = int(step_s / _freq_seconds(freq))
    if step_rows <= 0:
        raise ValueError("step_s must be >= freq")

    # Create future targets: value at t + step_s
    for tgt in targets:
        if tgt not in fe.columns:
            raise ValueError(f"Target '{tgt}' not found in data columns: {list(fe.columns)}")
        fe[f"target_{tgt}"] = fe[tgt].shift(-step_rows)

    # Drop rows where any target is NaN (not enough future horizon)
    target_cols = [f"target_{t}" for t in targets]
    fe = fe.dropna(subset=target_cols)

    # Feature matrix = everything except timestamp + target_* columns
    feature_cols = [c for c in fe.columns if c not in ["timestamp"] + target_cols]
    X_all = fe[feature_cols].select_dtypes(include=["number"])

    return fe, X_all, feature_cols


# -------------------------------------------------
# Main training function
# -------------------------------------------------
def train_recursive_models(
    csv_path: Path,
    freq: str,
    step_s: int,
    horizon_s: int,
    win_s: int,
    lags_s,
    targets,
    models_dir: Path,
    meta_path: Path = Path("model_meta_recursive.joblib"),
):
    print(f"Loading CSV: {csv_path}")
    df_raw = pd.read_csv(csv_path)

    print("Building features...")
    fe, X_all, feature_cols = build_feature_frame(
        df_raw,
        freq=freq,
        win_s=win_s,
        lags_s=lags_s,
        step_s=step_s,
        targets=targets,
    )

    models_dir.mkdir(parents=True, exist_ok=True)

    model_files = {}
    metrics = {}

    for tgt in targets:
        y_col = f"target_{tgt}"
        y = fe[y_col].astype(float)

        # Drop rows with NaNs in features or y
        mask = (~y.isna()) & (~X_all.isna().any(axis=1))
        X = X_all[mask]
        y = y[mask]

        if len(X) < 50:
            print(f"Warning: only {len(X)} training samples for target '{tgt}'. Model may be poor.")

        # Simple 80/20 split
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

        print(f"Training model for target '{tgt}' on {len(X_train)} samples, validating on {len(X_val)} samples...")

        model = XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="reg:squarederror",
            random_state=42,
            n_jobs=4,
        )

        model.fit(X_train, y_train)

        # Simple metrics
        def mae(y_true, y_pred):
            return float(np.mean(np.abs(y_true - y_pred)))

        if len(X_val) > 0:
            y_pred = model.predict(X_val)
            rss = np.sum((y_val - y_pred) ** 2)
            tss = np.sum((y_val - np.mean(y_val)) ** 2)
            r2 = 1 - rss / tss if tss != 0 else float("nan")
            metrics[tgt] = {
                "r2": float(r2),
                "mae": mae(y_val, y_pred),
            }
            print(f"  -> {tgt}: R2 = {metrics[tgt]['r2']:.4f}, MAE = {metrics[tgt]['mae']:.4f}")
        else:
            metrics[tgt] = {"r2": float("nan"), "mae": float("nan")}
            print(f"  -> {tgt}: not enough validation data to compute metrics.")

        # Save model
        model_filename = f"xgb_{tgt}.json"
        model_path = models_dir / model_filename
        model.save_model(model_path)
        model_files[tgt] = model_filename
        print(f"Saved model for '{tgt}' to {model_path}")

    # Meta needed by Streamlit + realtime service
    meta = {
        "freq": freq,
        "step_s": int(step_s),
        "horizon_s": int(horizon_s),
        "win_s": int(win_s),
        "lags_s": list(lags_s),
        "targets": list(targets),
        "columns": feature_cols,    # feature order
        "model_files": model_files, # target -> filename
        "metrics": metrics,         # training metrics (optional, just for info)
    }

    joblib.dump(meta, meta_path)
    print(f"Saved meta to {meta_path}")
    print("Done.")


# -------------------------------------------------
# CLI entry point
# -------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Train recursive XGBoost models for tailings monitoring."
    )
    parser.add_argument("--csv", required=True,
                        help="Path to training CSV with 'timestamp' + sensor columns.")
    parser.add_argument("--freq", default="1s",
                        help="Base frequency for resampling (e.g. '1s').")
    parser.add_argument("--step_s", type=int, default=60,
                        help="Step size in seconds between recursive forecasts (e.g. 60).")
    parser.add_argument("--horizon_s", type=int, default=3600,
                        help="Total forecast horizon in seconds (e.g., 18000 = 5h).")
    parser.add_argument("--win_s", type=int, default=60,
                        help="Window size (seconds) for rolling features.")
    parser.add_argument("--lags_s", default="60,120,300",
                        help="Comma-separated list of lag offsets in seconds, e.g. '60,120,300'.")
    parser.add_argument("--targets", default="level_cm,turb_ntu,flow_lpm",
                        help="Comma-separated list of target column names in the CSV.")
    parser.add_argument("--models_dir", default="models",
                        help="Directory to save model JSON files.")
    parser.add_argument("--meta_path", default="model_meta_recursive.joblib",
                        help="Path to save the meta joblib file.")

    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    lags_s = [int(x) for x in str(args.lags_s).split(",") if x.strip()]
    targets = [t.strip() for t in str(args.targets).split(",") if t.strip()]
    models_dir = Path(args.models_dir)
    meta_path = Path(args.meta_path)

    train_recursive_models(
        csv_path=csv_path,
        freq=args.freq,
        step_s=args.step_s,
        horizon_s=args.horizon_s,
        win_s=args.win_s,
        lags_s=lags_s,
        targets=targets,
        models_dir=models_dir,
        meta_path=meta_path,
    )


if __name__ == "__main__":
    main()
