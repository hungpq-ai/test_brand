"""One-time script to import existing results CSV files into SQLite database."""
import glob
import os
import pandas as pd
from db import init_db, insert_results

init_db()
output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
pattern = os.path.join(output_dir, "results_*.csv")

total_imported = 0
for csv_path in sorted(glob.glob(pattern)):
    filename = os.path.basename(csv_path)
    timestamp = filename.replace("results_", "").replace(".csv", "")

    df = pd.read_csv(csv_path)
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "Query": row.get("Query", ""),
            "AI Engine": row.get("AI Engine", ""),
            "Brand": row.get("Brand", ""),
            "Mention": row.get("Mention", "No"),
            "Rank": row.get("Rank") if pd.notna(row.get("Rank")) else None,
            "Ranking Score": row.get("Ranking Score", 0),
            "Citation Type": row.get("Citation Type", "none"),
            "Citation Score": row.get("Citation Score", 0),
            "Source": row.get("Source", "") if pd.notna(row.get("Source", "")) else "",
            "Error": row.get("Error") if pd.notna(row.get("Error")) else None,
        })

    if rows:
        insert_results(rows, timestamp, source="batch")
        total_imported += len(rows)
        print(f"Imported {len(rows)} rows from {filename}")

print(f"\nMigration complete. Total: {total_imported} rows imported.")
