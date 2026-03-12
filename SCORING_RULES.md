# AI Visibility Scoring Rules

## 📊 Scoring Formula

```
AI Visibility Score = (Mention Score × 40%) + (Ranking Score × 40%) + (Citation Score × 20%)
```

---

## 1️⃣ Mention Score (40%)

**Calculation:**
```
Mention Score = (Number of Mentions / Total Prompts) × 100
```

**Example:**
- Total prompts: 107
- Brand mentioned: 85 times
- Mention Score = (85/107) × 100 = **79.44%**

---

## 2️⃣ Ranking Score (40%)

**Position-based scoring:**

| Rank Position | Score |
|--------------|-------|
| Rank 1       | 100   |
| Rank 2       | 80    |
| Rank 3       | 60    |
| Rank 4       | 40    |
| Rank 5       | 20    |
| Rank 6+      | 0     |

**Calculation:**
```
Ranking Score = Average of all ranking scores across prompts
```

**Example:**
- Prompt 1: Rank 1 → 100 points
- Prompt 2: Rank 2 → 80 points
- Prompt 3: Not mentioned → 0 points
- Prompt 4: Rank 1 → 100 points
- Average Ranking Score = (100 + 80 + 0 + 100) / 4 = **70 points**

---

## 3️⃣ Citation Score (20%)

**Citation type scoring:**

| Citation Type | Score | Description |
|--------------|-------|-------------|
| Official     | 100   | Official brand website cited |
| Other        | 50    | Third-party website cited |
| None         | 0     | No citation provided |

**Official Domains:**
- **Mondelez**: mondelezinternational.com, mondelez.com
- **Nestlé**: nestle.com, nestle.vn, nestle.com.vn
- **Mars**: mars.com, mars.com.vn, marsinc.com
- **PepsiCo**: pepsico.com, pepsico.com.vn
- **Orion**: orionworld.com, oriongroup.com.vn

**Calculation:**
```
Citation Score = Average of all citation scores across prompts
```

**Example:**
- Prompt 1: Official source → 100 points
- Prompt 2: Other source → 50 points
- Prompt 3: No citation → 0 points
- Prompt 4: Official source → 100 points
- Average Citation Score = (100 + 50 + 0 + 100) / 4 = **62.5 points**

---

## 📈 Final Score Example

**Given:**
- Mention Score: 79.44%
- Ranking Score: 70 points
- Citation Score: 62.5 points

**Calculation:**
```
AI Visibility Score = (79.44 × 0.40) + (70 × 0.40) + (62.5 × 0.20)
                    = 31.78 + 28.00 + 12.50
                    = 72.28
```

**Grade Scale:**
- 🏆 **Excellent**: 80-100
- ✅ **Good**: 60-79
- ⚠️ **Fair**: 40-59
- ❌ **Poor**: 0-39

---

## 🎯 Brands Tracked

1. **Mondelez** (Primary brand)
2. **Nestlé** (Competitor)
3. **Mars** (Competitor)
4. **PepsiCo** (Competitor)
5. **Orion** (Competitor)

---

## 📝 Prompt Categories

### 1. Commercial Keywords (30 prompts)
- Purchase intent queries
- "Best [product] brands" type questions
- Direct buying questions

### 2. Comparison Keywords (22 prompts)
- Brand vs brand comparisons
- Product comparisons
- Alternative recommendations

### 3. Brand Keywords (20 prompts)
- Brand-specific queries
- Product line questions
- Brand history/information

### 4. Informational Keywords (35 prompts)
- Educational content
- Industry information
- How-to and explainer queries

**Total: 107 prompts**

---

## 🚀 Usage

### Run test with all prompts:
```bash
# Via Docker
docker-compose up -d

# Access dashboard
http://localhost:8501

# Go to "Run Test" tab
# Select engines: ChatGPT, Gemini, Claude
# Click "Start Test Run"
```

### Upload custom prompts:
```bash
# Access upload page
http://localhost:8501/upload

# Upload CSV with format:
# prompt
# "Your question here"
# "Another question"
```

---

## 📤 Output Files

After running tests, check `output/` directory:

- `Mondelez_[timestamp].csv` - Per-prompt results with all brands
- `ai_visibility_scores_[timestamp].csv` - Aggregate scores per brand
- `raw_responses_[timestamp].json` - Full AI responses for analysis

---

## 🎯 Interpretation Guide

### Mention Score Analysis
- **80-100%**: Strong brand visibility
- **60-79%**: Good presence but room to grow
- **40-59%**: Moderate visibility, needs improvement
- **0-39%**: Low visibility, requires GEO optimization

### Ranking Score Analysis
- **80-100**: Consistently top-ranked
- **60-79**: Often in top 3
- **40-59**: Middle-of-pack placement
- **0-39**: Rarely mentioned or low rankings

### Citation Score Analysis
- **80-100**: Strong official source citations
- **60-79**: Mix of official and third-party
- **40-59**: Mostly third-party citations
- **0-39**: Few or no citations

---

## 🔍 Next Steps for Optimization

1. **For Low Mention Scores:**
   - Create more content around keywords
   - Improve brand association with key topics
   - Increase content distribution

2. **For Low Ranking Scores:**
   - Strengthen brand authority signals
   - Improve content quality and relevance
   - Build more brand associations in AI training data

3. **For Low Citation Scores:**
   - Ensure official website is well-structured
   - Improve content discoverability
   - Build authoritative backlinks
   - Enhance structured data markup
