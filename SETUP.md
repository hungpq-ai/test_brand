# Setup Guide - AI Brand Monitoring Tool

## 📋 Prerequisites

- Python 3.11+
- API Keys:
  - **Deepbricks** (for ChatGPT & Claude)
  - **Google Gemini** (direct)

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install packages
pip install -r requirements.txt
pip install fastapi uvicorn  # For web dashboard
```

### 2. Configure API Keys

Edit `.env` file and choose your API provider:

#### **Option A: Yescale (mỗi model cần key riêng)**

```bash
# ChatGPT key
CHATGPT_BASE_URL=https://api.yescale.one/v1
CHATGPT_API_KEY=sk-yescale-gpt-xxxxx

# Claude key (khác với GPT key)
CLAUDE_BASE_URL=https://api.yescale.one/v1
CLAUDE_API_KEY=sk-yescale-claude-xxxxx

# Google Gemini
GOOGLE_API_KEY=AIza-xxxxx
```

**Lưu ý:** Yescale yêu cầu API key riêng cho từng model!

---

#### **Option B: Deepbricks (1 key dùng cho tất cả)**

```bash
# Chung 1 key cho cả GPT và Claude
CHATGPT_BASE_URL=https://api.deepbricks.ai/v1
CHATGPT_API_KEY=sk-deepbricks-xxxxx

CLAUDE_BASE_URL=https://api.deepbricks.ai/v1
CLAUDE_API_KEY=sk-deepbricks-xxxxx  # Dùng chung key

# Hoặc dùng shared config (cũ):
# OPENAI_BASE_URL=https://api.deepbricks.ai/v1
# OPENAI_API_KEY=sk-deepbricks-xxxxx

# Google Gemini
GOOGLE_API_KEY=AIza-xxxxx
```

**Lợi ích:** Deepbricks cho phép dùng 1 key cho nhiều models → tiện hơn!

---

**Where to get API keys:**
- Yescale: https://yescale.ai
- Deepbricks: https://deepbricks.ai
- Google Gemini: https://aistudio.google.com/apikey

### 3. Configure Brands & Engines

Edit `config.yaml`:

```yaml
brands:
  - "Mondelez"
  - "Nestlé"      # Add competitors
  - "Mars"
  - "Ferrero"

engines:
  chatgpt:
    enabled: true
    model: "gpt-4o"
    rpm: 60

  gemini:
    enabled: true
    model: "gemini-2.0-flash-exp"
    rpm: 15

  claude:
    enabled: true
    model: "claude-sonnet-4-20250514"
    rpm: 50

  perplexity:
    enabled: false  # Not available yet
```

---

## 💻 Usage

### Option A: CLI Mode

Run batch test on all prompts:

```bash
python main.py
```

Custom options:

```bash
# Test specific engines only
python main.py --engines chatgpt,gemini

# Test specific brands
python main.py --brands "Mondelez,Nestlé"

# Dry run (preview without calling APIs)
python main.py --dry-run
```

### Option B: Web Dashboard

```bash
python app.py
```

Then open: **http://localhost:8501**

Features:
- 📊 Overview dashboard
- ⚡ Live Query (test single prompt)
- 🔄 Batch Run (run all prompts)
- 📄 View raw responses

---

## 📂 Output Files

Results saved to `output/` directory:

```
output/
├── results_20260311_153045.csv          # Combined results
├── Mondelez_20260311_153045.csv         # Per-brand CSV
├── Nestle_20260311_153045.csv
├── raw_responses_20260311_153045.csv    # Full AI responses
└── raw_responses_20260311_153045.json
```

---

## 📊 Understanding Scores

### Brand Visibility Score (BVS)

```
BVS = (Mention Score × 40%) + (Ranking Score × 40%) + (Citation Score × 20%)
```

**Components:**

1. **Mention Score** = (Prompts with brand / Total prompts) × 100
   - Brand mentioned: 1
   - Brand not mentioned: 0

2. **Ranking Score** = Average position score
   - Rank 1: 100
   - Rank 2: 80
   - Rank 3: 60
   - Rank 4: 40
   - Rank 5: 20
   - Rank 6+: 0

3. **Citation Score** = Average citation quality
   - Official site cited: 100
   - Other site cited: 50
   - No citation: 0

**Example:**
```
Mondelez Vietnam:
├─ Mention Score: 82% (mentioned in 82/100 prompts)
├─ Ranking Score: 75 (average Top 2-3)
└─ Citation Score: 80 (mostly quality sources)

BVS = (82 × 0.4) + (75 × 0.4) + (80 × 0.2)
    = 32.8 + 30 + 16
    = 78.8 (Grade: A - Strong Visibility)
```

---

## 🌏 Multi-Language Support

Current prompts: Vietnamese (130 prompts)

**Coming soon:**
- English
- Bahasa Indonesia
- Malay
- Thai

---

## ⚙️ Advanced Configuration

### Rate Limiting

Adjust `rpm` (requests per minute) in `config.yaml`:

```yaml
engines:
  chatgpt:
    rpm: 60  # Lower if hitting rate limits
```

### Multiple API Keys

For higher throughput, use comma-separated keys:

```bash
GOOGLE_API_KEY=key1,key2,key3
```

Tool will rotate keys automatically.

---

## 🐛 Troubleshooting

**Error: "OPENAI_API_KEY is not set"**
- Check `.env` file exists
- Verify `OPENAI_API_KEY=your-key` (no spaces)

**Error: "google-genai package is required"**
```bash
pip install google-genai
```

**Rate limit errors:**
- Lower `rpm` in `config.yaml`
- Add more API keys (comma-separated)

**No results in dashboard:**
- Run CLI mode first: `python main.py`
- Check `output/` directory for CSV files

---

## 📝 Next Steps

1. **Run test with 5 prompts** to verify setup
2. **Check costs** (estimate ~$0.05 per prompt × engines)
3. **Add competitors** to `brands:` in config.yaml
4. **Analyze results** in dashboard
5. **Generate reports** for presentation

---

## 💰 Cost Estimation

Per query (1 prompt × 3 engines):
- ChatGPT (gpt-4o): ~$0.01
- Gemini (flash): ~$0.001
- Claude (sonnet): ~$0.015

**Example:**
- 100 prompts × 3 engines = 300 API calls
- Total cost: ~$8 per run
- Monthly (weekly runs): ~$32/month

---

## 🔗 Links

- Deepbricks: https://deepbricks.ai
- Google AI Studio: https://aistudio.google.com
- Repo issues: https://github.com/hungpq-ai/test_brand/issues
