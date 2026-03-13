#!/usr/bin/env python3
"""Simple standalone runner - No complex dependencies"""
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
import json
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from engines.gemini import GeminiEngine
from engines.perplexity import PerplexityEngine
from engines.chatgpt import ChatGPTEngine
from engines.claude import ClaudeEngine


def analyze_brand_mention(brand, response_text, citations):
    """Simple brand analysis"""
    # Check if brand is mentioned
    mentioned = brand.lower() in response_text.lower()

    # Extract rank (look for numbered lists)
    rank = None
    if mentioned:
        # Pattern: "1. Brand" or "1) Brand" or "1 - Brand"
        # Only match 1-2 digit numbers to avoid matching years (2014, 2022, etc)
        pattern = rf'(\d{{1,2}})[\.\)\-\s]+.*?{re.escape(brand)}'
        match = re.search(pattern, response_text, re.IGNORECASE)
        if match:
            potential_rank = int(match.group(1))
            # Only accept ranks 1-20 (filter out years like 2014, 2022)
            if 1 <= potential_rank <= 20:
                rank = potential_rank

    # Ranking score
    ranking_score = 0
    if rank:
        score_map = {1: 100, 2: 80, 3: 60, 4: 40, 5: 20}
        ranking_score = score_map.get(rank, 10 if rank <= 10 else 0)

    # Citation analysis
    citation_type = "none"
    citation_score = 0

    if citations:
        # Check for official domain
        official_domains = {
            "Mondelez": "mondelezinternational.com",
            "Nestlé": "nestle.com",
            "Mars": "mars.com",
            "PepsiCo": "pepsico.com",
            "Orion": "orionworld.com"
        }

        official_domain = official_domains.get(brand, "")
        has_official = any(official_domain in cite for cite in citations)

        if has_official:
            citation_type = "official"
            citation_score = 100
        else:
            citation_type = "other"
            citation_score = 50

    return {
        "mentioned": mentioned,
        "rank": rank,
        "ranking_score": ranking_score,
        "citation_type": citation_type,
        "citation_score": citation_score
    }


def extract_prompts(csv_path):
    """Extract prompts from CSV"""
    print(f"📖 Reading: {csv_path}")
    df = pd.read_csv(csv_path)

    prompts = []
    # Columns: Brand, Đối thủ, Unnamed: 2, Unnamed: 3
    # These contain: Keyword, EN prompt, VN formal, VN natural

    for idx, row in df.iterrows():
        if idx < 7:  # Skip first 7 header rows
            continue

        # Extract from all 4 columns (skip column 0 which is keyword)
        for col_idx in [1, 2, 3]:  # Đối thủ, Unnamed: 2, Unnamed: 3
            col_name = df.columns[col_idx]
            val = row[col_name]

            if pd.notna(val):
                prompt = str(val).strip()
                # Skip section headers and column names
                if prompt and not prompt.startswith(('Commercial', 'Comparison', 'Brand', 'Informational', 'Keyword', 'AI Query')):
                    if prompt not in prompts:
                        prompts.append(prompt)

    print(f"✓ Found {len(prompts)} prompts\n")
    return prompts


async def run_test(prompts, brands, engines, output_dir):
    """Run monitoring"""
    print("="*80)
    print("MONITORING TEST")
    print("="*80)
    print(f"Prompts: {len(prompts)}")
    print(f"Engines: {len(engines)}")
    print(f"Brands: {len(brands)}")
    print("="*80)
    print()

    results = []
    completed = 0
    errors = 0

    for prompt_idx, prompt in enumerate(prompts, 1):
        print(f"\n[{prompt_idx}/{len(prompts)}] {prompt[:60]}...")

        for engine in engines:
            try:
                print(f"  {engine.name:12} ", end="", flush=True)
                response = await engine.query(prompt)

                for brand in brands:
                    analysis = analyze_brand_mention(brand, response.response_text, response.citations)

                    results.append({
                        "Query": prompt,
                        "AI Engine": engine.name,
                        "Brand": brand,
                        "Mention": "Yes" if analysis["mentioned"] else "No",
                        "Rank": analysis["rank"] if analysis["rank"] else "",
                        "Ranking Score": analysis["ranking_score"],
                        "Citation Type": analysis["citation_type"],
                        "Citation Score": analysis["citation_score"],
                        "Source": "; ".join(response.citations[:5]) if response.citations else ""
                    })

                print(f"✓ ({len(response.citations)})")
                completed += 1

            except Exception as e:
                print(f"✗ {str(e)[:50]}")
                errors += 1
                for brand in brands:
                    results.append({
                        "Query": prompt,
                        "AI Engine": engine.name,
                        "Brand": brand,
                        "Mention": "No",
                        "Rank": "",
                        "Ranking Score": 0,
                        "Citation Type": "none",
                        "Citation Score": 0,
                        "Source": ""
                    })

    # Save
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(output_dir, exist_ok=True)

    # Combined results
    results_file = f"{output_dir}/results_{timestamp}.csv"
    df = pd.DataFrame(results)
    df.to_csv(results_file, index=False)
    print(f"\n✓ Saved: {results_file}")

    # Brand-specific files
    for brand in brands:
        brand_data = [r for r in results if r["Brand"] == brand]
        brand_file = f"{output_dir}/{brand}_{timestamp}.csv"
        pd.DataFrame(brand_data).to_csv(brand_file, index=False)
        print(f"✓ Saved: {brand_file}")

    print(f"\n✅ Complete! {completed} queries, {errors} errors")
    return results_file


async def main():
    CSV_PATH = "Seed keyword Mondelez - Sheet1.csv"
    OUTPUT_DIR = "output"
    BRANDS = ["Mondelez", "Nestlé", "Mars", "PepsiCo", "Orion"]

    prompts = extract_prompts(CSV_PATH)

    print("🤖 Init engines...")
    engines = [
        GeminiEngine(model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"), rpm=10),
        PerplexityEngine(model=os.getenv("PERPLEXITY_MODEL", "sonar"), rpm=3),
        ChatGPTEngine(model=os.getenv("YESCALE_GPT_MODEL", "gpt-5.1"), rpm=20),
        ClaudeEngine(model=os.getenv("YESCALE_CLAUDE_MODEL", "claude-sonnet-4.5"), rpm=20),
    ]
    print(f"✓ Ready\n")

    await run_test(prompts, BRANDS, engines, OUTPUT_DIR)


if __name__ == "__main__":
    asyncio.run(main())
