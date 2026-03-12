#!/usr/bin/env python3
"""
Generate Summary Report từ kết quả test Mondelez
"""
import pandas as pd
from datetime import datetime
import sys

def generate_summary_report(input_file, output_file):
    """Tạo summary report từ file kết quả"""

    # Read data (skip header rows)
    df = pd.read_csv(input_file, skiprows=7, encoding='utf-8')

    print(f"📖 Đọc file: {input_file}")
    print(f"   Rows: {len(df)}, Columns: {len(df.columns)}")

    # Constants
    BRANDS = ["Mondelez", "Nestlé", "Mars", "PepsiCo", "Orion"]
    ENGINES = ["chatgpt", "gemini", "claude", "perplexity"]
    VARIANTS = ["EN", "VI", "VN"]

    summary_data = []

    # 1. Overall Brand Performance (across all engines and variants)
    print("\n📊 Tạo Overall Brand Performance...")
    for brand in BRANDS:
        # Get all mention columns for this brand
        mention_cols = [col for col in df.columns if f"_{brand}_Mentioned" in col]
        visibility_cols = [col for col in df.columns if f"_{brand}_AI_Visibility" in col]
        rank_cols = [col for col in df.columns if f"_{brand}_Rank" in col]

        total_tests = 0
        total_mentions = 0
        total_visibility = 0
        visibility_count = 0
        ranks = []

        for col in mention_cols:
            total_tests += df[col].notna().sum()
            total_mentions += (df[col] == "Yes").sum()

        for col in visibility_cols:
            scores = pd.to_numeric(df[col], errors='coerce').dropna()
            if len(scores) > 0:
                total_visibility += scores.sum()
                visibility_count += len(scores)

        for col in rank_cols:
            valid_ranks = pd.to_numeric(df[col], errors='coerce').dropna()
            ranks.extend(valid_ranks.tolist())

        mention_rate = (total_mentions / total_tests * 100) if total_tests > 0 else 0
        avg_visibility = (total_visibility / visibility_count) if visibility_count > 0 else 0
        avg_rank = (sum(ranks) / len(ranks)) if ranks else 0

        summary_data.append({
            "Category": "Overall Performance",
            "Brand": brand,
            "Engine": "All",
            "Variant": "All",
            "Total Tests": total_tests,
            "Total Mentions": total_mentions,
            "Mention Rate (%)": round(mention_rate, 2),
            "Avg AI Visibility Score": round(avg_visibility, 2),
            "Avg Rank": round(avg_rank, 2) if avg_rank > 0 else "-",
            "Top 3 Rate (%)": round(len([r for r in ranks if r <= 3]) / len(ranks) * 100, 2) if ranks else 0
        })

    # 2. Brand Performance by Engine
    print("📊 Tạo Brand Performance by Engine...")
    for engine in ENGINES:
        for brand in BRANDS:
            mention_cols = [col for col in df.columns if f"{engine}_{brand}_Mentioned" in col]
            visibility_cols = [col for col in df.columns if f"{engine}_{brand}_AI_Visibility" in col]
            rank_cols = [col for col in df.columns if f"{engine}_{brand}_Rank" in col]

            total_tests = 0
            total_mentions = 0
            total_visibility = 0
            visibility_count = 0
            ranks = []

            for col in mention_cols:
                total_tests += df[col].notna().sum()
                total_mentions += (df[col] == "Yes").sum()

            for col in visibility_cols:
                scores = pd.to_numeric(df[col], errors='coerce').dropna()
                if len(scores) > 0:
                    total_visibility += scores.sum()
                    visibility_count += len(scores)

            for col in rank_cols:
                valid_ranks = pd.to_numeric(df[col], errors='coerce').dropna()
                ranks.extend(valid_ranks.tolist())

            if total_tests == 0:
                continue

            mention_rate = (total_mentions / total_tests * 100) if total_tests > 0 else 0
            avg_visibility = (total_visibility / visibility_count) if visibility_count > 0 else 0
            avg_rank = (sum(ranks) / len(ranks)) if ranks else 0

            summary_data.append({
                "Category": "By Engine",
                "Brand": brand,
                "Engine": engine.upper(),
                "Variant": "All",
                "Total Tests": total_tests,
                "Total Mentions": total_mentions,
                "Mention Rate (%)": round(mention_rate, 2),
                "Avg AI Visibility Score": round(avg_visibility, 2),
                "Avg Rank": round(avg_rank, 2) if avg_rank > 0 else "-",
                "Top 3 Rate (%)": round(len([r for r in ranks if r <= 3]) / len(ranks) * 100, 2) if ranks else 0
            })

    # 3. Brand Performance by Variant
    print("📊 Tạo Brand Performance by Variant...")
    for variant in VARIANTS:
        for brand in BRANDS:
            mention_cols = [col for col in df.columns if f"_{brand}_Mentioned_{variant}" in col]
            visibility_cols = [col for col in df.columns if f"_{brand}_AI_Visibility_{variant}" in col]
            rank_cols = [col for col in df.columns if f"_{brand}_Rank_{variant}" in col]

            total_tests = 0
            total_mentions = 0
            total_visibility = 0
            visibility_count = 0
            ranks = []

            for col in mention_cols:
                total_tests += df[col].notna().sum()
                total_mentions += (df[col] == "Yes").sum()

            for col in visibility_cols:
                scores = pd.to_numeric(df[col], errors='coerce').dropna()
                if len(scores) > 0:
                    total_visibility += scores.sum()
                    visibility_count += len(scores)

            for col in rank_cols:
                valid_ranks = pd.to_numeric(df[col], errors='coerce').dropna()
                ranks.extend(valid_ranks.tolist())

            if total_tests == 0:
                continue

            mention_rate = (total_mentions / total_tests * 100) if total_tests > 0 else 0
            avg_visibility = (total_visibility / visibility_count) if visibility_count > 0 else 0
            avg_rank = (sum(ranks) / len(ranks)) if ranks else 0

            summary_data.append({
                "Category": "By Language",
                "Brand": brand,
                "Engine": "All",
                "Variant": variant,
                "Total Tests": total_tests,
                "Total Mentions": total_mentions,
                "Mention Rate (%)": round(mention_rate, 2),
                "Avg AI Visibility Score": round(avg_visibility, 2),
                "Avg Rank": round(avg_rank, 2) if avg_rank > 0 else "-",
                "Top 3 Rate (%)": round(len([r for r in ranks if r <= 3]) / len(ranks) * 100, 2) if ranks else 0
            })

    # 4. Engine Performance (overall across all brands)
    print("📊 Tạo Engine Performance Summary...")
    for engine in ENGINES:
        mention_cols = [col for col in df.columns if f"{engine}_" in col and "_Mentioned_" in col]
        visibility_cols = [col for col in df.columns if f"{engine}_" in col and "_AI_Visibility_" in col]

        total_tests = 0
        total_mentions = 0
        total_visibility = 0
        visibility_count = 0

        for col in mention_cols:
            total_tests += df[col].notna().sum()
            total_mentions += (df[col] == "Yes").sum()

        for col in visibility_cols:
            scores = pd.to_numeric(df[col], errors='coerce').dropna()
            if len(scores) > 0:
                total_visibility += scores.sum()
                visibility_count += len(scores)

        if total_tests == 0:
            continue

        mention_rate = (total_mentions / total_tests * 100)
        avg_visibility = (total_visibility / visibility_count) if visibility_count > 0 else 0

        summary_data.append({
            "Category": "Engine Summary",
            "Brand": "All Brands",
            "Engine": engine.upper(),
            "Variant": "All",
            "Total Tests": total_tests,
            "Total Mentions": total_mentions,
            "Mention Rate (%)": round(mention_rate, 2),
            "Avg AI Visibility Score": round(avg_visibility, 2),
            "Avg Rank": "-",
            "Top 3 Rate (%)": "-"
        })

    # Create DataFrame and save
    summary_df = pd.DataFrame(summary_data)
    summary_df.to_csv(output_file, index=False, encoding='utf-8-sig')

    print(f"\n✅ Summary report saved to: {output_file}")
    print(f"   Total rows: {len(summary_df)}")

    # Print top performers
    print("\n" + "="*80)
    print("🏆 TOP PERFORMERS")
    print("="*80)

    overall = summary_df[summary_df["Category"] == "Overall Performance"].sort_values(
        "Avg AI Visibility Score", ascending=False
    )

    print("\nTop 3 Brands (by AI Visibility Score):")
    for idx, row in overall.head(3).iterrows():
        print(f"  {row['Brand']:15s} - Score: {row['Avg AI Visibility Score']:6.2f} | Mention Rate: {row['Mention Rate (%)']:5.2f}%")

    return summary_df


if __name__ == "__main__":
    input_file = "output/mondelez_test_results_20260312_133612.csv"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"output/mondelez_summary_report_{timestamp}.csv"

    print("🚀 GENERATING SUMMARY REPORT")
    print(f"📁 Input: {input_file}")
    print(f"📁 Output: {output_file}")

    summary_df = generate_summary_report(input_file, output_file)

    print("\n✅ DONE!")
