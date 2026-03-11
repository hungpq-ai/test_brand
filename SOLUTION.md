# Đề xuất giải pháp: Test Prompt hàng loạt trên nhiều AI Engines

---

## 1. Mục tiêu

Xây dựng hệ thống tự động đo lường mức độ hiện diện (brand visibility) của thương hiệu trên các nền tảng AI, phục vụ cho GEO Audit (Generative Engine Optimization).

---

## 2. Quy trình xử lý

```
Prompt Database (30–100+ prompts)
        │
        ▼
┌───────────────────────────────┐
│   Gửi tự động đến AI Engines │
│                               │
│   • ChatGPT                   │
│   • Google Gemini             │
│   • Claude                    │
│   • Perplexity                │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│   Lưu AI Response đầy đủ     │
│   (raw text + citations)      │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│   Trích xuất dữ liệu         │
│                               │
│   • Brand Mention (Yes/No)    │
│   • Brand Ranking (vị trí)    │
│   • Source / Citation domain  │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│   Xuất dataset dạng bảng     │
│                               │
│   prompt | engine | brand     │
│   rank   | source             │
└───────────────────────────────┘
```

---

## 3. Chi tiết từng bước

### 3.1. Nhận Prompt Database

- Input: file CSV chứa 30–100+ prompts
- Prompts được thiết kế đa dạng góc nhìn ngành hàng:
  - Theo quốc gia (Việt Nam, châu Á, toàn cầu...)
  - Theo loại sản phẩm (chocolate, bánh quy, snack, kẹo...)
  - Theo kênh phân phối (siêu thị, online, cửa hàng tiện lợi...)
  - Theo đặc tính (organic, premium, healthy...)
- Hỗ trợ đa ngôn ngữ: Tiếng Việt + Tiếng Anh

### 3.2. Gửi tự động đến các AI Engines

| Engine | Đặc điểm |
|--------|----------|
| **ChatGPT** | AI phổ biến nhất hiện tại, nhiều user dùng để tìm kiếm sản phẩm |
| **Google Gemini** | Tích hợp với Google ecosystem, ảnh hưởng đến AI Overview |
| **Claude** | Đang tăng trưởng nhanh, nổi bật với câu trả lời chi tiết |
| **Perplexity** | Search-first AI, có citation/source rõ ràng |

Xử lý kỹ thuật:
- Gửi **song song** đến tất cả engines để tối ưu thời gian
- **Rate limiting** tự động theo giới hạn từng provider
- **Retry** tự động khi gặp lỗi mạng hoặc rate limit
- Hỗ trợ **xoay vòng nhiều API key** để tăng throughput

### 3.3. Lưu AI Response đầy đủ

Mỗi response được lưu nguyên vẹn gồm:
- Full text response từ AI
- Citations / URL trích dẫn (nếu có, đặc biệt từ Perplexity)
- Metadata: model, timestamp, prompt gốc

### 3.4. Trích xuất dữ liệu

Từ mỗi response, hệ thống tự động trích xuất:

| Dữ liệu | Mô tả |
|----------|-------|
| **Brand Mention** | Thương hiệu có được nhắc đến không? (Yes/No) — Hỗ trợ nhận diện Unicode (vd: Mondelēz = Mondelez) |
| **Brand Ranking** | Vị trí xuất hiện của brand trong danh sách AI trả về (numbered list, bullet list, table, heading) |
| **Source / Citation** | Domain nguồn trích dẫn được AI sử dụng |

### 3.5. Xuất dataset

Output dạng bảng CSV:

| prompt | engine | brand | mention | rank | rank_score | source |
|--------|--------|-------|---------|------|------------|--------|
| Top công ty bánh kẹo... | chatgpt | Mondelez | Yes | 3 | 0.6 | mondelezinternational.com |
| Top công ty bánh kẹo... | gemini | Mondelez | Yes | 1 | 1.0 | — |
| Top công ty bánh kẹo... | claude | Mondelez | Yes | 2 | 0.8 | — |
| Top công ty bánh kẹo... | perplexity | Mondelez | Yes | 4 | 0.4 | wikipedia.org |

**Rank Score** quy đổi:
- Top 1 = 1.0 | Top 2 = 0.8 | Top 3 = 0.6 | Top 4 = 0.4 | Top 5 = 0.2 | 6+ = 0.1

---

## 4. Deliverables

1. **Dataset CSV** — Bảng tổng hợp toàn bộ kết quả (prompt × engine × brand)
2. **Raw Responses** — File lưu trữ toàn bộ response gốc từ AI (CSV + JSON)
3. **Per-brand CSV** — File riêng cho từng brand theo dõi
4. **Web Dashboard** — Giao diện trực quan để:
   - Xem tổng quan kết quả & so sánh engines
   - Nhập prompt realtime, so sánh response side-by-side (Live Query)
   - Xem chi tiết từng response gốc
   - Chạy batch test trực tiếp từ web
