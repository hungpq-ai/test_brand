import asyncio
import json
import os
from datetime import datetime

import pandas as pd

from engines.base import BaseEngine, EngineResponse
from extractor import extract_brands
from scoring import BrandScore, calculate_ai_visibility_score, get_score_grade


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

    # Get list of mentioned competitors for each brand
    mentioned_brands = [m for m in mentions if m.mentioned]

    rows = []
    for m in mentions:
        # Create BrandScore for new scoring system
        brand_score = BrandScore(
            brand=m.brand,
            mentioned=m.mentioned,
            rank=m.rank,
            citation_type=m.citation_type,
        )

        # Build competitor presence list (other brands mentioned in same response)
        competitors = []
        for other in mentioned_brands:
            if other.brand != m.brand:
                rank_str = f"Rank {other.rank}" if other.rank else "mentioned"
                competitors.append(f"{other.brand} ({rank_str})")

        competitor_presence = "; ".join(competitors) if competitors else ""

        rows.append({
            "Query": prompt,
            "AI Engine": engine.name,
            "Brand": m.brand,
            "Mention": "Yes" if m.mentioned else "No",
            "Rank": m.rank,
            "Ranking Score": brand_score.ranking_score,  # NEW: 100, 80, 60...
            "Citation Type": m.citation_type,  # NEW: official/other/none
            "Citation Score": brand_score.citation_score,  # NEW: 100/50/0
            "Competitors Mentioned": competitor_presence,  # NEW: Competitor presence
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
) -> tuple[pd.DataFrame, dict]:
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
    col_order = ["Query", "AI Engine", "Brand", "Mention", "Rank", "Ranking Score", "Citation Type", "Citation Score", "Source", "Error"]
    df = df[[c for c in col_order if c in df.columns]]
    csv_path = os.path.join(output_dir, f"results_{timestamp}.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nResults saved to: {csv_path}")

    # Persist to SQLite database
    try:
        from db import insert_results
        full_df = pd.DataFrame(all_rows)
        db_rows = []
        for _, row in full_df.iterrows():
            db_rows.append({
                "Query": row.get("Query", ""),
                "AI Engine": row.get("AI Engine", ""),
                "Brand": row.get("Brand", ""),
                "Mention": row.get("Mention", "No"),
                "Rank": row.get("Rank") if pd.notna(row.get("Rank")) else None,
                "Ranking Score": row.get("Ranking Score", 0),
                "Citation Type": row.get("Citation Type", "none"),
                "Citation Score": row.get("Citation Score", 0),
                "Source": row.get("Source", ""),
                "Competitors Mentioned": row.get("Competitors Mentioned", ""),
                "Error": row.get("Error") if pd.notna(row.get("Error")) else None,
            })
        insert_results(db_rows, timestamp, source="batch")
        print(f"Results persisted to database ({len(db_rows)} rows)")
    except Exception as e:
        print(f"Warning: Failed to persist to database: {e}")

    # Calculate aggregate AI Visibility Scores for each brand
    print(f"\nCalculating AI Visibility Scores...")
    brand_scores_summary = []

    for brand in brands:
        brand_df = df[df["Brand"] == brand].copy()

        # Create BrandScore objects for aggregate calculation
        brand_score_objs = []
        for _, row in brand_df.iterrows():
            if pd.notna(row.get("Error")) and row["Error"]:
                continue  # Skip error rows

            brand_score_objs.append(BrandScore(
                brand=brand,
                mentioned=(row["Mention"] == "Yes"),
                rank=int(row["Rank"]) if pd.notna(row["Rank"]) else None,
                citation_type=row.get("Citation Type", "none"),
            ))

        if brand_score_objs:
            scores = calculate_ai_visibility_score(brand_score_objs)
            scores["brand"] = brand
            scores["grade"] = get_score_grade(scores["ai_visibility_score"])
            brand_scores_summary.append(scores)

    # Track all output files for download
    output_files = {
        "timestamp": timestamp,
        "results_csv": csv_path,
        "scores_csv": None,
        "raw_csv": None,
        "raw_json": None,
        "brand_csvs": []
    }

    # Save aggregate scores
    if brand_scores_summary:
        scores_df = pd.DataFrame(brand_scores_summary)
        scores_csv = os.path.join(output_dir, f"ai_visibility_scores_{timestamp}.csv")
        scores_df.to_csv(scores_csv, index=False)
        print(f"AI Visibility Scores saved to: {scores_csv}")
        output_files["scores_csv"] = scores_csv

    # Save per-brand CSVs: Query | AI Engine | {Brand} Mention | Rank | Rank Score | Source
    for brand in brands:
        brand_df = df[df["Brand"] == brand].copy()
        brand_df = brand_df.rename(columns={"Mention": f"{brand} Mention"})
        brand_df = brand_df.drop(columns=["Brand", "Error"], errors="ignore")
        brand_csv = os.path.join(output_dir, f"{brand}_{timestamp}.csv")
        brand_df.to_csv(brand_csv, index=False)
        print(f"  Brand CSV: {brand_csv}")
        output_files["brand_csvs"].append({"brand": brand, "path": brand_csv})

    # Save raw AI responses as CSV (one row per prompt+engine with full response)
    if save_raw and raw_responses:
        raw_df = pd.DataFrame(raw_responses)
        raw_csv_path = os.path.join(output_dir, f"raw_responses_{timestamp}.csv")
        raw_df.to_csv(raw_csv_path, index=False)
        print(f"Raw responses saved to: {raw_csv_path}")
        output_files["raw_csv"] = raw_csv_path

        # Also save as JSON for structured access
        raw_json_path = os.path.join(output_dir, f"raw_responses_{timestamp}.json")
        with open(raw_json_path, "w", encoding="utf-8") as f:
            json.dump(raw_responses, f, ensure_ascii=False, indent=2)
        print(f"Raw responses (JSON) saved to: {raw_json_path}")
        output_files["raw_json"] = raw_json_path

    return df, output_files
