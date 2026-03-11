import asyncio
import csv
import glob
import json
import os
import threading
from datetime import datetime

import pandas as pd
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
load_dotenv()

app = FastAPI(title="AI Brand Monitor")

CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
PROMPTS_PATH = os.path.join(BASE_DIR, "prompts.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_prompts():
    prompts = []
    with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            prompt = row.get("prompt", "").strip().strip('"')
            if prompt:
                prompts.append(prompt)
    return prompts


def get_results():
    """Load all result CSV files and return combined data."""
    pattern = os.path.join(OUTPUT_DIR, "Mondelez_*.csv")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return None
    # Use the latest file
    df = pd.read_csv(files[0])
    return df


def get_raw_responses():
    """Load latest raw responses."""
    pattern = os.path.join(OUTPUT_DIR, "raw_responses_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return []
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


# Track running jobs
job_status = {"running": False, "progress": "", "log": []}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return DASHBOARD_HTML


@app.get("/api/config")
async def api_config():
    config = load_config()
    return config


@app.get("/api/prompts")
async def api_prompts():
    prompts = load_prompts()
    return {"count": len(prompts), "prompts": prompts}


@app.get("/api/results")
async def api_results():
    df = get_results()
    if df is None:
        return {"data": [], "summary": {}}

    # Build summary before fillna
    mention_col = [c for c in df.columns if "Mention" in c][0] if any("Mention" in c for c in df.columns) else None
    summary = {}
    if mention_col:
        for engine in df["AI Engine"].unique():
            eng_df = df[df["AI Engine"] == engine]
            mentioned = eng_df[eng_df[mention_col] == "Yes"]
            avg_rank = None
            if not mentioned.empty and mentioned["Rank"].notna().any():
                avg_rank = round(float(mentioned["Rank"].mean()), 1)
            avg_score = round(float(mentioned["Rank Score"].mean()), 2) if not mentioned.empty else 0
            summary[engine] = {
                "total": int(len(eng_df)),
                "mentions": int(len(mentioned)),
                "mention_rate": round(len(mentioned) / len(eng_df) * 100, 1) if len(eng_df) > 0 else 0,
                "avg_rank": avg_rank,
                "avg_score": avg_score,
            }

    # Clean NaN for JSON serialization
    records = json.loads(df.to_json(orient="records"))

    return {"data": records, "summary": summary}


@app.get("/api/raw/{engine}/{index}")
async def api_raw_response(engine: str, index: int):
    raw = get_raw_responses()
    engine_responses = [r for r in raw if r["engine"] == engine]
    if 0 <= index < len(engine_responses):
        return engine_responses[index]
    return {"error": "Not found"}


@app.post("/api/run")
async def api_run(request: Request):
    body = await request.json()
    engines = body.get("engines", [])

    if job_status["running"]:
        return JSONResponse({"error": "A job is already running"}, status_code=409)

    def run_job():
        job_status["running"] = True
        job_status["log"] = []
        job_status["progress"] = "Starting..."

        try:
            from engines import ChatGPTEngine, GeminiEngine, ClaudeEngine, PerplexityEngine
            from engines.base import BaseEngine
            from runner import run_all

            config = load_config()
            prompts = load_prompts()
            brands = config.get("brands", [])

            ENGINE_CLASSES = {
                "chatgpt": ChatGPTEngine,
                "gemini": GeminiEngine,
                "claude": ClaudeEngine,
                "perplexity": PerplexityEngine,
            }

            engine_objs = []
            engine_configs = config.get("engines", {})
            for name in engines:
                cls = ENGINE_CLASSES.get(name)
                if not cls:
                    continue
                eng_cfg = engine_configs.get(name, {})
                model = eng_cfg.get("model")
                rpm = eng_cfg.get("rpm", 60)
                try:
                    engine_objs.append(cls(model=model, rpm=rpm))
                    job_status["log"].append(f"Initialized {name} (model={model})")
                except Exception as e:
                    job_status["log"].append(f"Failed to init {name}: {e}")

            if not engine_objs:
                job_status["log"].append("No engines available")
                return

            output_dir = config.get("output", {}).get("dir", "output")
            save_raw = config.get("output", {}).get("save_raw_responses", True)

            job_status["progress"] = f"Running {len(prompts)} prompts x {len(engine_objs)} engines..."

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            df = loop.run_until_complete(run_all(prompts, engine_objs, brands, output_dir, save_raw))
            loop.close()

            job_status["log"].append(f"Done! {len(df)} rows generated")
            job_status["progress"] = "Completed"
        except Exception as e:
            job_status["log"].append(f"Error: {e}")
            job_status["progress"] = f"Error: {e}"
        finally:
            job_status["running"] = False

    thread = threading.Thread(target=run_job, daemon=True)
    thread.start()

    return {"status": "started"}


@app.get("/api/status")
async def api_status():
    return job_status


@app.post("/api/query")
async def api_live_query(request: Request):
    """Send a single prompt to selected engines and return comparison."""
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    engine_names = body.get("engines", [])
    brands = body.get("brands", None)

    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    from engines import ChatGPTEngine, GeminiEngine, ClaudeEngine, PerplexityEngine
    from extractor import extract_brands

    config = load_config()
    if brands is None:
        brands = config.get("brands", [])

    ENGINE_CLASSES = {
        "chatgpt": ChatGPTEngine,
        "gemini": GeminiEngine,
        "claude": ClaudeEngine,
        "perplexity": PerplexityEngine,
    }

    engine_configs = config.get("engines", {})
    results = []

    async def query_engine(name):
        cls = ENGINE_CLASSES.get(name)
        if not cls:
            return {"engine": name, "error": f"Unknown engine: {name}"}
        eng_cfg = engine_configs.get(name, {})
        model = eng_cfg.get("model")
        rpm = eng_cfg.get("rpm", 60)
        try:
            engine = cls(model=model, rpm=rpm)
        except Exception as e:
            return {"engine": name, "model": model, "error": str(e)}

        try:
            response = await engine.safe_query(prompt)
            if response.error:
                return {"engine": name, "model": model, "error": response.error, "response": ""}

            mentions = extract_brands(
                response.response_text, brands,
                extra_citations=response.citations if response.citations else None,
            )

            brand_results = []
            for m in mentions:
                rank_score = 0
                if m.mentioned and m.rank is not None:
                    rank_score = round(1 - (m.rank - 1) * 0.2, 2) if m.rank <= 5 else 0.1
                elif m.mentioned:
                    rank_score = 0.1
                brand_results.append({
                    "brand": m.brand,
                    "mentioned": m.mentioned,
                    "rank": m.rank,
                    "rank_score": rank_score,
                    "sources": m.sources,
                })

            return {
                "engine": name,
                "model": model,
                "response": response.response_text,
                "brands": brand_results,
                "error": None,
            }
        except Exception as e:
            return {"engine": name, "model": model, "error": str(e), "response": ""}

    tasks = [query_engine(name) for name in engine_names]
    results = await asyncio.gather(*tasks)

    return {"prompt": prompt, "brands": brands, "results": list(results)}


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Brand Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; }

        .header { background: linear-gradient(135deg, #1e293b, #334155); padding: 20px 32px; border-bottom: 1px solid #475569; display: flex; align-items: center; justify-content: space-between; }
        .header h1 { font-size: 24px; font-weight: 700; }
        .header h1 span { color: #60a5fa; }
        .header .subtitle { color: #94a3b8; font-size: 14px; margin-top: 4px; }

        .container { max-width: 1400px; margin: 0 auto; padding: 24px; }

        /* Summary Cards */
        .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .card { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .card-title { font-size: 14px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }
        .card-value { font-size: 36px; font-weight: 700; }
        .card-sub { font-size: 13px; color: #94a3b8; margin-top: 4px; }

        .mention-rate { color: #34d399; }
        .avg-rank { color: #60a5fa; }
        .avg-score { color: #f59e0b; }

        /* Engine comparison */
        .engine-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .engine-card { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; position: relative; overflow: hidden; }
        .engine-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; }
        .engine-card.chatgpt::before { background: #10b981; }
        .engine-card.gemini::before { background: #3b82f6; }
        .engine-card.claude::before { background: #f59e0b; }
        .engine-card.perplexity::before { background: #8b5cf6; }

        .engine-name { font-size: 18px; font-weight: 600; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
        .engine-name .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
        .chatgpt .dot { background: #10b981; }
        .gemini .dot { background: #3b82f6; }
        .claude .dot { background: #f59e0b; }
        .perplexity .dot { background: #8b5cf6; }

        .engine-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .stat { }
        .stat-label { font-size: 12px; color: #64748b; margin-bottom: 2px; }
        .stat-value { font-size: 20px; font-weight: 600; }

        .bar-container { margin-top: 16px; }
        .bar-bg { background: #334155; border-radius: 8px; height: 8px; overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 8px; transition: width 0.8s ease; }
        .chatgpt .bar-fill { background: #10b981; }
        .gemini .bar-fill { background: #3b82f6; }
        .claude .bar-fill { background: #f59e0b; }
        .perplexity .bar-fill { background: #8b5cf6; }

        /* Table */
        .table-section { background: #1e293b; border-radius: 12px; border: 1px solid #334155; overflow: hidden; margin-bottom: 24px; }
        .table-header { padding: 16px 20px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
        .table-header h2 { font-size: 16px; font-weight: 600; }
        .table-filters { display: flex; gap: 8px; }
        .filter-btn { padding: 6px 14px; border-radius: 6px; border: 1px solid #475569; background: transparent; color: #94a3b8; cursor: pointer; font-size: 13px; transition: all 0.2s; }
        .filter-btn:hover, .filter-btn.active { background: #334155; color: #e2e8f0; border-color: #60a5fa; }

        table { width: 100%; border-collapse: collapse; }
        th { padding: 12px 16px; text-align: left; font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #334155; background: #1e293b; position: sticky; top: 0; }
        td { padding: 10px 16px; font-size: 14px; border-bottom: 1px solid #1e293b; }
        tr:hover td { background: #1e293b; }
        .table-scroll { max-height: 500px; overflow-y: auto; }

        .badge { padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 500; }
        .badge-yes { background: #065f46; color: #34d399; }
        .badge-no { background: #7f1d1d33; color: #f87171; }
        .badge-engine { font-size: 11px; padding: 2px 8px; }
        .badge-chatgpt { background: #10b98133; color: #34d399; }
        .badge-gemini { background: #3b82f633; color: #60a5fa; }
        .badge-claude { background: #f59e0b33; color: #fbbf24; }
        .badge-perplexity { background: #8b5cf633; color: #a78bfa; }

        /* Run Panel */
        .run-panel { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; margin-bottom: 24px; }
        .run-panel h2 { font-size: 16px; font-weight: 600; margin-bottom: 16px; }
        .engine-toggles { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
        .toggle-label { display: flex; align-items: center; gap: 8px; padding: 8px 16px; border-radius: 8px; border: 1px solid #475569; cursor: pointer; transition: all 0.2s; }
        .toggle-label:hover { border-color: #60a5fa; }
        .toggle-label input:checked + span { color: #60a5fa; }
        .toggle-label input { accent-color: #60a5fa; }

        .btn { padding: 10px 24px; border-radius: 8px; border: none; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
        .btn-primary { background: #3b82f6; color: white; }
        .btn-primary:hover { background: #2563eb; }
        .btn-primary:disabled { background: #475569; cursor: not-allowed; }

        .log-box { background: #0f172a; border-radius: 8px; padding: 12px; margin-top: 12px; font-family: monospace; font-size: 13px; max-height: 200px; overflow-y: auto; display: none; }
        .log-box.visible { display: block; }
        .log-line { padding: 2px 0; color: #94a3b8; }
        .log-line.success { color: #34d399; }
        .log-line.error { color: #f87171; }

        /* Tabs */
        .tabs { display: flex; gap: 0; margin-bottom: 24px; }
        .tab { padding: 10px 24px; border: 1px solid #334155; background: transparent; color: #94a3b8; cursor: pointer; font-size: 14px; transition: all 0.2s; }
        .tab:first-child { border-radius: 8px 0 0 8px; }
        .tab:last-child { border-radius: 0 8px 8px 0; }
        .tab.active { background: #334155; color: #e2e8f0; border-color: #60a5fa; }

        .section { display: none; }
        .section.active { display: block; }

        /* Raw response viewer */
        .raw-viewer { background: #1e293b; border-radius: 12px; border: 1px solid #334155; padding: 20px; }
        .raw-response { background: #0f172a; border-radius: 8px; padding: 16px; margin-top: 12px; font-size: 14px; line-height: 1.6; max-height: 400px; overflow-y: auto; white-space: pre-wrap; }
        .raw-nav { display: flex; gap: 8px; align-items: center; margin-top: 12px; }
        .raw-nav select { background: #334155; color: #e2e8f0; border: 1px solid #475569; border-radius: 6px; padding: 6px 12px; font-size: 13px; }

        /* Live Query */
        .query-box { background: #1e293b; border-radius: 12px; padding: 24px; border: 1px solid #334155; margin-bottom: 24px; }
        .query-input-row { display: flex; gap: 12px; margin-bottom: 16px; }
        .query-input { flex: 1; background: #0f172a; border: 1px solid #475569; border-radius: 8px; padding: 12px 16px; color: #e2e8f0; font-size: 15px; outline: none; transition: border-color 0.2s; }
        .query-input:focus { border-color: #60a5fa; }
        .query-input::placeholder { color: #64748b; }

        .brand-input-row { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
        .brand-input { flex: 1; background: #0f172a; border: 1px solid #475569; border-radius: 8px; padding: 10px 16px; color: #e2e8f0; font-size: 14px; outline: none; }
        .brand-input:focus { border-color: #60a5fa; }

        .query-engines { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
        .query-engine-btn { padding: 8px 18px; border-radius: 8px; border: 1px solid #475569; background: transparent; color: #94a3b8; cursor: pointer; font-size: 13px; transition: all 0.2s; }
        .query-engine-btn.selected { border-color: #60a5fa; color: #e2e8f0; background: #334155; }
        .query-engine-btn:hover { border-color: #60a5fa; }

        .comparison-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 16px; }
        .comparison-card { background: #1e293b; border-radius: 12px; border: 1px solid #334155; overflow: hidden; }
        .comparison-header { padding: 14px 18px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
        .comparison-header .engine-label { font-weight: 600; font-size: 15px; display: flex; align-items: center; gap: 8px; }
        .comparison-header .model-label { font-size: 12px; color: #64748b; }
        .comparison-brand-row { padding: 10px 18px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b; background: #0f172a; }
        .comparison-brand-name { font-weight: 500; }
        .comparison-brand-info { display: flex; gap: 16px; align-items: center; font-size: 13px; }
        .comparison-response { padding: 14px 18px; font-size: 13px; line-height: 1.6; max-height: 300px; overflow-y: auto; white-space: pre-wrap; color: #cbd5e1; }

        .loading-spinner { display: inline-block; width: 18px; height: 18px; border: 2px solid #475569; border-top-color: #60a5fa; border-radius: 50%; animation: spin 0.8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }

        .score-pill { padding: 2px 10px; border-radius: 10px; font-size: 12px; font-weight: 600; }
        .score-high { background: #065f46; color: #34d399; }
        .score-mid { background: #78350f; color: #fbbf24; }
        .score-low { background: #7f1d1d33; color: #f87171; }
        .score-none { background: #334155; color: #64748b; }

        .query-history { margin-top: 24px; }
        .query-history h3 { font-size: 14px; color: #94a3b8; margin-bottom: 12px; }
        .history-item { padding: 10px 16px; background: #0f172a; border-radius: 8px; margin-bottom: 8px; cursor: pointer; transition: all 0.2s; border: 1px solid transparent; }
        .history-item:hover { border-color: #475569; }
        .history-prompt { font-size: 14px; margin-bottom: 6px; }
        .history-badges { display: flex; gap: 8px; flex-wrap: wrap; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>AI <span>Brand Monitor</span></h1>
            <div class="subtitle">GEO Audit Framework — Track brand visibility across AI engines</div>
        </div>
        <div style="text-align: right;">
            <div id="brand-name" style="font-size: 20px; font-weight: 700; color: #60a5fa;">Mondelez</div>
            <div id="prompt-count" style="font-size: 13px; color: #94a3b8;">Loading...</div>
        </div>
    </div>

    <div class="container">
        <div class="tabs">
            <button class="tab active" onclick="switchTab('dashboard')">Dashboard</button>
            <button class="tab" onclick="switchTab('query')">Live Query</button>
            <button class="tab" onclick="switchTab('details')">Detail Data</button>
            <button class="tab" onclick="switchTab('raw')">Raw Responses</button>
            <button class="tab" onclick="switchTab('run')">Run Test</button>
        </div>

        <!-- Dashboard Tab -->
        <div id="tab-dashboard" class="section active">
            <div class="cards">
                <div class="card">
                    <div class="card-title">Total Mentions</div>
                    <div class="card-value mention-rate" id="total-mentions">—</div>
                    <div class="card-sub" id="total-mention-rate"></div>
                </div>
                <div class="card">
                    <div class="card-title">Best Avg Rank</div>
                    <div class="card-value avg-rank" id="best-rank">—</div>
                    <div class="card-sub" id="best-rank-engine"></div>
                </div>
                <div class="card">
                    <div class="card-title">Best Avg Score</div>
                    <div class="card-value avg-score" id="best-score">—</div>
                    <div class="card-sub" id="best-score-engine"></div>
                </div>
                <div class="card">
                    <div class="card-title">Engines Tested</div>
                    <div class="card-value" id="engine-count" style="color: #c084fc;">—</div>
                    <div class="card-sub" id="engine-list"></div>
                </div>
            </div>

            <div class="engine-grid" id="engine-grid"></div>
        </div>

        <!-- Live Query Tab -->
        <div id="tab-query" class="section">
            <div class="query-box">
                <h2 style="margin-bottom: 16px; font-size: 18px;">Live Brand Detection</h2>
                <div class="brand-input-row">
                    <label style="font-size: 13px; color: #94a3b8; white-space: nowrap;">Brands:</label>
                    <input type="text" class="brand-input" id="query-brands" placeholder="Mondelez, Nestle, Mars... (comma separated)">
                </div>
                <div class="query-input-row">
                    <input type="text" class="query-input" id="query-prompt" placeholder="Enter your prompt here... e.g. Top 10 snack brands in Vietnam">
                    <button class="btn btn-primary" id="query-btn" onclick="sendLiveQuery()">Send</button>
                </div>
                <div class="query-engines" id="query-engine-toggles">
                    <button class="query-engine-btn selected" data-engine="chatgpt" onclick="toggleQueryEngine(this)">ChatGPT</button>
                    <button class="query-engine-btn selected" data-engine="gemini" onclick="toggleQueryEngine(this)">Gemini</button>
                    <button class="query-engine-btn selected" data-engine="claude" onclick="toggleQueryEngine(this)">Claude</button>
                    <button class="query-engine-btn" data-engine="perplexity" onclick="toggleQueryEngine(this)">Perplexity</button>
                </div>
            </div>

            <div class="comparison-grid" id="comparison-grid"></div>

            <div class="query-history" id="query-history" style="display:none;">
                <h3>Query History</h3>
                <div id="history-list"></div>
            </div>
        </div>

        <!-- Detail Data Tab -->
        <div id="tab-details" class="section">
            <div class="table-section">
                <div class="table-header">
                    <h2>Query Results</h2>
                    <div class="table-filters">
                        <button class="filter-btn active" onclick="filterTable('all', this)">All</button>
                        <button class="filter-btn" onclick="filterTable('yes', this)">Mentioned</button>
                        <button class="filter-btn" onclick="filterTable('no', this)">Not Mentioned</button>
                    </div>
                </div>
                <div class="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th style="width:40px">#</th>
                                <th>Query</th>
                                <th>Engine</th>
                                <th>Mention</th>
                                <th>Rank</th>
                                <th>Score</th>
                                <th>Source</th>
                            </tr>
                        </thead>
                        <tbody id="results-tbody"></tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Raw Responses Tab -->
        <div id="tab-raw" class="section">
            <div class="raw-viewer">
                <h2>Raw AI Responses</h2>
                <div class="raw-nav">
                    <select id="raw-engine" onchange="loadRawResponse()">
                        <option value="chatgpt">ChatGPT</option>
                        <option value="gemini">Gemini</option>
                        <option value="claude">Claude</option>
                    </select>
                    <select id="raw-index" onchange="loadRawResponse()"></select>
                </div>
                <div class="raw-response" id="raw-content">Select a prompt to view the raw response...</div>
            </div>
        </div>

        <!-- Run Test Tab -->
        <div id="tab-run" class="section">
            <div class="run-panel">
                <h2>Run Brand Monitoring Test</h2>
                <div class="engine-toggles">
                    <label class="toggle-label">
                        <input type="checkbox" value="chatgpt" checked>
                        <span>ChatGPT (gpt-5.1)</span>
                    </label>
                    <label class="toggle-label">
                        <input type="checkbox" value="gemini" checked>
                        <span>Gemini (gemini-3-flash-preview)</span>
                    </label>
                    <label class="toggle-label">
                        <input type="checkbox" value="claude" checked>
                        <span>Claude (claude-sonnet-4.5)</span>
                    </label>
                    <label class="toggle-label">
                        <input type="checkbox" value="perplexity">
                        <span>Perplexity (sonar-pro)</span>
                    </label>
                </div>
                <button class="btn btn-primary" id="run-btn" onclick="startRun()">Start Test Run</button>
                <div class="log-box" id="log-box"></div>
            </div>
        </div>
    </div>

    <script>
        let allData = [];
        let currentFilter = 'all';

        function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById('tab-' + tab).classList.add('active');
        }

        async function loadData() {
            const [resultsRes, promptsRes, configRes] = await Promise.all([
                fetch('/api/results'), fetch('/api/prompts'), fetch('/api/config')
            ]);
            const results = await resultsRes.json();
            const prompts = await promptsRes.json();
            const config = await configRes.json();

            document.getElementById('brand-name').textContent = (config.brands || ['Mondelez'])[0];
            document.getElementById('prompt-count').textContent = prompts.count + ' prompts loaded';

            allData = results.data || [];
            const summary = results.summary || {};

            // Summary cards
            const engines = Object.keys(summary);
            let totalMentions = 0, totalPrompts = 0;
            let bestRank = null, bestRankEng = '';
            let bestScore = 0, bestScoreEng = '';

            engines.forEach(eng => {
                const s = summary[eng];
                totalMentions += s.mentions;
                totalPrompts += s.total;
                if (s.avg_rank && (bestRank === null || s.avg_rank < bestRank)) {
                    bestRank = s.avg_rank;
                    bestRankEng = eng;
                }
                if (s.avg_score > bestScore) {
                    bestScore = s.avg_score;
                    bestScoreEng = eng;
                }
            });

            document.getElementById('total-mentions').textContent = totalMentions;
            document.getElementById('total-mention-rate').textContent =
                totalPrompts > 0 ? `${(totalMentions/totalPrompts*100).toFixed(1)}% of ${totalPrompts} queries` : '';
            document.getElementById('best-rank').textContent = bestRank ? '#' + bestRank : '—';
            document.getElementById('best-rank-engine').textContent = bestRankEng;
            document.getElementById('best-score').textContent = bestScore.toFixed(2);
            document.getElementById('best-score-engine').textContent = bestScoreEng;
            document.getElementById('engine-count').textContent = engines.length;
            document.getElementById('engine-list').textContent = engines.join(', ');

            // Engine cards
            const grid = document.getElementById('engine-grid');
            grid.innerHTML = '';
            engines.forEach(eng => {
                const s = summary[eng];
                grid.innerHTML += `
                    <div class="engine-card ${eng}">
                        <div class="engine-name"><span class="dot"></span>${eng}</div>
                        <div class="engine-stats">
                            <div class="stat">
                                <div class="stat-label">Mentions</div>
                                <div class="stat-value">${s.mentions}/${s.total}</div>
                            </div>
                            <div class="stat">
                                <div class="stat-label">Mention Rate</div>
                                <div class="stat-value">${s.mention_rate}%</div>
                            </div>
                            <div class="stat">
                                <div class="stat-label">Avg Rank</div>
                                <div class="stat-value">${s.avg_rank || '—'}</div>
                            </div>
                            <div class="stat">
                                <div class="stat-label">Avg Score</div>
                                <div class="stat-value">${s.avg_score}</div>
                            </div>
                        </div>
                        <div class="bar-container">
                            <div class="bar-bg"><div class="bar-fill" style="width: ${s.mention_rate}%"></div></div>
                        </div>
                    </div>
                `;
            });

            renderTable();
            populateRawSelect();
        }

        function renderTable() {
            const tbody = document.getElementById('results-tbody');
            const mentionCol = Object.keys(allData[0] || {}).find(k => k.includes('Mention')) || 'Mondelez Mention';

            let filtered = allData;
            if (currentFilter === 'yes') filtered = allData.filter(r => r[mentionCol] === 'Yes');
            if (currentFilter === 'no') filtered = allData.filter(r => r[mentionCol] === 'No');

            tbody.innerHTML = filtered.map((r, i) => {
                const mentioned = r[mentionCol] === 'Yes';
                const eng = r['AI Engine'] || '';
                return `<tr>
                    <td>${i + 1}</td>
                    <td title="${(r.Query || '').replace(/"/g, '&quot;')}">${(r.Query || '').substring(0, 80)}${(r.Query || '').length > 80 ? '...' : ''}</td>
                    <td><span class="badge badge-engine badge-${eng}">${eng}</span></td>
                    <td><span class="badge ${mentioned ? 'badge-yes' : 'badge-no'}">${mentioned ? 'Yes' : 'No'}</span></td>
                    <td>${r.Rank != null && !isNaN(r.Rank) ? '#' + Math.round(r.Rank) : '—'}</td>
                    <td>${r['Rank Score'] || 0}</td>
                    <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${r.Source || ''}">${r.Source || ''}</td>
                </tr>`;
            }).join('');
        }

        function filterTable(filter, btn) {
            currentFilter = filter;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderTable();
        }

        function populateRawSelect() {
            const prompts = [...new Set(allData.map(r => r.Query))];
            const select = document.getElementById('raw-index');
            select.innerHTML = prompts.map((p, i) =>
                `<option value="${i}">${i + 1}. ${p.substring(0, 60)}...</option>`
            ).join('');
        }

        async function loadRawResponse() {
            const engine = document.getElementById('raw-engine').value;
            const index = parseInt(document.getElementById('raw-index').value);
            try {
                const res = await fetch(`/api/raw/${engine}/${index}`);
                const data = await res.json();
                if (data.error) {
                    document.getElementById('raw-content').textContent = 'No response found for this engine/prompt combination.';
                } else {
                    document.getElementById('raw-content').textContent = data.response || 'Empty response';
                }
            } catch(e) {
                document.getElementById('raw-content').textContent = 'Error loading response';
            }
        }

        async function startRun() {
            const engines = [...document.querySelectorAll('.engine-toggles input:checked')].map(c => c.value);
            if (engines.length === 0) { alert('Select at least one engine'); return; }

            const btn = document.getElementById('run-btn');
            const logBox = document.getElementById('log-box');
            btn.disabled = true;
            btn.textContent = 'Running...';
            logBox.classList.add('visible');
            logBox.innerHTML = '<div class="log-line">Starting test run...</div>';

            await fetch('/api/run', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({engines})
            });

            const poll = setInterval(async () => {
                const res = await fetch('/api/status');
                const status = await res.json();

                logBox.innerHTML = status.log.map(l =>
                    `<div class="log-line ${l.includes('Done') ? 'success' : l.includes('Error') ? 'error' : ''}">${l}</div>`
                ).join('') + `<div class="log-line">${status.progress}</div>`;
                logBox.scrollTop = logBox.scrollHeight;

                if (!status.running) {
                    clearInterval(poll);
                    btn.disabled = false;
                    btn.textContent = 'Start Test Run';
                    loadData();
                }
            }, 2000);
        }

        loadData();

        // === LIVE QUERY ===
        let queryHistory = [];

        function toggleQueryEngine(btn) {
            btn.classList.toggle('selected');
        }

        // Enter key to send
        document.getElementById('query-prompt').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') sendLiveQuery();
        });

        async function sendLiveQuery() {
            const prompt = document.getElementById('query-prompt').value.trim();
            if (!prompt) return;

            const brandsInput = document.getElementById('query-brands').value.trim();
            const brands = brandsInput ? brandsInput.split(',').map(b => b.trim()).filter(Boolean) : null;

            const engines = [...document.querySelectorAll('.query-engine-btn.selected')].map(b => b.dataset.engine);
            if (engines.length === 0) { alert('Select at least one engine'); return; }

            const btn = document.getElementById('query-btn');
            btn.disabled = true;
            btn.textContent = 'Querying...';

            const grid = document.getElementById('comparison-grid');
            // Show loading cards
            grid.innerHTML = engines.map(eng => `
                <div class="comparison-card">
                    <div class="comparison-header">
                        <div class="engine-label"><span class="dot" style="width:8px;height:8px;border-radius:50;display:inline-block;background:var(--c-${eng})"></span>${eng}</div>
                        <div class="loading-spinner"></div>
                    </div>
                    <div class="comparison-response" style="text-align:center;padding:40px;color:#64748b;">Waiting for response...</div>
                </div>
            `).join('');

            try {
                const res = await fetch('/api/query', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({prompt, engines, brands})
                });
                const data = await res.json();

                if (data.error) {
                    grid.innerHTML = `<div style="color:#f87171;padding:20px;">${data.error}</div>`;
                    return;
                }

                renderComparison(data);
                addToHistory(data);
            } catch(e) {
                grid.innerHTML = `<div style="color:#f87171;padding:20px;">Error: ${e.message}</div>`;
            } finally {
                btn.disabled = false;
                btn.textContent = 'Send';
            }
        }

        function getScoreClass(score) {
            if (score >= 0.6) return 'score-high';
            if (score >= 0.2) return 'score-mid';
            if (score > 0) return 'score-low';
            return 'score-none';
        }

        function renderComparison(data) {
            const grid = document.getElementById('comparison-grid');
            grid.innerHTML = data.results.map(r => {
                if (r.error) {
                    return `
                        <div class="comparison-card">
                            <div class="comparison-header">
                                <div class="engine-label"><span class="dot" style="width:8px;height:8px;border-radius:50%;display:inline-block;background:${getEngineColor(r.engine)}"></span>${r.engine}</div>
                                <div class="model-label">${r.model || ''}</div>
                            </div>
                            <div class="comparison-response" style="color:#f87171;">Error: ${r.error}</div>
                        </div>
                    `;
                }

                const brandRows = (r.brands || []).map(b => {
                    const scoreClass = getScoreClass(b.rank_score);
                    return `
                        <div class="comparison-brand-row">
                            <div class="comparison-brand-name">${b.brand}</div>
                            <div class="comparison-brand-info">
                                <span class="badge ${b.mentioned ? 'badge-yes' : 'badge-no'}">${b.mentioned ? 'Yes' : 'No'}</span>
                                <span style="color:#94a3b8;">${b.rank ? '#' + b.rank : '—'}</span>
                                <span class="score-pill ${scoreClass}">${b.rank_score.toFixed(1)}</span>
                            </div>
                        </div>
                    `;
                }).join('');

                return `
                    <div class="comparison-card">
                        <div class="comparison-header">
                            <div class="engine-label"><span class="dot" style="width:8px;height:8px;border-radius:50%;display:inline-block;background:${getEngineColor(r.engine)}"></span>${r.engine}</div>
                            <div class="model-label">${r.model || ''}</div>
                        </div>
                        ${brandRows}
                        <div class="comparison-response">${escapeHtml(r.response || '')}</div>
                    </div>
                `;
            }).join('');
        }

        function getEngineColor(engine) {
            return {chatgpt: '#10b981', gemini: '#3b82f6', claude: '#f59e0b', perplexity: '#8b5cf6'}[engine] || '#94a3b8';
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function addToHistory(data) {
            queryHistory.unshift(data);
            if (queryHistory.length > 20) queryHistory.pop();
            renderHistory();
        }

        function renderHistory() {
            const container = document.getElementById('query-history');
            const list = document.getElementById('history-list');
            if (queryHistory.length === 0) { container.style.display = 'none'; return; }
            container.style.display = 'block';

            list.innerHTML = queryHistory.map((q, idx) => {
                const badges = q.results.map(r => {
                    if (r.error) return `<span class="badge badge-no" style="font-size:11px;">${r.engine}: error</span>`;
                    const mentioned = (r.brands || []).filter(b => b.mentioned).length;
                    const total = (r.brands || []).length;
                    const cls = mentioned > 0 ? 'badge-yes' : 'badge-no';
                    return `<span class="badge ${cls}" style="font-size:11px;">${r.engine}: ${mentioned}/${total}</span>`;
                }).join('');

                return `
                    <div class="history-item" onclick="replayHistory(${idx})">
                        <div class="history-prompt">${escapeHtml(q.prompt)}</div>
                        <div class="history-badges">${badges}</div>
                    </div>
                `;
            }).join('');
        }

        function replayHistory(idx) {
            renderComparison(queryHistory[idx]);
            document.getElementById('query-prompt').value = queryHistory[idx].prompt;
        }
    </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8501)
