#!/usr/bin/env python3
"""
Re-run missing Claude prompts và update vào file kết quả
"""
import pandas as pd
import requests
import time
from datetime import datetime

# Config
CSV_FILE = "Seed keyword Mondelez - Sheet1.csv"
OUTPUT_FILE = "output/mondelez_test_results_20260312_133612.csv"
API_URL = "http://localhost:8501/api/query"
BRANDS = ["Mondelez", "Nestlé", "Mars", "PepsiCo", "Orion"]

def calculate_ai_visibility_score(brand_results):
    """Tính AI Visibility Score"""
    if not brand_results:
        return 0

    mention_score = 100 if brand_results.get('mentioned') else 0

    rank = brand_results.get('rank')
    rank_scores = {1: 100, 2: 80, 3: 60, 4: 40, 5: 20}
    ranking_score = rank_scores.get(rank, 0) if rank else 0

    sources = brand_results.get('sources', [])
    if sources:
        brand_name = brand_results.get('brand', '').lower().split()[0]
        has_official = any(brand_name in src.lower() for src in sources)
        citation_score = 100 if has_official else 50
    else:
        citation_score = 0

    ai_visibility_score = (mention_score * 0.4) + (ranking_score * 0.4) + (citation_score * 0.2)
    return round(ai_visibility_score, 2)

def test_prompt_claude_only(prompt_text, brands):
    """Test prompt chỉ qua Claude engine"""
    try:
        print(f"      API call (Claude only): {prompt_text[:60]}...")
        response = requests.post(
            API_URL,
            json={
                "prompt": prompt_text,
                "engines": ["claude"],  # Chỉ Claude
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

def find_missing_claude_rows(df):
    """Tìm các rows thiếu Claude results"""
    missing_rows = []

    prompt_cols = [1, 2, 3]  # EN, VI, VN
    prompt_types = {1: "EN", 2: "VI", 3: "VN"}

    for idx, row in df.iterrows():
        keyword = row.iloc[0]

        for prompt_col_idx in prompt_cols:
            prompt = row.iloc[prompt_col_idx]

            # Skip empty prompts
            if pd.isna(prompt) or str(prompt).strip() == "":
                continue

            prompt_type = prompt_types[prompt_col_idx]

            # Check if Claude data is missing for this row
            claude_col = f"claude_Mondelez_Mentioned_{prompt_type}"

            if claude_col in df.columns:
                if pd.isna(row[claude_col]) or row[claude_col] == "":
                    missing_rows.append({
                        'index': idx,
                        'keyword': keyword,
                        'prompt': prompt,
                        'prompt_type': prompt_type,
                        'prompt_col_idx': prompt_col_idx
                    })

    return missing_rows

def main():
    print("🚀 RE-RUN MISSING CLAUDE PROMPTS")
    print("="*80)

    # Read existing results
    print(f"\n📖 Reading: {OUTPUT_FILE}")
    header_lines = []
    with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
        for i in range(7):
            header_lines.append(f.readline())

    df = pd.read_csv(OUTPUT_FILE, skiprows=7, encoding='utf-8')
    print(f"   Loaded {len(df)} rows")

    # Find missing Claude rows
    print("\n🔍 Finding missing Claude prompts...")
    missing = find_missing_claude_rows(df)
    print(f"   Found {len(missing)} missing prompts")

    if len(missing) == 0:
        print("\n✅ No missing Claude prompts!")
        return

    # Show summary
    print("\n📋 Missing breakdown:")
    for ptype in ["EN", "VI", "VN"]:
        count = len([m for m in missing if m['prompt_type'] == ptype])
        print(f"   {ptype}: {count} prompts")

    # Confirm before running
    print(f"\n⚠️  Sẽ re-run {len(missing)} prompts qua Claude API")
    print(f"   Estimated time: ~{len(missing) * 15} seconds (~{len(missing) * 15 / 60:.1f} minutes)")

    # Process missing prompts
    print("\n🔄 Processing missing prompts...")
    success_count = 0

    for i, item in enumerate(missing, 1):
        idx = item['index']
        keyword = item['keyword']
        prompt = item['prompt']
        prompt_type = item['prompt_type']

        print(f"\n[{i}/{len(missing)}] {keyword} ({prompt_type})")
        print(f"   Prompt: {prompt[:80]}...")

        # Test prompt
        result = test_prompt_claude_only(prompt, BRANDS)

        if not result:
            print(f"   ❌ Failed")
            continue

        # Parse results and update DataFrame
        for engine_result in result.get('results', []):
            engine = engine_result.get('engine')
            if engine != 'claude':
                continue

            brands_data = engine_result.get('brands', [])

            for brand_data in brands_data:
                brand = brand_data.get('brand')
                mentioned = "Yes" if brand_data.get('mentioned') else "No"
                rank = brand_data.get('rank', "")
                rank_score = brand_data.get('rank_score', 0)

                # Calculate AI Visibility Score
                ai_visibility = calculate_ai_visibility_score(brand_data)

                # Update DataFrame
                suffix = f"_{prompt_type}"
                df.at[idx, f"claude_{brand}_Mentioned{suffix}"] = mentioned
                df.at[idx, f"claude_{brand}_Rank{suffix}"] = rank if rank else ""
                df.at[idx, f"claude_{brand}_Score{suffix}"] = rank_score
                df.at[idx, f"claude_{brand}_AI_Visibility{suffix}"] = ai_visibility

        print(f"   ✅ Updated")
        success_count += 1

        # Delay
        time.sleep(2)

    # Save updated file
    print(f"\n💾 Saving updated results...")

    # Write header lines
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.writelines(header_lines)

    # Append DataFrame
    df.to_csv(OUTPUT_FILE, mode='a', index=False, encoding='utf-8')

    print(f"   ✅ Saved to: {OUTPUT_FILE}")
    print(f"\n🎉 DONE!")
    print(f"   Successfully updated: {success_count}/{len(missing)} prompts")

    # Verify
    print("\n📊 Verification:")
    df_verify = pd.read_csv(OUTPUT_FILE, skiprows=7, encoding='utf-8')
    for ptype in ["EN", "VI", "VN"]:
        col = f"claude_Mondelez_Mentioned_{ptype}"
        if col in df_verify.columns:
            non_empty = df_verify[col].notna().sum()
            print(f"   Claude {ptype}: {non_empty} rows có data")

if __name__ == "__main__":
    main()
