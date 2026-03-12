#!/usr/bin/env python3
"""
Script để chạy tất cả prompts từ CSV file và xuất kết quả
"""
import pandas as pd
import requests
import json
import time
from datetime import datetime

# Config
CSV_FILE = "Seed keyword Mondelez - Sheet1.csv"
API_URL = "http://localhost:8501/api/query"
BRANDS = ["Mondelez", "Nestlé", "Mars", "PepsiCo", "Orion"]
ENGINES = ["chatgpt", "gemini", "claude", "perplexity"]
OUTPUT_DIR = "output"

def load_prompts(csv_file):
    """Đọc prompts từ CSV file"""
    df = pd.read_csv(csv_file, skiprows=7)  # Skip header rows

    # Lọc các row có prompt (bỏ header và empty rows)
    df = df.dropna(subset=[df.columns[1]])  # Column 2: AI Query Style

    prompts = []
    for idx, row in df.iterrows():
        keyword = row[df.columns[0]]
        ai_query_en = row[df.columns[1]]
        ai_query_vi = row[df.columns[2]] if pd.notna(row[df.columns[2]]) else None
        natural_vi = row[df.columns[3]] if pd.notna(row[df.columns[3]]) else None

        # Bỏ qua category headers
        if pd.isna(ai_query_en) or str(ai_query_en).strip() == "":
            continue

        prompts.append({
            "keyword": keyword,
            "prompt_en": ai_query_en,
            "prompt_vi": ai_query_vi,
            "prompt_natural_vi": natural_vi
        })

    return prompts

def test_prompt(prompt_text, engines, brands):
    """Gọi API để test một prompt"""
    try:
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
            print(f"❌ Error: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None

def export_results(all_results, output_file):
    """Xuất kết quả ra CSV"""
    rows = []

    for item in all_results:
        keyword = item["keyword"]
        prompt = item["prompt"]
        results = item["results"]

        for result in results:
            engine = result.get("engine", "")
            brands_data = result.get("brands", [])
            response_text = result.get("response", "")
            error = result.get("error", "")

            for brand_data in brands_data:
                brand = brand_data.get("brand", "")
                mentioned = "Yes" if brand_data.get("mentioned") else "No"
                rank = brand_data.get("rank", "")
                rank_score = brand_data.get("rank_score", 0)
                sources = ", ".join(brand_data.get("sources", []))

                rows.append({
                    "Keyword": keyword,
                    "Prompt": prompt,
                    "AI Engine": engine,
                    "Brand": brand,
                    "Mentioned": mentioned,
                    "Rank": rank if rank else "",
                    "Rank Score": rank_score,
                    "Sources": sources,
                    "Response": response_text[:500] if response_text else "",  # Truncate
                    "Error": error
                })

    df = pd.DataFrame(rows)
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ Exported to: {output_file}")
    return df

def main():
    print("🚀 Starting bulk prompt testing...")
    print(f"📁 Reading: {CSV_FILE}")

    # Load prompts
    prompts = load_prompts(CSV_FILE)
    print(f"📊 Found {len(prompts)} prompts")

    # Ask user which language to use
    print("\nChọn ngôn ngữ prompt:")
    print("1. English (AI Query Style)")
    print("2. Tiếng Việt (AI Query Style)")
    print("3. Tiếng Việt (Natural)")
    choice = input("Chọn (1/2/3): ").strip()

    prompt_key = {
        "1": "prompt_en",
        "2": "prompt_vi",
        "3": "prompt_natural_vi"
    }.get(choice, "prompt_en")

    # Process prompts
    all_results = []
    total = len(prompts)

    for i, prompt_data in enumerate(prompts, 1):
        keyword = prompt_data["keyword"]
        prompt_text = prompt_data[prompt_key]

        if not prompt_text or pd.isna(prompt_text):
            print(f"⚠️  [{i}/{total}] Skipping {keyword} - No prompt")
            continue

        print(f"\n🔄 [{i}/{total}] Testing: {keyword}")
        print(f"   Prompt: {prompt_text[:80]}...")

        result = test_prompt(prompt_text, ENGINES, BRANDS)

        if result:
            all_results.append({
                "keyword": keyword,
                "prompt": prompt_text,
                "results": result.get("results", [])
            })
            print(f"   ✅ Completed")
        else:
            print(f"   ❌ Failed")

        # Delay để tránh rate limit
        if i < total:
            time.sleep(2)

    # Export results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"{OUTPUT_DIR}/mondelez_results_{timestamp}.csv"

    df = export_results(all_results, output_file)

    print(f"\n✅ Done! Tested {len(all_results)}/{total} prompts")
    print(f"📊 Results: {len(df)} rows")
    print(f"💾 Output: {output_file}")

if __name__ == "__main__":
    main()
