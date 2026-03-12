#!/usr/bin/env python3
"""
Convert wide format CSV to spec-compliant long format
Format: Prompt | AI Engine | Brand | Mention | Rank | Rank_score | Source | AI_Visibility_Score
"""
import pandas as pd
from datetime import datetime

# Config
INPUT_FILE = "output/mondelez_test_results_20260312_133612.csv"
OUTPUT_FILE = f"output/mondelez_spec_format_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

BRANDS = ["Mondelez", "Nestlé", "Mars", "PepsiCo", "Orion"]
ENGINES = ["chatgpt", "gemini", "claude", "perplexity"]
VARIANTS = ["EN", "VI", "VN"]

def convert_to_spec_format():
    """Convert wide format to long format spec-compliant CSV"""

    print(f"📖 Reading: {INPUT_FILE}")

    # Read data (skip header rows)
    df = pd.read_csv(INPUT_FILE, skiprows=7, encoding='utf-8')

    print(f"   Loaded {len(df)} rows, {len(df.columns)} columns")

    # Storage for long format data
    long_format_data = []

    # Get base columns
    keyword_col = df.columns[0]  # "Keyword"

    # Map column indices to prompts
    prompt_cols = {
        "EN": 1,   # AI Query Style (English)
        "VI": 2,   # AI Query Style tiếng Việt
        "VN": 3    # Natural VN query
    }

    print("\n🔄 Converting to long format...")

    row_count = 0

    # Iterate through each row
    for idx, row in df.iterrows():
        keyword = row[keyword_col]

        # For each variant
        for variant in VARIANTS:
            # Get prompt text
            prompt_text = row.iloc[prompt_cols[variant]]

            # Skip if prompt is empty
            if pd.isna(prompt_text) or str(prompt_text).strip() == "":
                continue

            # For each engine and brand combination
            for engine in ENGINES:
                for brand in BRANDS:
                    # Column names with variant suffix
                    mentioned_col = f"{engine}_{brand}_Mentioned_{variant}"
                    rank_col = f"{engine}_{brand}_Rank_{variant}"
                    score_col = f"{engine}_{brand}_Score_{variant}"
                    visibility_col = f"{engine}_{brand}_AI_Visibility_{variant}"

                    # Check if columns exist
                    if mentioned_col not in df.columns:
                        continue

                    # Get values
                    mentioned = row[mentioned_col] if pd.notna(row[mentioned_col]) else ""
                    rank = row[rank_col] if pd.notna(row[rank_col]) else ""
                    rank_score = row[score_col] if pd.notna(row[score_col]) else ""
                    ai_visibility = row[visibility_col] if pd.notna(row[visibility_col]) else ""

                    # Skip rows with no data
                    if mentioned == "" and rank == "" and rank_score == "":
                        continue

                    # Add to long format
                    long_format_data.append({
                        'Prompt': prompt_text,
                        'AI Engine': engine.upper(),
                        'Brand': brand,
                        'Mention': mentioned,
                        'Rank': rank,
                        'Rank_score': rank_score,
                        'Source': "",  # Empty for now (no sources in original file)
                        'AI_Visibility_Score': ai_visibility
                    })

                    row_count += 1

                    if row_count % 100 == 0:
                        print(f"   Processed {row_count} records...")

    print(f"\n✅ Converted {row_count} records")

    # Create DataFrame
    spec_df = pd.DataFrame(long_format_data)

    # Save to CSV
    spec_df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')

    print(f"\n💾 Saved to: {OUTPUT_FILE}")
    print(f"   Total rows: {len(spec_df)}")

    # Show sample
    print("\n📋 Sample output (first 10 rows):")
    print(spec_df.head(10).to_string(index=False))

    # Show stats
    print(f"\n📊 Statistics:")
    print(f"   Unique prompts: {spec_df['Prompt'].nunique()}")
    print(f"   Engines: {spec_df['AI Engine'].unique().tolist()}")
    print(f"   Brands: {spec_df['Brand'].unique().tolist()}")
    print(f"   Total mentions (Yes): {(spec_df['Mention'] == 'Yes').sum()}")

    return OUTPUT_FILE

if __name__ == "__main__":
    print("🚀 CONVERTING TO SPEC FORMAT")
    print("="*80)

    output_file = convert_to_spec_format()

    print(f"\n✅ DONE!")
    print(f"📂 Output: {output_file}")
