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
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import tempfile
import shutil

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


@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    return UPLOAD_PAGE_HTML


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
            avg_score = round(float(mentioned["Ranking Score"].mean()), 2) if not mentioned.empty else 0
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


@app.post("/api/upload-csv")
async def api_upload_csv(file: UploadFile = File(...)):
    """Upload CSV file and validate format"""
    try:
        # Check file extension
        if not file.filename.endswith('.csv'):
            return JSONResponse({"error": "File must be .csv format"}, status_code=400)

        # Save to temp file
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"uploaded_{file.filename}")

        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Validate CSV format (must have "prompt" column)
        prompts = []
        with open(temp_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "prompt" not in reader.fieldnames:
                return JSONResponse(
                    {"error": "CSV must have 'prompt' column"},
                    status_code=400
                )

            for row in reader:
                prompt = row.get("prompt", "").strip().strip('"')
                if prompt:
                    prompts.append(prompt)

        if not prompts:
            return JSONResponse({"error": "No prompts found in CSV"}, status_code=400)

        return {
            "success": True,
            "filename": file.filename,
            "temp_path": temp_path,
            "prompt_count": len(prompts),
            "prompts_preview": prompts[:5]  # Show first 5
        }

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/run-uploaded")
async def api_run_uploaded(request: Request):
    """Run batch test with uploaded CSV file"""
    body = await request.json()
    temp_path = body.get("temp_path")
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

            # Load prompts from uploaded file or default
            if temp_path and os.path.exists(temp_path):
                job_status["log"].append(f"Loading prompts from uploaded file: {temp_path}")
                prompts = []
                with open(temp_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        prompt = row.get("prompt", "").strip().strip('"')
                        if prompt:
                            prompts.append(prompt)
            else:
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


UPLOAD_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Upload CSV - AI Brand Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; }

        .header { background: linear-gradient(135deg, #1e293b, #334155); padding: 20px 32px; border-bottom: 1px solid #475569; display: flex; align-items: center; justify-content: space-between; }
        .header h1 { font-size: 24px; font-weight: 700; }
        .header h1 span { color: #60a5fa; }
        .header .subtitle { color: #94a3b8; font-size: 14px; margin-top: 4px; }

        .container { max-width: 900px; margin: 0 auto; padding: 40px 24px; }

        .upload-section { background: #1e293b; border-radius: 12px; padding: 32px; border: 1px solid #334155; margin-bottom: 24px; }
        .upload-section h2 { font-size: 20px; font-weight: 600; margin-bottom: 24px; display: flex; align-items: center; gap: 10px; }

        .upload-area { border: 2px dashed #475569; border-radius: 12px; padding: 40px; text-align: center; background: #0f172a; transition: all 0.3s; margin-bottom: 20px; }
        .upload-area:hover { border-color: #60a5fa; background: #1e293b; }
        .upload-area.dragover { border-color: #60a5fa; background: #1e293b; }

        .file-input-wrapper { position: relative; display: inline-block; width: 100%; }
        .file-input { width: 100%; padding: 12px; background: #334155; border: 1px solid #475569; border-radius: 8px; color: #e2e8f0; cursor: pointer; font-size: 14px; }
        .file-input::file-selector-button { background: #3b82f6; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; margin-right: 12px; font-weight: 600; }
        .file-input::file-selector-button:hover { background: #2563eb; }

        .upload-hint { color: #64748b; font-size: 13px; margin-top: 12px; }
        .upload-hint code { background: #334155; padding: 2px 6px; border-radius: 4px; color: #60a5fa; }

        .btn { padding: 12px 28px; border-radius: 8px; border: none; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
        .btn-primary { background: #3b82f6; color: white; }
        .btn-primary:hover { background: #2563eb; }
        .btn-primary:disabled { background: #475569; cursor: not-allowed; opacity: 0.6; }
        .btn-secondary { background: #334155; color: #e2e8f0; }
        .btn-secondary:hover { background: #475569; }

        .preview-box { background: #0f172a; padding: 20px; border-radius: 8px; margin-top: 20px; display: none; border: 1px solid #334155; }
        .preview-box.visible { display: block; }
        .preview-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
        .preview-title { font-size: 15px; font-weight: 600; color: #34d399; display: flex; align-items: center; gap: 8px; }
        .preview-info { font-size: 13px; color: #cbd5e1; }
        .preview-info strong { color: #e2e8f0; }
        .preview-prompts { background: #1e293b; padding: 12px; border-radius: 6px; margin-top: 12px; font-size: 12px; color: #94a3b8; max-height: 150px; overflow-y: auto; }
        .preview-prompts div { padding: 4px 0; border-bottom: 1px solid #334155; }
        .preview-prompts div:last-child { border-bottom: none; }

        .error-box { background: #7f1d1d33; color: #f87171; padding: 16px; border-radius: 8px; margin-top: 20px; font-size: 14px; display: none; border: 1px solid #7f1d1d; }
        .error-box.visible { display: block; }

        .engine-section { background: #1e293b; border-radius: 12px; padding: 32px; border: 1px solid #334155; margin-bottom: 24px; }
        .engine-section h3 { font-size: 16px; font-weight: 600; margin-bottom: 16px; color: #94a3b8; }
        .engine-toggles { display: flex; gap: 12px; flex-wrap: wrap; }
        .toggle-label { display: flex; align-items: center; gap: 8px; padding: 10px 18px; border-radius: 8px; border: 1px solid #475569; cursor: pointer; transition: all 0.2s; background: #0f172a; }
        .toggle-label:hover { border-color: #60a5fa; background: #1e293b; }
        .toggle-label input { accent-color: #60a5fa; cursor: pointer; }
        .toggle-label input:checked + span { color: #60a5fa; font-weight: 600; }

        .run-section { background: #1e293b; border-radius: 12px; padding: 32px; border: 1px solid #334155; }
        .run-section .btn { width: 100%; }

        .log-box { background: #0f172a; border-radius: 8px; padding: 16px; margin-top: 16px; font-family: monospace; font-size: 13px; max-height: 300px; overflow-y: auto; display: none; border: 1px solid #334155; }
        .log-box.visible { display: block; }
        .log-line { padding: 3px 0; color: #94a3b8; }
        .log-line.success { color: #34d399; }
        .log-line.error { color: #f87171; }
        .log-line.info { color: #60a5fa; }

        .back-link { display: inline-flex; align-items: center; gap: 8px; color: #60a5fa; text-decoration: none; font-size: 14px; margin-bottom: 24px; transition: all 0.2s; }
        .back-link:hover { color: #3b82f6; }

        .info-box { background: #1e40af22; border: 1px solid #3b82f6; color: #93c5fd; padding: 16px; border-radius: 8px; margin-bottom: 24px; font-size: 14px; }
        .info-box strong { color: #60a5fa; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>📤 Upload <span>Custom CSV</span></h1>
            <div class="subtitle">Run batch tests with your own prompt file</div>
        </div>
    </div>

    <div class="container">
        <a href="/" class="back-link">← Back to Dashboard</a>

        <div class="info-box">
            <strong>CSV Format:</strong> Your file must have a <code style="background:#1e293b;padding:2px 6px;border-radius:4px;">prompt</code> column with one prompt per row.
        </div>

        <!-- Upload Section -->
        <div class="upload-section">
            <h2>📁 Select CSV File</h2>

            <div class="upload-area" id="upload-area">
                <div style="font-size: 48px; margin-bottom: 16px;">📄</div>
                <div class="file-input-wrapper">
                    <input type="file" id="csv-upload" class="file-input" accept=".csv">
                </div>
                <div class="upload-hint">
                    Accepted format: <code>.csv</code> • Required column: <code>prompt</code>
                </div>
            </div>

            <button class="btn btn-primary" id="validate-btn" onclick="validateCSV()" style="width: 100%;">
                Validate CSV
            </button>

            <!-- Preview Box -->
            <div class="preview-box" id="preview-box">
                <div class="preview-header">
                    <div class="preview-title">
                        <span>✅</span> Valid CSV File
                    </div>
                    <button class="btn btn-secondary" style="padding: 6px 14px; font-size: 12px;" onclick="resetUpload()">
                        Change File
                    </button>
                </div>
                <div class="preview-info" id="preview-info">
                    <strong>File:</strong> <span id="file-name">—</span><br>
                    <strong>Prompts Found:</strong> <span id="prompt-count">—</span>
                </div>
                <div style="margin-top: 16px; font-size: 13px; color: #94a3b8; font-weight: 600;">
                    Preview (first 5 prompts):
                </div>
                <div class="preview-prompts" id="preview-prompts"></div>
            </div>

            <!-- Error Box -->
            <div class="error-box" id="error-box"></div>
        </div>

        <!-- Engine Selection -->
        <div class="engine-section" id="engine-section" style="display: none;">
            <h3>⚙️ Select AI Engines</h3>
            <div class="engine-toggles">
                <label class="toggle-label">
                    <input type="checkbox" value="chatgpt" checked>
                    <span>ChatGPT</span>
                </label>
                <label class="toggle-label">
                    <input type="checkbox" value="gemini" checked>
                    <span>Gemini</span>
                </label>
                <label class="toggle-label">
                    <input type="checkbox" value="claude" checked>
                    <span>Claude</span>
                </label>
                <label class="toggle-label">
                    <input type="checkbox" value="perplexity">
                    <span>Perplexity</span>
                </label>
            </div>
        </div>

        <!-- Run Section -->
        <div class="run-section" id="run-section" style="display: none;">
            <button class="btn btn-primary" id="run-btn" onclick="startUploadedRun()">
                🚀 Run Batch Test
            </button>
            <div class="log-box" id="log-box"></div>
        </div>
    </div>

    <script>
        let uploadedCSVPath = null;

        // Drag and drop
        const uploadArea = document.getElementById('upload-area');
        const fileInput = document.getElementById('csv-upload');

        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) {
                fileInput.files = e.dataTransfer.files;
                validateCSV();
            }
        });

        // Auto-validate on file selection
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length > 0) {
                validateCSV();
            }
        });

        async function validateCSV() {
            const file = fileInput.files[0];

            if (!file) {
                showError('Please select a CSV file');
                return;
            }

            if (!file.name.endsWith('.csv')) {
                showError('File must be in .csv format');
                return;
            }

            const validateBtn = document.getElementById('validate-btn');
            validateBtn.disabled = true;
            validateBtn.textContent = 'Validating...';

            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await fetch('/api/upload-csv', {
                    method: 'POST',
                    body: formData
                });

                const data = await res.json();

                if (data.success) {
                    uploadedCSVPath = data.temp_path;
                    showPreview(data);
                    hideError();
                } else {
                    showError(data.error);
                    hidePreview();
                }
            } catch (error) {
                showError('Error uploading file: ' + error.message);
                hidePreview();
            } finally {
                validateBtn.disabled = false;
                validateBtn.textContent = 'Validate CSV';
            }
        }

        function showPreview(data) {
            document.getElementById('file-name').textContent = data.filename;
            document.getElementById('prompt-count').textContent = data.prompt_count;

            const previewPrompts = document.getElementById('preview-prompts');
            previewPrompts.innerHTML = data.prompts_preview.map((p, i) =>
                `<div>${i + 1}. ${escapeHtml(p.substring(0, 100))}${p.length > 100 ? '...' : ''}</div>`
            ).join('');

            document.getElementById('preview-box').classList.add('visible');
            document.getElementById('engine-section').style.display = 'block';
            document.getElementById('run-section').style.display = 'block';
        }

        function hidePreview() {
            document.getElementById('preview-box').classList.remove('visible');
            document.getElementById('engine-section').style.display = 'none';
            document.getElementById('run-section').style.display = 'none';
            uploadedCSVPath = null;
        }

        function showError(message) {
            const errorBox = document.getElementById('error-box');
            errorBox.textContent = message;
            errorBox.classList.add('visible');
        }

        function hideError() {
            document.getElementById('error-box').classList.remove('visible');
        }

        function resetUpload() {
            fileInput.value = '';
            hidePreview();
            hideError();
        }

        async function startUploadedRun() {
            const engines = [...document.querySelectorAll('.engine-toggles input:checked')].map(c => c.value);

            if (engines.length === 0) {
                showError('Please select at least one AI engine');
                return;
            }

            if (!uploadedCSVPath) {
                showError('No CSV file uploaded. Please upload and validate a file first.');
                return;
            }

            const runBtn = document.getElementById('run-btn');
            const logBox = document.getElementById('log-box');

            runBtn.disabled = true;
            runBtn.textContent = '⏳ Running...';
            logBox.classList.add('visible');
            logBox.innerHTML = '<div class="log-line info">📤 Starting batch test with uploaded CSV...</div>';

            try {
                await fetch('/api/run-uploaded', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        engines: engines,
                        temp_path: uploadedCSVPath
                    })
                });

                // Poll for status
                const poll = setInterval(async () => {
                    const res = await fetch('/api/status');
                    const status = await res.json();

                    logBox.innerHTML = status.log.map(l =>
                        `<div class="log-line ${l.includes('Done') ? 'success' : l.includes('Error') ? 'error' : 'info'}">${escapeHtml(l)}</div>`
                    ).join('') + `<div class="log-line info">${escapeHtml(status.progress)}</div>`;
                    logBox.scrollTop = logBox.scrollHeight;

                    if (!status.running) {
                        clearInterval(poll);
                        runBtn.disabled = false;
                        runBtn.textContent = '🚀 Run Batch Test';

                        if (status.log.some(l => l.includes('Done'))) {
                            logBox.innerHTML += '<div class="log-line success">✅ Test completed! <a href="/" style="color:#60a5fa;text-decoration:underline;">View results on dashboard</a></div>';
                        }
                    }
                }, 2000);
            } catch (error) {
                logBox.innerHTML += `<div class="log-line error">❌ Error: ${escapeHtml(error.message)}</div>`;
                runBtn.disabled = false;
                runBtn.textContent = '🚀 Run Batch Test';
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    </script>
</body>
</html>"""


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Brand Monitor - GEO Analytics</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        :root {
            --color-bg: #fafafa;
            --color-surface: #ffffff;
            --color-border: #e4e4e7;
            --color-text: #18181b;
            --color-text-light: #71717a;
            --color-text-lighter: #a1a1aa;
            --color-primary: #0ea5e9;
            --color-primary-hover: #0284c7;
            --color-success: #22c55e;
            --color-warning: #f59e0b;
            --color-error: #ef4444;
            --sidebar-width: 260px;
            --header-height: 64px;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--color-bg);
            color: var(--color-text);
            font-size: 14px;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        /* Sidebar */
        .sidebar {
            position: fixed;
            left: 0;
            top: 0;
            width: var(--sidebar-width);
            height: 100vh;
            background: var(--color-surface);
            border-right: 1px solid var(--color-border);
            padding: 24px 0;
            z-index: 100;
        }

        .logo {
            padding: 0 24px 24px;
            border-bottom: 1px solid var(--color-border);
            margin-bottom: 24px;
        }

        .logo h1 {
            font-size: 20px;
            font-weight: 800;
            color: var(--color-text);
            letter-spacing: -0.5px;
        }

        .logo .subtitle {
            font-size: 12px;
            color: var(--color-text-lighter);
            margin-top: 4px;
            font-weight: 500;
        }

        .nav {
            padding: 0 12px;
        }

        .nav-item {
            display: flex;
            align-items: center;
            padding: 10px 12px;
            margin-bottom: 2px;
            border-radius: 8px;
            color: var(--color-text-light);
            text-decoration: none;
            font-weight: 500;
            font-size: 14px;
            transition: all 0.15s ease;
            cursor: pointer;
        }

        .nav-item:hover {
            background: var(--color-bg);
            color: var(--color-text);
        }

        .nav-item.active {
            background: var(--color-primary);
            color: white;
        }

        .nav-item .icon {
            width: 20px;
            margin-right: 12px;
            font-size: 18px;
        }

        /* Main Content */
        .main {
            margin-left: var(--sidebar-width);
            min-height: 100vh;
        }

        .header {
            height: var(--header-height);
            background: var(--color-surface);
            border-bottom: 1px solid var(--color-border);
            padding: 0 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 50;
        }

        .header-left h2 {
            font-size: 18px;
            font-weight: 700;
            color: var(--color-text);
        }

        .header-right {
            display: flex;
            gap: 16px;
            align-items: center;
        }

        .stat-pill {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 12px;
            background: var(--color-bg);
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
        }

        .stat-pill .label {
            color: var(--color-text-lighter);
        }

        .stat-pill .value {
            color: var(--color-text);
        }

        .content {
            padding: 32px;
            max-width: 1600px;
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 32px;
        }

        .stat-card {
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 12px;
            padding: 20px;
            transition: all 0.2s ease;
        }

        .stat-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            border-color: var(--color-primary);
        }

        .stat-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
        }

        .stat-title {
            font-size: 13px;
            font-weight: 600;
            color: var(--color-text-lighter);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .stat-icon {
            width: 36px;
            height: 36px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
        }

        .stat-value {
            font-size: 32px;
            font-weight: 700;
            color: var(--color-text);
            letter-spacing: -1px;
            margin-bottom: 4px;
        }

        .stat-change {
            font-size: 12px;
            font-weight: 600;
            color: var(--color-text-light);
        }

        .stat-change.positive { color: var(--color-success); }
        .stat-change.negative { color: var(--color-error); }

        /* Engine Cards */
        .engines-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 20px;
            margin-bottom: 32px;
        }

        .engine-card {
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 12px;
            padding: 24px;
            transition: all 0.2s ease;
        }

        .engine-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }

        .engine-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 20px;
        }

        .engine-logo {
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            font-weight: 700;
        }

        .engine-info h3 {
            font-size: 16px;
            font-weight: 700;
            color: var(--color-text);
        }

        .engine-info p {
            font-size: 12px;
            color: var(--color-text-lighter);
        }

        .engine-stats {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px;
            margin-bottom: 20px;
        }

        .engine-stat {
            text-align: center;
        }

        .engine-stat-value {
            font-size: 24px;
            font-weight: 700;
            color: var(--color-text);
        }

        .engine-stat-label {
            font-size: 11px;
            color: var(--color-text-lighter);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 4px;
        }

        .progress-bar {
            height: 8px;
            background: var(--color-bg);
            border-radius: 4px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.6s ease;
        }

        .engine-card.chatgpt .progress-fill { background: linear-gradient(90deg, #10b981, #34d399); }
        .engine-card.gemini .progress-fill { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
        .engine-card.claude .progress-fill { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
        .engine-card.perplexity .progress-fill { background: linear-gradient(90deg, #8b5cf6, #a78bfa); }

        /* Table */
        .table-container {
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 12px;
            overflow: hidden;
        }

        .table-header {
            padding: 20px 24px;
            border-bottom: 1px solid var(--color-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .table-title {
            font-size: 16px;
            font-weight: 700;
            color: var(--color-text);
        }

        .filter-tabs {
            display: flex;
            gap: 8px;
        }

        .filter-tab {
            padding: 6px 12px;
            border-radius: 6px;
            border: 1px solid var(--color-border);
            background: transparent;
            color: var(--color-text-light);
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .filter-tab:hover {
            background: var(--color-bg);
        }

        .filter-tab.active {
            background: var(--color-text);
            color: white;
            border-color: var(--color-text);
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th {
            text-align: left;
            padding: 12px 24px;
            font-size: 12px;
            font-weight: 700;
            color: var(--color-text-lighter);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid var(--color-border);
            background: var(--color-bg);
        }

        td {
            padding: 16px 24px;
            border-bottom: 1px solid var(--color-border);
            font-size: 14px;
        }

        tr:hover td {
            background: var(--color-bg);
        }

        .badge {
            display: inline-flex;
            align-items: center;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
        }

        .badge-success {
            background: rgba(34, 197, 94, 0.1);
            color: #16a34a;
        }

        .badge-error {
            background: rgba(239, 68, 68, 0.1);
            color: #dc2626;
        }

        .badge-primary {
            background: rgba(14, 165, 233, 0.1);
            color: #0284c7;
        }

        /* Buttons */
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 16px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.15s ease;
            border: none;
        }

        .btn-primary {
            background: var(--color-primary);
            color: white;
        }

        .btn-primary:hover {
            background: var(--color-primary-hover);
        }

        /* Section */
        .section {
            display: none;
        }

        .section.active {
            display: block;
        }

        .section-header {
            margin-bottom: 24px;
        }

        .section-title {
            font-size: 24px;
            font-weight: 700;
            color: var(--color-text);
            margin-bottom: 8px;
        }

        .section-subtitle {
            font-size: 14px;
            color: var(--color-text-light);
        }

        /* Upload Form */
        .upload-form {
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 12px;
            padding: 32px;
            max-width: 600px;
        }

        .upload-form h3 {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 16px;
            color: var(--color-text);
        }

        .upload-form p {
            font-size: 14px;
            color: var(--color-text-light);
            margin-bottom: 24px;
        }

        .upload-form .btn {
            width: 100%;
        }

        /* History Section */
        .history-list {
            display: grid;
            gap: 16px;
        }

        .history-card {
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 12px;
            padding: 20px;
            transition: all 0.2s ease;
        }

        .history-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            border-color: var(--color-primary);
        }

        .history-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .history-date {
            font-size: 12px;
            color: var(--color-text-lighter);
            font-weight: 600;
        }

        .history-stats {
            display: flex;
            gap: 12px;
            font-size: 12px;
            color: var(--color-text-light);
        }

        .history-content {
            font-size: 14px;
            color: var(--color-text);
            line-height: 1.6;
        }
    </style>
</head>
<body>
    <!-- Sidebar -->
    <div class="sidebar">
        <div class="logo">
            <h1>BrandMonitor</h1>
            <div class="subtitle">GEO Analytics</div>
        </div>
        <nav class="nav">
            <a class="nav-item active" onclick="switchSection('overview')">
                <span class="icon">📊</span>
                Overview
            </a>
            <a class="nav-item" onclick="switchSection('history')">
                <span class="icon">🕐</span>
                History
            </a>
            <a class="nav-item" onclick="switchSection('upload')">
                <span class="icon">📤</span>
                Upload CSV
            </a>
        </nav>
    </div>

    <!-- Main Content -->
    <div class="main">
        <div class="header">
            <div class="header-left">
                <h2 id="page-title">Dashboard</h2>
            </div>
            <div class="header-right">
                <div class="stat-pill">
                    <span class="label">Brand:</span>
                    <span class="value" id="brand-name">Mondelez</span>
                </div>
                <div class="stat-pill">
                    <span class="label">Prompts:</span>
                    <span class="value" id="prompt-count">—</span>
                </div>
            </div>
        </div>

        <div class="content">
            <!-- Overview Section -->
            <div id="section-overview" class="section active">
                <div class="section-header">
                    <h1 class="section-title">Performance Overview</h1>
                    <p class="section-subtitle">AI visibility metrics across all engines</p>
                </div>

                <!-- Stats Grid -->
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-header">
                            <div class="stat-title">Total Mentions</div>
                            <div class="stat-icon" style="background: rgba(34, 197, 94, 0.1); color: #16a34a;">
                                💬
                            </div>
                        </div>
                        <div class="stat-value" id="total-mentions">—</div>
                        <div class="stat-change" id="total-mention-rate"></div>
                    </div>

                    <div class="stat-card">
                        <div class="stat-header">
                            <div class="stat-title">Best Avg Rank</div>
                            <div class="stat-icon" style="background: rgba(14, 165, 233, 0.1); color: #0284c7;">
                                🏆
                            </div>
                        </div>
                        <div class="stat-value" id="best-rank">—</div>
                        <div class="stat-change" id="best-rank-engine"></div>
                    </div>

                    <div class="stat-card">
                        <div class="stat-header">
                            <div class="stat-title">Best Avg Score</div>
                            <div class="stat-icon" style="background: rgba(245, 158, 11, 0.1); color: #d97706;">
                                ⭐
                            </div>
                        </div>
                        <div class="stat-value" id="best-score">—</div>
                        <div class="stat-change" id="best-score-engine"></div>
                    </div>

                    <div class="stat-card">
                        <div class="stat-header">
                            <div class="stat-title">Engines Tested</div>
                            <div class="stat-icon" style="background: rgba(139, 92, 246, 0.1); color: #7c3aed;">
                                🤖
                            </div>
                        </div>
                        <div class="stat-value" id="engine-count">—</div>
                        <div class="stat-change" id="engine-list"></div>
                    </div>
                </div>

                <!-- Engine Performance -->
                <div class="section-header">
                    <h2 class="section-title" style="font-size: 20px;">Engine Performance</h2>
                    <p class="section-subtitle">Breakdown by AI platform</p>
                </div>

                <div class="engines-grid" id="engine-grid"></div>

                <!-- Query Results Table -->
                <div class="table-container">
                    <div class="table-header">
                        <div class="table-title">Recent Queries</div>
                        <div class="filter-tabs">
                            <button class="filter-tab active" onclick="filterTable('all', this)">All</button>
                            <button class="filter-tab" onclick="filterTable('yes', this)">Mentioned</button>
                            <button class="filter-tab" onclick="filterTable('no', this)">Not Mentioned</button>
                        </div>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Query</th>
                                <th>Engine</th>
                                <th>Status</th>
                                <th>Rank</th>
                                <th>Score</th>
                            </tr>
                        </thead>
                        <tbody id="results-tbody"></tbody>
                    </table>
                </div>
            </div>

            <!-- History Section -->
            <div id="section-history" class="section">
                <div class="section-header">
                    <h1 class="section-title">Test History</h1>
                    <p class="section-subtitle">View previous test runs and results</p>
                </div>
                <div class="history-list" id="history-container">
                    <!-- Will be populated by JavaScript -->
                </div>
            </div>

            <!-- Upload CSV Section -->
            <div id="section-upload" class="section">
                <div class="section-header">
                    <h1 class="section-title">Test Prompts</h1>
                    <p class="section-subtitle">Test single prompts or upload batch CSV files</p>
                </div>
                <div style="max-width: 800px;">
                    <!-- Quick Test: Single Prompt -->
                    <div style="background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 12px; padding: 32px; margin-bottom: 24px;">
                        <h3 style="font-size: 16px; font-weight: 700; margin-bottom: 12px;">⚡ Quick Test - Single Prompt</h3>
                        <p style="color: var(--color-text-light); margin-bottom: 24px;">
                            Test a single prompt across selected AI engines instantly
                        </p>

                        <form id="quick-test-form" style="margin-bottom: 24px;">
                            <div style="margin-bottom: 16px;">
                                <label style="display: block; font-weight: 600; margin-bottom: 8px; font-size: 14px;">Enter Your Prompt</label>
                                <textarea id="quick-prompt" required
                                    placeholder="e.g., What are the best chocolate brands for gifting?"
                                    style="width: 100%; min-height: 100px; padding: 12px; border: 1px solid var(--color-border); border-radius: 8px; font-size: 14px; background: var(--color-bg); font-family: inherit; resize: vertical;"></textarea>
                            </div>

                            <div style="margin-bottom: 16px;">
                                <label style="display: block; font-weight: 600; margin-bottom: 8px; font-size: 14px;">Brands to Track <span style="font-weight: 400; color: var(--color-text-light);">(comma-separated)</span></label>
                                <input type="text" id="quick-brands" required
                                    placeholder="e.g., Mondelez, Nestlé, Mars, Ferrero, Hershey"
                                    value="Mondelez, Nestlé, Mars, PepsiCo, Orion"
                                    style="width: 100%; padding: 12px; border: 1px solid var(--color-border); border-radius: 8px; font-size: 14px; background: var(--color-bg);">
                                <p style="font-size: 12px; color: var(--color-text-light); margin-top: 4px;">These brands will be tracked and scored according to AI Visibility Score formula</p>
                            </div>

                            <div style="margin-bottom: 24px;">
                                <label style="display: block; font-weight: 600; margin-bottom: 8px; font-size: 14px;">Select AI Engines</label>
                                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;">
                                    <label style="display: flex; align-items: center; padding: 12px; background: var(--color-bg); border: 1px solid var(--color-border); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" name="quick-engines" value="chatgpt" checked style="margin-right: 8px;">
                                        <span style="font-weight: 600;">ChatGPT <span style="font-size: 10px; color: var(--color-text-lighter);">(Auto-fallback)</span></span>
                                    </label>
                                    <label style="display: flex; align-items: center; padding: 12px; background: var(--color-bg); border: 1px solid var(--color-border); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" name="quick-engines" value="gemini" checked style="margin-right: 8px;">
                                        <span style="font-weight: 600;">Gemini</span>
                                    </label>
                                    <label style="display: flex; align-items: center; padding: 12px; background: var(--color-bg); border: 1px solid var(--color-border); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" name="quick-engines" value="claude" checked style="margin-right: 8px;">
                                        <span style="font-weight: 600;">Claude</span>
                                    </label>
                                    <label style="display: flex; align-items: center; padding: 12px; background: var(--color-bg); border: 1px solid var(--color-border); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" name="quick-engines" value="perplexity" checked style="margin-right: 8px;">
                                        <span style="font-weight: 600;">Perplexity</span>
                                    </label>
                                </div>
                            </div>

                            <button type="submit" id="quick-test-btn"
                                style="width: 100%; padding: 14px; background: var(--color-primary); color: white; border: none; border-radius: 8px; font-weight: 600; font-size: 14px; cursor: pointer; transition: all 0.2s;">
                                ⚡ Test Now
                            </button>
                        </form>

                        <div id="quick-status" style="display: none; padding: 16px; border-radius: 8px; font-size: 14px; margin-bottom: 16px;"></div>
                        <div id="quick-progress" style="display: none;">
                            <div style="height: 8px; background: var(--color-bg); border-radius: 4px; overflow: hidden; margin-bottom: 8px;">
                                <div id="quick-progress-bar" style="height: 100%; background: var(--color-primary); width: 0%; transition: width 0.3s;"></div>
                            </div>
                            <p id="quick-progress-text" style="font-size: 13px; color: var(--color-text-light); text-align: center;"></p>
                        </div>

                        <!-- Quick Test Results -->
                        <div id="quick-results" style="display: none; margin-top: 24px; padding-top: 24px; border-top: 1px solid var(--color-border);">
                            <h4 style="font-size: 14px; font-weight: 700; margin-bottom: 16px;">🎯 Results</h4>
                            <div id="quick-results-content"></div>
                        </div>
                    </div>

                    <!-- Batch Upload: CSV -->
                    <div style="background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 12px; padding: 32px;">
                        <h3 style="font-size: 16px; font-weight: 700; margin-bottom: 12px;">📤 Batch Upload - CSV File</h3>
                        <p style="color: var(--color-text-light); margin-bottom: 24px;">
                            Upload a CSV file to test multiple prompts at once. File must have a <code style="background:#f3f4f6;padding:2px 6px;border-radius:4px;">prompt</code> column.
                        </p>

                        <form id="upload-form" enctype="multipart/form-data" style="margin-bottom: 24px;">
                            <div style="margin-bottom: 16px;">
                                <label style="display: block; font-weight: 600; margin-bottom: 8px; font-size: 14px;">Select CSV File</label>
                                <input type="file" id="csv-file" name="file" accept=".csv" required
                                    style="width: 100%; padding: 10px 12px; border: 1px solid var(--color-border); border-radius: 8px; font-size: 14px; background: var(--color-bg);">
                            </div>

                            <div style="margin-bottom: 24px;">
                                <label style="display: block; font-weight: 600; margin-bottom: 8px; font-size: 14px;">Select AI Engines</label>
                                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;">
                                    <label style="display: flex; align-items: center; padding: 12px; background: var(--color-bg); border: 1px solid var(--color-border); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" name="engines" value="chatgpt" checked style="margin-right: 8px;">
                                        <span style="font-weight: 600;">ChatGPT <span style="font-size: 10px; color: var(--color-text-lighter);">(Auto-fallback)</span></span>
                                    </label>
                                    <label style="display: flex; align-items: center; padding: 12px; background: var(--color-bg); border: 1px solid var(--color-border); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" name="engines" value="gemini" checked style="margin-right: 8px;">
                                        <span style="font-weight: 600;">Gemini</span>
                                    </label>
                                    <label style="display: flex; align-items: center; padding: 12px; background: var(--color-bg); border: 1px solid var(--color-border); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" name="engines" value="claude" checked style="margin-right: 8px;">
                                        <span style="font-weight: 600;">Claude</span>
                                    </label>
                                    <label style="display: flex; align-items: center; padding: 12px; background: var(--color-bg); border: 1px solid var(--color-border); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" name="engines" value="perplexity" checked style="margin-right: 8px;">
                                        <span style="font-weight: 600;">Perplexity</span>
                                    </label>
                                </div>
                            </div>

                            <button type="submit" id="upload-btn"
                                style="width: 100%; padding: 14px; background: var(--color-primary); color: white; border: none; border-radius: 8px; font-weight: 600; font-size: 14px; cursor: pointer; transition: all 0.2s;">
                                📤 Upload and Start Test
                            </button>
                        </form>

                        <div id="upload-status" style="display: none; padding: 16px; border-radius: 8px; font-size: 14px;"></div>
                        <div id="upload-progress" style="display: none;">
                            <div style="height: 8px; background: var(--color-bg); border-radius: 4px; overflow: hidden; margin-bottom: 8px;">
                                <div id="progress-bar" style="height: 100%; background: var(--color-primary); width: 0%; transition: width 0.3s;"></div>
                            </div>
                            <p id="progress-text" style="font-size: 13px; color: var(--color-text-light); text-align: center;"></p>
                        </div>
                    </div>

                    <div style="background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 12px; padding: 24px; margin-top: 20px;">
                        <h4 style="font-size: 14px; font-weight: 700; margin-bottom: 12px;">📋 CSV Format Example</h4>
                        <pre style="background: var(--color-bg); padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; border: 1px solid var(--color-border);">prompt
"What are the best chocolate brands?"
"Which snack company has healthiest products?"
"Compare Oreo vs other sandwich cookies"</pre>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let allData = [];
        let currentFilter = 'all';

        function switchSection(sectionName) {
            // Update nav
            document.querySelectorAll('.nav-item').forEach(item => {
                item.classList.remove('active');
            });
            if (event && event.currentTarget) {
                event.currentTarget.classList.add('active');
            }

            // Update sections
            document.querySelectorAll('.section').forEach(sec => {
                sec.classList.remove('active');
            });
            document.getElementById('section-' + sectionName).classList.add('active');

            // Update header title
            const titles = {
                overview: 'Dashboard',
                history: 'Test History',
                upload: 'Upload CSV'
            };
            document.querySelector('.header-left h2').textContent = titles[sectionName] || 'Dashboard';

            // Load history if switching to history tab
            if (sectionName === 'history') {
                loadHistory();
            }
        }

        async function loadData() {
            const [resultsRes, promptsRes, configRes] = await Promise.all([
                fetch('/api/results'), fetch('/api/prompts'), fetch('/api/config')
            ]);
            const results = await resultsRes.json();
            const prompts = await promptsRes.json();
            const config = await configRes.json();

            document.getElementById('brand-name').textContent = (config.brands || ['Mondelez'])[0];
            document.getElementById('prompt-count').textContent = prompts.count;

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
            const engineLogos = {
                chatgpt: { icon: '🤖', bg: 'rgba(16, 185, 129, 0.1)', color: '#059669' },
                gemini: { icon: '✨', bg: 'rgba(59, 130, 246, 0.1)', color: '#2563eb' },
                claude: { icon: '🧠', bg: 'rgba(245, 158, 11, 0.1)', color: '#d97706' },
                perplexity: { icon: '🔍', bg: 'rgba(139, 92, 246, 0.1)', color: '#7c3aed' }
            };
            engines.forEach(eng => {
                const s = summary[eng];
                const logo = engineLogos[eng] || { icon: '🤖', bg: 'rgba(100, 116, 139, 0.1)', color: '#64748b' };
                grid.innerHTML += `
                    <div class="engine-card ${eng}">
                        <div class="engine-header">
                            <div class="engine-logo" style="background: ${logo.bg}; color: ${logo.color};">
                                ${logo.icon}
                            </div>
                            <div class="engine-info">
                                <h3>${eng.charAt(0).toUpperCase() + eng.slice(1)}</h3>
                                <p>${s.total} queries</p>
                            </div>
                        </div>
                        <div class="engine-stats">
                            <div class="engine-stat">
                                <div class="engine-stat-value">${s.mentions}</div>
                                <div class="engine-stat-label">Mentions</div>
                            </div>
                            <div class="engine-stat">
                                <div class="engine-stat-value">${s.avg_rank ? '#' + s.avg_rank : '—'}</div>
                                <div class="engine-stat-label">Avg Rank</div>
                            </div>
                        </div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${s.mention_rate}%"></div>
                        </div>
                    </div>
                `;
            });

            renderTable();
        }

        function renderTable() {
            const tbody = document.getElementById('results-tbody');
            const mentionCol = Object.keys(allData[0] || {}).find(k => k.includes('Mention')) || 'Mondelez Mention';

            let filtered = allData;
            if (currentFilter === 'yes') filtered = allData.filter(r => r[mentionCol] === 'Yes');
            if (currentFilter === 'no') filtered = allData.filter(r => r[mentionCol] === 'No');

            tbody.innerHTML = filtered.slice(0, 100).map((r, i) => {
                const mentioned = r[mentionCol] === 'Yes';
                const eng = r['AI Engine'] || '';
                return `<tr>
                    <td style="max-width: 400px;">${(r.Query || '').substring(0, 100)}${(r.Query || '').length > 100 ? '...' : ''}</td>
                    <td><span class="badge badge-primary">${eng}</span></td>
                    <td><span class="badge ${mentioned ? 'badge-success' : 'badge-error'}">${mentioned ? 'Mentioned' : 'Not Mentioned'}</span></td>
                    <td>${r.Rank != null && !isNaN(r.Rank) ? '#' + Math.round(r.Rank) : '—'}</td>
                    <td>${r['Ranking Score'] || 0}</td>
                </tr>`;
            }).join('');
        }

        function filterTable(filter, btn) {
            currentFilter = filter;
            document.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderTable();
        }

        // Quick Test handler
        document.getElementById('quick-test-form').addEventListener('submit', async (e) => {
            e.preventDefault();

            const prompt = document.getElementById('quick-prompt').value.trim();
            const brandsInput = document.getElementById('quick-brands').value.trim();
            const checkedEngines = Array.from(document.querySelectorAll('input[name="quick-engines"]:checked')).map(e => e.value);

            if (!prompt) {
                showQuickStatus('Please enter a prompt', 'error');
                return;
            }

            if (!brandsInput) {
                showQuickStatus('Please enter brands to track', 'error');
                return;
            }

            if (checkedEngines.length === 0) {
                showQuickStatus('Please select at least one AI engine', 'error');
                return;
            }

            // Parse brands
            const brands = brandsInput.split(',').map(b => b.trim()).filter(b => b);

            showQuickStatus('Testing prompt across engines...', 'info');
            document.getElementById('quick-progress').style.display = 'block';
            document.getElementById('quick-test-btn').disabled = true;
            document.getElementById('quick-results').style.display = 'none';

            try {
                updateQuickProgress(10, 'Sending request...');

                const res = await fetch('/api/query', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        prompt: prompt,
                        engines: checkedEngines,
                        brands: brands
                    })
                });

                if (!res.ok) {
                    const error = await res.json();
                    throw new Error(error.error || 'Test failed');
                }

                updateQuickProgress(80, 'Processing results...');
                const data = await res.json();

                updateQuickProgress(100, 'Complete!');
                showQuickStatus('✅ Test completed successfully!', 'success');
                displayQuickResults(prompt, brands, data.results || []);

            } catch (error) {
                showQuickStatus(`❌ Error: ${error.message}`, 'error');
                document.getElementById('quick-results').style.display = 'none';
            } finally {
                document.getElementById('quick-progress').style.display = 'none';
                document.getElementById('quick-test-btn').disabled = false;
            }
        });

        function showQuickStatus(message, type) {
            const status = document.getElementById('quick-status');
            status.style.display = 'block';
            status.textContent = message;
            status.style.background = type === 'success' ? '#d1fae5' : type === 'error' ? '#fee2e2' : '#dbeafe';
            status.style.color = type === 'success' ? '#065f46' : type === 'error' ? '#991b1b' : '#1e40af';
        }

        function updateQuickProgress(percent, text) {
            document.getElementById('quick-progress-bar').style.width = percent + '%';
            document.getElementById('quick-progress-text').textContent = text;
        }

        function calculateAIVisibilityScores(trackedBrands, results) {
            const brandScores = trackedBrands.map(brand => {
                let totalMentions = 0;
                let totalRankScore = 0;
                let totalCitationScore = 0;
                let totalPrompts = results.length;

                results.forEach(result => {
                    if (result.error) return;

                    const brandData = result.brands.find(b => b.brand.toLowerCase() === brand.toLowerCase());
                    if (!brandData) return;

                    // Mention Score
                    if (brandData.mentioned) totalMentions++;

                    // Ranking Score (100/80/60/40/20/0 for ranks 1-6+)
                    if (brandData.mentioned && brandData.rank) {
                        const rankPoints = {
                            1: 100, 2: 80, 3: 60, 4: 40, 5: 20
                        };
                        totalRankScore += rankPoints[brandData.rank] || 0;
                    } else if (brandData.mentioned) {
                        totalRankScore += 0; // Mentioned but no rank
                    }

                    // Citation Score (100=official, 50=other, 0=none)
                    if (brandData.sources && brandData.sources.length > 0) {
                        // Check if any source is official (simplified - would need official domain list)
                        const hasOfficialDomain = brandData.sources.some(src =>
                            src.toLowerCase().includes(brand.toLowerCase().split(' ')[0])
                        );
                        totalCitationScore += hasOfficialDomain ? 100 : 50;
                    }
                });

                // Calculate percentages
                const mentionScore = (totalMentions / totalPrompts) * 100;
                const rankingScore = totalPrompts > 0 ? totalRankScore / totalPrompts : 0;
                const citationScore = totalPrompts > 0 ? totalCitationScore / totalPrompts : 0;

                // AI Visibility Score = (Mention × 40%) + (Ranking × 40%) + (Citation × 20%)
                const aiVisibilityScore = (mentionScore * 0.4) + (rankingScore * 0.4) + (citationScore * 0.2);

                return {
                    brand,
                    score: aiVisibilityScore,
                    mentionScore,
                    rankingScore,
                    citationScore
                };
            });

            return brandScores.sort((a, b) => b.score - a.score);
        }

        function displayQuickResults(prompt, trackedBrands, results) {
            const container = document.getElementById('quick-results-content');

            // Calculate AI Visibility Scores
            const brandScores = calculateAIVisibilityScores(trackedBrands, results);

            let html = `
                <div style="background: var(--color-bg); padding: 16px; border-radius: 8px; margin-bottom: 20px;">
                    <div style="font-size: 12px; font-weight: 700; color: var(--color-text-light); text-transform: uppercase; margin-bottom: 8px;">PROMPT</div>
                    <div style="font-size: 14px; color: var(--color-text);">${prompt}</div>
                </div>

                <!-- AI Visibility Scores -->
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 12px; margin-bottom: 24px;">
                    <h3 style="color: white; font-size: 16px; font-weight: 700; margin-bottom: 16px;">📊 AI Visibility Scores</h3>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
                        ${brandScores.map(bs => {
                            const grade = bs.score >= 80 ? '🏆 Excellent' : bs.score >= 60 ? '✅ Good' : bs.score >= 40 ? '⚠️ Fair' : '❌ Poor';
                            return `
                                <div style="background: rgba(255,255,255,0.15); backdrop-filter: blur(10px); padding: 16px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.2);">
                                    <div style="color: white; font-weight: 700; font-size: 14px; margin-bottom: 8px;">${bs.brand}</div>
                                    <div style="color: white; font-size: 32px; font-weight: 800; line-height: 1; margin-bottom: 4px;">${bs.score.toFixed(1)}</div>
                                    <div style="color: rgba(255,255,255,0.8); font-size: 11px;">${grade}</div>
                                    <div style="margin-top: 12px; font-size: 11px; color: rgba(255,255,255,0.9);">
                                        <div>Mention: ${bs.mentionScore.toFixed(0)}% × 40%</div>
                                        <div>Ranking: ${bs.rankingScore.toFixed(0)} × 40%</div>
                                        <div>Citation: ${bs.citationScore.toFixed(0)} × 20%</div>
                                    </div>
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
            `;

            results.forEach(result => {
                const engine = result.engine || 'Unknown';
                const brands = result.brands || [];
                const response = result.response || '';
                const error = result.error;

                if (error) {
                    html += `
                        <div style="background: var(--color-surface); border: 1px solid var(--color-error); border-radius: 8px; padding: 20px; margin-bottom: 16px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                                <h4 style="font-size: 16px; font-weight: 700;">${engine.toUpperCase()}</h4>
                                <span style="color: var(--color-error); font-weight: 600;">Error</span>
                            </div>
                            <div style="padding: 12px; background: #fee2e2; border-radius: 6px; color: #991b1b;">
                                ${error}
                            </div>
                        </div>
                    `;
                    return;
                }

                const mentioned = brands.filter(b => b.mentioned);
                const brandList = mentioned.map(b => {
                    const rankStr = b.rank ? `#${b.rank}` : '—';
                    return `<div style="display: flex; justify-content: space-between; padding: 8px 12px; background: #d1fae5; border-radius: 6px; margin-bottom: 6px;">
                        <span style="font-weight: 600; color: #065f46;">${b.brand}</span>
                        <span style="color: #065f46;">Rank: ${rankStr}</span>
                    </div>`;
                }).join('');

                html += `
                    <div style="background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 8px; padding: 20px; margin-bottom: 16px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                            <h4 style="font-size: 16px; font-weight: 700;">${engine.toUpperCase()}</h4>
                            <div style="font-size: 24px; font-weight: 700; color: ${mentioned.length > 0 ? 'var(--color-success)' : 'var(--color-text-light)'};">
                                ${mentioned.length}/${brands.length}
                            </div>
                        </div>

                        <div style="display: grid; grid-template-columns: 350px 1fr; gap: 20px;">
                            <!-- Left: Brand mentions -->
                            <div>
                                ${mentioned.length > 0 ? `
                                    <div style="font-size: 12px; font-weight: 700; color: var(--color-text-light); margin-bottom: 8px;">MENTIONED BRANDS</div>
                                    ${brandList}
                                ` : `
                                    <div style="text-align: center; padding: 20px; background: var(--color-bg); border-radius: 6px;">
                                        <p style="color: var(--color-text-light);">No tracked brands mentioned</p>
                                    </div>
                                `}
                            </div>

                            <!-- Right: Response preview -->
                            <div>
                                ${response ? `
                                    <div style="font-size: 12px; font-weight: 700; color: var(--color-text-light); margin-bottom: 8px;">RESPONSE PREVIEW</div>
                                    <div style="font-size: 13px; color: var(--color-text); line-height: 1.6; max-height: 300px; overflow-y: auto; white-space: pre-wrap; background: var(--color-bg); padding: 12px; border-radius: 6px;">
                                        ${response.substring(0, 1000)}${response.length > 1000 ? '...' : ''}
                                    </div>
                                ` : `
                                    <div style="padding: 20px; background: var(--color-bg); border-radius: 6px; text-align: center;">
                                        <p style="color: var(--color-text-light);">No response available</p>
                                    </div>
                                `}
                            </div>
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
            document.getElementById('quick-results').style.display = 'block';
        }

        // Upload CSV handler
        document.getElementById('upload-form').addEventListener('submit', async (e) => {
            e.preventDefault();

            const fileInput = document.getElementById('csv-file');
            const file = fileInput.files[0];
            const checkedEngines = Array.from(document.querySelectorAll('input[name="engines"]:checked')).map(e => e.value);

            if (!file) {
                showUploadStatus('Please select a file', 'error');
                return;
            }

            if (checkedEngines.length === 0) {
                showUploadStatus('Please select at least one AI engine', 'error');
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            showUploadStatus('Uploading and processing...', 'info');
            document.getElementById('upload-progress').style.display = 'block';
            document.getElementById('upload-btn').disabled = true;

            try {
                // Upload CSV
                const uploadRes = await fetch('/api/upload-csv', {
                    method: 'POST',
                    body: formData
                });

                if (!uploadRes.ok) {
                    const error = await uploadRes.json();
                    throw new Error(error.detail || 'Upload failed');
                }

                const uploadData = await uploadRes.json();
                updateProgress(30, `Uploaded ${uploadData.count} prompts`);

                // Start test run
                const testRes = await fetch('/api/run-test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({engines: checkedEngines})
                });

                if (!testRes.ok) throw new Error('Test run failed');

                updateProgress(100, 'Test completed successfully!');
                showUploadStatus(`✅ Success! Processed ${uploadData.count} prompts across ${checkedEngines.length} engines`, 'success');

                // Reload data and switch to overview
                setTimeout(() => {
                    loadData();
                    switchSection('overview');
                    document.getElementById('upload-form').reset();
                    document.getElementById('upload-progress').style.display = 'none';
                    document.getElementById('upload-btn').disabled = false;
                }, 2000);

            } catch (error) {
                showUploadStatus(`❌ Error: ${error.message}`, 'error');
                document.getElementById('upload-progress').style.display = 'none';
                document.getElementById('upload-btn').disabled = false;
            }
        });

        function showUploadStatus(message, type) {
            const status = document.getElementById('upload-status');
            status.style.display = 'block';
            status.textContent = message;
            status.style.background = type === 'success' ? '#d1fae5' : type === 'error' ? '#fee2e2' : '#dbeafe';
            status.style.color = type === 'success' ? '#065f46' : type === 'error' ? '#991b1b' : '#1e40af';
        }

        function updateProgress(percent, text) {
            document.getElementById('progress-bar').style.width = percent + '%';
            document.getElementById('progress-text').textContent = text;
        }

        // Load and render history
        function loadHistory() {
            const container = document.getElementById('history-container');

            if (!allData || allData.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 64px 32px;">
                        <div style="font-size: 48px; margin-bottom: 16px;">📊</div>
                        <h3 style="font-size: 18px; font-weight: 700; margin-bottom: 8px; color: var(--color-text);">No test results yet</h3>
                        <p style="color: var(--color-text-light);">Upload a CSV file and run a test to see results here</p>
                    </div>
                `;
                return;
            }

            // Group by engine and show detailed results
            const byEngine = {};
            allData.forEach(row => {
                const eng = row['AI Engine'] || 'Unknown';
                if (!byEngine[eng]) byEngine[eng] = [];
                byEngine[eng].push(row);
            });

            let html = '';
            Object.entries(byEngine).forEach(([engine, rows]) => {
                const mentionCol = Object.keys(rows[0] || {}).find(k => k.includes('Mention'));
                const mentioned = rows.filter(r => r[mentionCol] === 'Yes').length;
                const total = rows.length;
                const rate = ((mentioned / total) * 100).toFixed(1);

                html += `
                    <div style="background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 12px; padding: 24px; margin-bottom: 20px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                            <div>
                                <h3 style="font-size: 18px; font-weight: 700; margin-bottom: 4px;">${engine}</h3>
                                <p style="font-size: 13px; color: var(--color-text-light);">${total} queries tested</p>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 32px; font-weight: 700; color: var(--color-primary); line-height: 1;">${rate}%</div>
                                <div style="font-size: 12px; color: var(--color-text-light); margin-top: 4px;">mention rate</div>
                            </div>
                        </div>
                        <div style="height: 8px; background: var(--color-bg); border-radius: 4px; overflow: hidden; margin-bottom: 20px;">
                            <div style="height: 100%; background: var(--color-primary); width: ${rate}%;"></div>
                        </div>

                        <!-- Recent queries from this engine -->
                        <div style="margin-top: 20px;">
                            <h4 style="font-size: 14px; font-weight: 700; margin-bottom: 12px; color: var(--color-text-light);">RECENT QUERIES</h4>
                            ${rows.slice(0, 10).map(r => {
                                const isMentioned = r[mentionCol] === 'Yes';
                                const query = (r.Query || '').substring(0, 150);
                                const rank = r.Rank != null && !isNaN(r.Rank) ? '#' + Math.round(r.Rank) : '—';

                                return `
                                    <div style="padding: 12px; background: var(--color-bg); border-radius: 8px; margin-bottom: 8px;">
                                        <div style="display: flex; justify-content: space-between; align-items: start; gap: 16px;">
                                            <div style="flex: 1;">
                                                <div style="font-size: 14px; color: var(--color-text); margin-bottom: 6px;">${query}${query.length >= 150 ? '...' : ''}</div>
                                                <div style="display: flex; gap: 8px; align-items: center;">
                                                    <span style="display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; ${isMentioned ? 'background: #d1fae5; color: #065f46;' : 'background: #fee2e2; color: #991b1b;'}">
                                                        ${isMentioned ? '✓ Mentioned' : '✗ Not Mentioned'}
                                                    </span>
                                                    ${isMentioned ? `<span style="font-size: 12px; color: var(--color-text-light);">Rank: ${rank}</span>` : ''}
                                                </div>
                                            </div>
                                            <div style="font-size: 20px; font-weight: 700; color: var(--color-text-light); min-width: 40px; text-align: right;">
                                                ${r['Ranking Score'] || 0}
                                            </div>
                                        </div>
                                    </div>
                                `;
                            }).join('')}
                            ${rows.length > 10 ? `<div style="text-align: center; margin-top: 12px; font-size: 13px; color: var(--color-text-light);">+ ${rows.length - 10} more queries</div>` : ''}
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        loadData();
        loadHistory();
    </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8501)
