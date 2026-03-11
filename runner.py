import asyncio
import json
import os
from datetime import datetime

import pandas as pd

from engines.base import BaseEngine, EngineResponse
from extractor import extract_brands


async def process_one(
    engine: BaseEngine,
    prompt: str,
    brands: list[str],
) -> tuple[EngineResponse, list[dict]]:
    """Send one prompt to one engine, extract brand data."""
    response = await engine.safe_query(prompt)

    if response.error:
        # Return error rows for each brand
        rows = []
        for brand in brands:
            rows.append({
                "Query": prompt,
                "AI Engine": engine.name,
                "Brand": brand,
                "Mention": "No",
                "Rank": None,
                "Rank Score": 0,
                "Source": "",
                "Error": response.error,
            })
        return response, rows

    mentions = extract_brands(
        response.response_text,
        brands,
        extra_citations=response.citations if response.citations else None,
    )

    rows = []
    for m in mentions:
        rank_score = 0
        if m.mentioned and m.rank is not None:
            # Top 1 = 1.0, Top 2 = 0.8, Top 3 = 0.6, Top 4 = 0.4, Top 5 = 0.2, 6+ = 0.1
            if m.rank <= 5:
                rank_score = round(1 - (m.rank - 1) * 0.2, 2)
            else:
                rank_score = 0.1
        elif m.mentioned and m.rank is None:
            rank_score = 0.1  # Mentioned but not in a list

        rows.append({
            "Query": prompt,
            "AI Engine": engine.name,
            "Brand": m.brand,
            "Mention": "Yes" if m.mentioned else "No",
            "Rank": m.rank,
            "Rank Score": rank_score,
            "Source": "; ".join(m.sources) if m.sources else "",
            "Error": None,
        })

    return response, rows


async def run_all(
    prompts: list[str],
    engines: list[BaseEngine],
    brands: list[str],
    output_dir: str = "output",
    save_raw: bool = True,
) -> pd.DataFrame:
    """Run all prompts against all engines and collect results."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_rows = []
    raw_responses = []
    total = len(prompts) * len(engines)
    completed = 0

    # Create tasks grouped by engine for better rate limiting
    tasks = []
    for prompt in prompts:
        for engine in engines:
            tasks.append((engine, prompt))

    # Process with concurrency
    results = await asyncio.gather(
        *[process_one(engine, prompt, brands) for engine, prompt in tasks],
        return_exceptions=True,
    )

    for i, result in enumerate(results):
        completed += 1
        engine, prompt = tasks[i]

        if isinstance(result, Exception):
            print(f"  [{completed}/{total}] ERROR {engine.name}: {prompt[:50]}... - {result}")
            for brand in brands:
                all_rows.append({
                    "Query": prompt,
                    "AI Engine": engine.name,
                    "Brand": brand,
                    "Mention": "No",
                    "Rank": None,
                    "Rank Score": 0,
                    "Source": "",
                    "Error": str(result),
                })
            continue

        response, rows = result
        all_rows.extend(rows)

        status = "OK" if not response.error else f"ERR: {response.error[:50]}"
        print(f"  [{completed}/{total}] {engine.name} | {prompt[:50]}... | {status}")

        if save_raw:
            raw_responses.append({
                "prompt": prompt,
                "engine": engine.name,
                "model": engine.model,
                "response": response.response_text,
                "citations": response.citations,
                "error": response.error,
            })

    # Save combined results CSV
    df = pd.DataFrame(all_rows)
    col_order = ["Query", "AI Engine", "Brand", "Mention", "Rank", "Rank Score", "Source", "Error"]
    df = df[[c for c in col_order if c in df.columns]]
    csv_path = os.path.join(output_dir, f"results_{timestamp}.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nResults saved to: {csv_path}")

    # Save per-brand CSVs: Query | AI Engine | {Brand} Mention | Rank | Rank Score | Source
    for brand in brands:
        brand_df = df[df["Brand"] == brand].copy()
        brand_df = brand_df.rename(columns={"Mention": f"{brand} Mention"})
        brand_df = brand_df.drop(columns=["Brand", "Error"], errors="ignore")
        brand_csv = os.path.join(output_dir, f"{brand}_{timestamp}.csv")
        brand_df.to_csv(brand_csv, index=False)
        print(f"  Brand CSV: {brand_csv}")

    # Save raw AI responses as CSV (one row per prompt+engine with full response)
    if save_raw and raw_responses:
        raw_df = pd.DataFrame(raw_responses)
        raw_csv_path = os.path.join(output_dir, f"raw_responses_{timestamp}.csv")
        raw_df.to_csv(raw_csv_path, index=False)
        print(f"Raw responses saved to: {raw_csv_path}")

        # Also save as JSON for structured access
        raw_json_path = os.path.join(output_dir, f"raw_responses_{timestamp}.json")
        with open(raw_json_path, "w", encoding="utf-8") as f:
            json.dump(raw_responses, f, ensure_ascii=False, indent=2)
        print(f"Raw responses (JSON) saved to: {raw_json_path}")

    return df
