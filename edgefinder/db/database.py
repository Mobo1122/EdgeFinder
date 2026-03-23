"""SQLite database connection and query helpers."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import SCHEMA

DB_PATH = Path(__file__).parent.parent.parent / "edgefinder.db"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.close()


@contextmanager
def db_session(db_path: Path | None = None):
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Market helpers ---

def upsert_market(conn: sqlite3.Connection, market: dict) -> None:
    conn.execute(
        """INSERT INTO markets (id, platform, question, category, current_price,
           volume, liquidity, end_date, url, extra_data, last_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             current_price=excluded.current_price,
             volume=excluded.volume,
             liquidity=excluded.liquidity,
             extra_data=excluded.extra_data,
             last_updated=excluded.last_updated""",
        (
            market["id"], market["platform"], market["question"],
            market.get("category"), market.get("current_price"),
            market.get("volume"), market.get("liquidity"),
            market.get("end_date"), market.get("url"),
            json.dumps(market.get("extra_data", {})), _now(),
        ),
    )


def get_open_trades(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM trades WHERE status = 'open' ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def insert_trade(conn: sqlite3.Connection, trade: dict) -> int:
    cursor = conn.execute(
        """INSERT INTO trades (market_id, platform, side, outcome, price, stake,
           mode, status, external_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
        (
            trade["market_id"], trade["platform"], trade["side"],
            trade["outcome"], trade["price"], trade["stake"],
            trade.get("mode", "paper"), trade.get("external_id"), _now(),
        ),
    )
    return cursor.lastrowid


def close_trade(conn: sqlite3.Connection, trade_id: int, pnl: float) -> None:
    conn.execute(
        "UPDATE trades SET status='closed', pnl=?, closed_at=? WHERE id=?",
        (pnl, _now(), trade_id),
    )


def insert_analysis(conn: sqlite3.Connection, analysis: dict) -> int:
    cursor = conn.execute(
        """INSERT INTO analyses (market_id, estimated_probability, confidence,
           edge, reasoning, news_context, model, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            analysis["market_id"], analysis["estimated_probability"],
            analysis["confidence"], analysis["edge"],
            analysis.get("reasoning"), analysis.get("news_context"),
            analysis.get("model"), _now(),
        ),
    )
    return cursor.lastrowid


def get_recent_analyses(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT a.*, m.question, m.platform, m.current_price
           FROM analyses a JOIN markets m ON a.market_id = m.id
           ORDER BY a.created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_portfolio_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    open_trades = conn.execute(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(stake), 0) as exposure FROM trades WHERE status='open'"
    ).fetchone()
    closed = conn.execute(
        """SELECT COUNT(*) as cnt, COALESCE(SUM(pnl), 0) as total_pnl,
           COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) as wins
           FROM trades WHERE status='closed'"""
    ).fetchone()
    total_closed = closed["cnt"] if closed["cnt"] else 0
    return {
        "open_positions": open_trades["cnt"],
        "total_exposure": open_trades["exposure"],
        "closed_trades": total_closed,
        "total_pnl": closed["total_pnl"],
        "win_rate": (closed["wins"] / total_closed * 100) if total_closed > 0 else 0,
    }


def snapshot_portfolio(conn: sqlite3.Connection) -> None:
    summary = get_portfolio_summary(conn)
    conn.execute(
        """INSERT INTO portfolio_snapshots (total_value, total_pnl, open_positions, win_rate)
           VALUES (?, ?, ?, ?)""",
        (summary["total_exposure"], summary["total_pnl"],
         summary["open_positions"], summary["win_rate"]),
    )
