#!/usr/bin/env python3
"""
AI Brand Monitoring Tool

Sends prompts to multiple AI engines and extracts brand mention data.
Output: CSV with columns: prompt | engine | brand | mentioned | rank | sources

Usage:
    python main.py
    python main.py --prompts prompts.csv --config config.yaml
    python main.py --engines chatgpt,claude --brands "Magenest,Shopify"
    python main.py --dry-run
"""

import argparse
import asyncio
import csv
import os
import sys

import yaml
from dotenv import load_dotenv

from engines import ChatGPTEngine, GeminiEngine, ClaudeEngine, PerplexityEngine
from engines.base import BaseEngine


def load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_prompts(csv_path: str) -> list[str]:
    prompts = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            prompt = row.get("prompt", "").strip().strip('"')
            if prompt:
                prompts.append(prompt)
    return prompts


ENGINE_CLASSES = {
    "chatgpt": ChatGPTEngine,
    "gemini": GeminiEngine,
    "claude": ClaudeEngine,
    "perplexity": PerplexityEngine,
}


def create_engines(config: dict, engine_filter: list[str] | None = None) -> list[BaseEngine]:
    engines = []
    engine_configs = config.get("engines", {})

    for name, cls in ENGINE_CLASSES.items():
        if engine_filter and name not in engine_filter:
            continue

        eng_cfg = engine_configs.get(name, {})
        if not eng_cfg.get("enabled", True):
            continue

        model = eng_cfg.get("model", cls.__init__.__defaults__[0] if cls.__init__.__defaults__ else None)
        rpm = eng_cfg.get("rpm", 60)

        try:
            engine = cls(model=model, rpm=rpm)
            engines.append(engine)
            print(f"  Initialized: {name} (model={model}, rpm={rpm})")
        except Exception as e:
            print(f"  WARNING: Failed to init {name}: {e}")

    return engines


def main():
    parser = argparse.ArgumentParser(description="AI Brand Monitoring Tool")
    parser.add_argument("--prompts", default="prompts.csv", help="Path to prompts CSV file")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    parser.add_argument("--brands", help="Comma-separated brand names (overrides config)")
    parser.add_argument("--engines", help="Comma-separated engine names: chatgpt,gemini,claude,perplexity")
    parser.add_argument("--output", help="Output directory (overrides config)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without calling APIs")
    args = parser.parse_args()

    # Load environment
    load_dotenv()

    # Load config
    config = load_config(args.config)

    # Load prompts
    prompts = load_prompts(args.prompts)
    if not prompts:
        print("ERROR: No prompts found in", args.prompts)
        sys.exit(1)
    print(f"\nLoaded {len(prompts)} prompts")

    # Brands
    if args.brands:
        brands = [b.strip() for b in args.brands.split(",")]
    else:
        brands = config.get("brands", [])
    if not brands:
        print("ERROR: No brands specified. Use --brands or set in config.yaml")
        sys.exit(1)
    print(f"Tracking brands: {', '.join(brands)}")

    # Engine filter
    engine_filter = None
    if args.engines:
        engine_filter = [e.strip() for e in args.engines.split(",")]

    # Initialize engines
    print("\nInitializing engines:")
    engines = create_engines(config, engine_filter)
    if not engines:
        print("ERROR: No engines available. Check API keys and config.")
        sys.exit(1)

    # Output dir
    output_dir = args.output or config.get("output", {}).get("dir", "output")
    save_raw = config.get("output", {}).get("save_raw_responses", True)

    # Summary
    total_calls = len(prompts) * len(engines)
    print(f"\nTotal API calls: {total_calls} ({len(prompts)} prompts x {len(engines)} engines)")

    if args.dry_run:
        print("\n[DRY RUN] Would send the following:")
        for p in prompts[:5]:
            for e in engines:
                print(f"  {e.name}: {p[:60]}...")
        if len(prompts) > 5:
            print(f"  ... and {(len(prompts) - 5) * len(engines)} more calls")
        return

    # Run
    print("\nStarting queries...\n")
    from runner import run_all

    df = asyncio.run(run_all(prompts, engines, brands, output_dir, save_raw))

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if not df.empty:
        mentioned = df[df["Mention"] == "Yes"]
        print(f"\nTotal rows: {len(df)}")
        print(f"Brand mentions found: {len(mentioned)}")

        print("\nMentions by engine:")
        for engine in df["AI Engine"].unique():
            eng_mentions = mentioned[mentioned["AI Engine"] == engine]
            print(f"  {engine}: {len(eng_mentions)} mentions")

        print("\nMentions by brand:")
        for brand in brands:
            brand_mentions = mentioned[mentioned["Brand"] == brand]
            if not brand_mentions.empty:
                avg_rank = brand_mentions["Rank"].mean()
                avg_ranking_score = brand_mentions["Ranking Score"].mean()
                print(f"  {brand}: {len(brand_mentions)} mentions, avg rank: {avg_rank:.1f}, avg ranking score: {avg_ranking_score:.1f}")
            else:
                print(f"  {brand}: 0 mentions")

    print("\nDone!")


if __name__ == "__main__":
    main()
