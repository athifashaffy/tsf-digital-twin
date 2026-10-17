import pandas as pd

# Load raw sensor log
df = pd.read_csv("sensor_data.csv")

# Parse timestamp
df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
df = df.dropna(subset=["timestamp"])

# Map Ultrasonic to level_cm (for now: level = distance_cm)
df["level_cm"] = df["ultrasonic_cm"]

# Keep only columns used in training
cols = ["timestamp", "level_cm", "turb_ntu", "flow_lpm"]
df_out = df[cols].dropna()

# Sort by time
df_out = df_out.sort_values("timestamp")

df_out.to_csv("training_data.csv", index=False)
print("Saved training_data.csv with", len(df_out), "rows")