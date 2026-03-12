#!/usr/bin/env python3
"""
Script test prompts từ CSV Mondelez và xuất kết quả theo đúng cấu trúc gốc
"""
import pandas as pd
import requests
import time
from datetime import datetime
import os

# Config
CSV_FILE = "Seed keyword Mondelez - Sheet1.csv"
API_URL = "http://localhost:8501/api/query"
OUTPUT_DIR = "output"

# Brands từ CSV (dòng 2-5)
BRANDS = ["Mondelez", "Nestlé", "Mars", "PepsiCo", "Orion"]

# Engines
ENGINES = ["chatgpt", "gemini", "claude", "perplexity"]

def read_csv_structure():
    """Đọc toàn bộ CSV giữ nguyên cấu trúc"""
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Header section (rows 1-7)
    header_lines = lines[:7]

    # Read data starting from row 8
    df = pd.read_csv(CSV_FILE, skiprows=7, encoding='utf-8')

    return header_lines, df

def test_prompt(prompt_text, engines, brands):
    """Test một prompt qua API"""
    try:
        print(f"      API call: {prompt_text[:60]}...")
        response = requests.post(
            API_URL,
            json={
                "prompt": prompt_text,
                "engines": engines,
                "brands": brands
            },
            timeout=120
        )

        if response.status_code == 200:
            return response.json()
        else:
            print(f"      ❌ HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"      ❌ Error: {e}")
        return None

def calculate_ai_visibility_score(brand_results):
    """
    Tính AI Visibility Score theo công thức:
    (Mention × 40%) + (Ranking × 40%) + (Citation × 20%)
    """
    if not brand_results:
        return 0

    # Mention score: brand có được mention không (0 hoặc 100)
    mention_score = 100 if brand_results.get('mentioned') else 0

    # Ranking score: 100/80/60/40/20 cho rank 1-5
    rank = brand_results.get('rank')
    rank_scores = {1: 100, 2: 80, 3: 60, 4: 40, 5: 20}
    ranking_score = rank_scores.get(rank, 0) if rank else 0

    # Citation score
    sources = brand_results.get('sources', [])
    if sources:
        # Check if có official domain (chứa tên brand)
        brand_name = brand_results.get('brand', '').lower().split()[0]
        has_official = any(brand_name in src.lower() for src in sources)
        citation_score = 100 if has_official else 50
    else:
        citation_score = 0

    # Final AI Visibility Score
    ai_visibility_score = (mention_score * 0.4) + (ranking_score * 0.4) + (citation_score * 0.2)

    return round(ai_visibility_score, 2)

def process_prompts(df):
    """Process tất cả prompts và thêm kết quả vào DataFrame"""

    # Chọn ngôn ngữ
    print("\n📋 Chọn cột prompt để test:")
    print("1. AI Query Style (English)")
    print("2. AI Query Style tiếng Việt")
    print("3. Natural VN query")
    print("4. TẤT CẢ (All 3 variants)")
    choice = input("Chọn (1/2/3/4) [default=1]: ").strip() or "1"

    if choice == "4":
        # Test all 3 variants
        prompt_cols = [1, 2, 3]
        print("✅ Sẽ test TẤT CẢ 3 variants của mỗi keyword")
    else:
        prompt_col_map = {
            "1": 1,  # Column index 1 (AI Query Style)
            "2": 2,  # Column index 2 (AI Query Style tiếng Việt)
            "3": 3   # Column index 3 (Natural VN query)
        }
        prompt_cols = [prompt_col_map.get(choice, 1)]

    # Add new columns for results
    result_columns = []
    prompt_suffixes = []

    if len(prompt_cols) > 1:
        # Multiple variants - add suffix for each
        prompt_types = {1: "EN", 2: "VI", 3: "VN"}
        prompt_suffixes = [f"_{prompt_types[col]}" for col in prompt_cols]
    else:
        # Single variant - no suffix
        prompt_suffixes = [""]

    for engine in ENGINES:
        for brand in BRANDS:
            for suffix in prompt_suffixes:
                result_columns.append(f"{engine}_{brand}_Mentioned{suffix}")
                result_columns.append(f"{engine}_{brand}_Rank{suffix}")
                result_columns.append(f"{engine}_{brand}_Score{suffix}")
                result_columns.append(f"{engine}_{brand}_AI_Visibility{suffix}")

    # Create all columns at once to avoid fragmentation
    new_cols = {col: "" for col in result_columns}
    df = df.assign(**new_cols)

    # Process each row
    total_rows = len(df)
    tested_count = 0

    for idx, row in df.iterrows():
        keyword = row.iloc[0]

        # Test each selected prompt column
        for prompt_col_idx in prompt_cols:
            prompt = row.iloc[prompt_col_idx]

            # Skip category headers and empty rows
            if pd.isna(prompt) or str(prompt).strip() == "":
                continue

            tested_count += 1

            # Determine prompt type for display
            prompt_types = {1: "EN", 2: "VI", 3: "VN"}
            prompt_type = prompt_types.get(prompt_col_idx, "")

            print(f"\n🔄 [{tested_count}] Testing: {keyword} ({prompt_type})")
            print(f"   Prompt: {prompt[:80]}...")

            # Test prompt
            result = test_prompt(prompt, ENGINES, BRANDS)

            if not result:
                print(f"   ❌ Failed")
                continue

            # Parse results
            for engine_result in result.get('results', []):
                engine = engine_result.get('engine')
                brands_data = engine_result.get('brands', [])

                for brand_data in brands_data:
                    brand = brand_data.get('brand')
                    mentioned = "Yes" if brand_data.get('mentioned') else "No"
                    rank = brand_data.get('rank', "")
                    rank_score = brand_data.get('rank_score', 0)

                    # Calculate AI Visibility Score
                    ai_visibility = calculate_ai_visibility_score(brand_data)

                    # Column suffix based on prompt type
                    suffix = f"_{prompt_type}" if len(prompt_cols) > 1 else ""

                    # Update DataFrame
                    df.at[idx, f"{engine}_{brand}_Mentioned{suffix}"] = mentioned
                    df.at[idx, f"{engine}_{brand}_Rank{suffix}"] = rank if rank else ""
                    df.at[idx, f"{engine}_{brand}_Score{suffix}"] = rank_score
                    df.at[idx, f"{engine}_{brand}_AI_Visibility{suffix}"] = ai_visibility

            print(f"   ✅ Completed")

            # Delay to avoid rate limit
            time.sleep(2)

    print(f"\n✅ Tested {tested_count} prompts")
    return df

def export_results(header_lines, df):
    """Export kết quả ra CSV với format gốc + thêm columns kết quả"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"{OUTPUT_DIR}/mondelez_test_results_{timestamp}.csv"

    # Create output directory if not exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Write header lines
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(header_lines)

    # Append DataFrame
    df.to_csv(output_file, mode='a', index=False, encoding='utf-8')

    print(f"\n💾 Exported to: {output_file}")
    return output_file

def generate_summary(df):
    """Tạo summary report"""
    print("\n" + "="*80)
    print("📊 SUMMARY REPORT - AI VISIBILITY SCORE")
    print("="*80)

    # Calculate average AI Visibility Score per brand across all engines
    for brand in BRANDS:
        scores = []
        for engine in ENGINES:
            col = f"{engine}_{brand}_AI_Visibility"
            if col in df.columns:
                scores.extend([s for s in df[col] if s != "" and pd.notna(s)])

        if scores:
            avg_score = sum(float(s) for s in scores) / len(scores)
            print(f"\n{brand:15s} - Avg AI Visibility Score: {avg_score:.2f}")

            # Breakdown by engine
            for engine in ENGINES:
                col = f"{engine}_{brand}_AI_Visibility"
                if col in df.columns:
                    engine_scores = [float(s) for s in df[col] if s != "" and pd.notna(s)]
                    if engine_scores:
                        eng_avg = sum(engine_scores) / len(engine_scores)
                        print(f"  - {engine:12s}: {eng_avg:.2f}")

    print("\n" + "="*80)

def main():
    print("🚀 MONDELEZ PROMPT TESTING")
    print(f"📁 Input: {CSV_FILE}")
    print(f"🎯 Brands: {', '.join(BRANDS)}")
    print(f"🤖 Engines: {', '.join(ENGINES)}")

    # Read CSV
    print("\n📖 Reading CSV...")
    header_lines, df = read_csv_structure()
    print(f"   Found {len(df)} rows")

    # Process prompts
    print("\n🔄 Processing prompts...")
    df = process_prompts(df)

    # Export results
    print("\n💾 Exporting results...")
    output_file = export_results(header_lines, df)

    # Generate summary
    generate_summary(df)

    print(f"\n✅ DONE! Results saved to: {output_file}")

if __name__ == "__main__":
    main()
