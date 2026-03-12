import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "brand_monitor.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'batch',
            created_at TEXT NOT NULL,
            query TEXT NOT NULL,
            ai_engine TEXT NOT NULL,
            brand TEXT NOT NULL,
            mention TEXT NOT NULL DEFAULT 'No',
            rank REAL,
            ranking_score REAL DEFAULT 0,
            citation_type TEXT DEFAULT 'none',
            citation_score REAL DEFAULT 0,
            source_urls TEXT DEFAULT '',
            competitors_mentioned TEXT DEFAULT '',
            error TEXT,
            raw_response TEXT,
            raw_citations TEXT
        )
    """)
    # Add competitors_mentioned column if missing (migration for existing DB)
    try:
        conn.execute("ALTER TABLE results ADD COLUMN competitors_mentioned TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_run_id ON results(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_created_at ON results(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_ai_engine ON results(ai_engine)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_brand ON results(brand)")
    conn.commit()
    conn.close()


def insert_results(rows, run_id, source="batch"):
    conn = get_connection()
    now = datetime.now().isoformat()
    for row in rows:
        conn.execute("""
            INSERT INTO results (run_id, source, created_at, query, ai_engine, brand,
                mention, rank, ranking_score, citation_type, citation_score,
                source_urls, competitors_mentioned, error, raw_response, raw_citations)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, source, now,
            row.get("Query", ""),
            row.get("AI Engine", ""),
            row.get("Brand", ""),
            row.get("Mention", "No"),
            row.get("Rank"),
            row.get("Ranking Score", 0),
            row.get("Citation Type", "none"),
            row.get("Citation Score", 0),
            row.get("Source", ""),
            row.get("Competitors Mentioned", ""),
            row.get("Error"),
            row.get("raw_response"),
            row.get("raw_citations"),
        ))
    conn.commit()
    conn.close()


def get_all_results():
    conn = get_connection()
    cursor = conn.execute("""
        SELECT query as "Query", ai_engine as "AI Engine",
               mention as "Mention", rank as "Rank",
               ranking_score as "Ranking Score",
               citation_type as "Citation Type",
               citation_score as "Citation Score",
               source_urls as "Source",
               error as "Error",
               run_id, source, created_at
        FROM results
        ORDER BY created_at DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_history():
    """Get all results with full detail (all brands) for history view."""
    conn = get_connection()
    cursor = conn.execute("""
        SELECT query, ai_engine, brand, mention, rank, ranking_score,
               citation_type, citation_score, source_urls,
               competitors_mentioned, error,
               run_id, source, created_at
        FROM results
        ORDER BY created_at DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Group by (run_id, query) to create history entries
    history = {}
    for r in rows:
        key = (r["run_id"], r["query"])
        if key not in history:
            history[key] = {
                "query": r["query"],
                "run_id": r["run_id"],
                "source": r["source"],
                "created_at": r["created_at"],
                "engines": {},
            }
        eng = r["ai_engine"]
        if eng not in history[key]["engines"]:
            history[key]["engines"][eng] = []
        history[key]["engines"][eng].append({
            "brand": r["brand"],
            "mention": r["mention"],
            "rank": r["rank"],
            "ranking_score": r["ranking_score"],
            "citation_type": r["citation_type"],
            "citation_score": r["citation_score"],
            "competitors_mentioned": r["competitors_mentioned"],
            "error": r["error"],
        })

    return list(history.values())
