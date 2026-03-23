"""Database schema definitions."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    question TEXT NOT NULL,
    category TEXT,
    current_price REAL,
    volume REAL,
    liquidity REAL,
    end_date TEXT,
    url TEXT,
    resolved INTEGER DEFAULT 0,
    resolution_outcome TEXT,
    extra_data TEXT,  -- JSON blob for platform-specific fields
    last_updated TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL REFERENCES markets(id),
    estimated_probability REAL NOT NULL,
    confidence REAL NOT NULL,
    edge REAL NOT NULL,
    reasoning TEXT,
    news_context TEXT,
    model TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL REFERENCES markets(id),
    platform TEXT NOT NULL,
    side TEXT NOT NULL,        -- 'back' or 'lay' (Betfair terms)
    outcome TEXT NOT NULL,     -- e.g. 'Yes', 'No', team name
    price REAL NOT NULL,       -- decimal odds or probability
    stake REAL NOT NULL,       -- amount in £
    mode TEXT DEFAULT 'paper', -- 'paper' or 'live'
    status TEXT DEFAULT 'open',
    pnl REAL,
    external_id TEXT,          -- platform order ID for live trades
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_value REAL NOT NULL,
    total_pnl REAL NOT NULL,
    open_positions INTEGER NOT NULL,
    win_rate REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analyses_market ON analyses(market_id);
CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_markets_platform ON markets(platform);
"""
