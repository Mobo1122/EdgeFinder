"""FastAPI web dashboard for monitoring the EdgeFinder agent."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..db.database import (
    db_session,
    get_open_trades,
    get_portfolio_summary,
    get_recent_analyses,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_dashboard(config: dict, pipeline_state: dict | None = None) -> FastAPI:
    app = FastAPI(title="EdgeFinder Dashboard")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    state = pipeline_state or {"last_run": None, "run_count": 0, "last_summary": {}}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse("index.html", {
            "request": request,
            "mode": config.get("mode", "paper"),
        })

    @app.get("/api/portfolio", response_class=HTMLResponse)
    async def portfolio():
        with db_session() as conn:
            summary = get_portfolio_summary(conn)

        pnl_class = "positive" if summary["total_pnl"] >= 0 else "negative"
        return f"""
        <h2>Portfolio Overview</h2>
        <div class="portfolio-grid">
            <div class="stat">
                <div class="value {pnl_class}">&pound;{summary['total_pnl']:+.2f}</div>
                <div class="label">Total P&amp;L</div>
            </div>
            <div class="stat">
                <div class="value">{summary['open_positions']}</div>
                <div class="label">Open Positions</div>
            </div>
            <div class="stat">
                <div class="value">&pound;{summary['total_exposure']:.2f}</div>
                <div class="label">Exposure</div>
            </div>
            <div class="stat">
                <div class="value">{summary['closed_trades']}</div>
                <div class="label">Closed Trades</div>
            </div>
            <div class="stat">
                <div class="value">{summary['win_rate']:.0f}%</div>
                <div class="label">Win Rate</div>
            </div>
        </div>
        """

    @app.get("/api/trades", response_class=HTMLResponse)
    async def trades():
        with db_session() as conn:
            open_trades = conn.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT 20"
            ).fetchall()

        if not open_trades:
            return "<p style='color:#444;text-align:center;padding:1rem;'>No trades yet</p>"

        rows = ""
        for t in open_trades:
            t = dict(t)
            side_class = "side-back" if t["side"] == "back" else "side-lay"
            pnl_str = ""
            if t["status"] == "closed" and t["pnl"] is not None:
                pnl_class = "pnl-positive" if t["pnl"] >= 0 else "pnl-negative"
                pnl_str = f'<span class="{pnl_class}">&pound;{t["pnl"]:+.2f}</span>'
            else:
                pnl_str = '<span style="color:#444">-</span>'

            rows += f"""
            <tr>
                <td><span class="tag {t['platform']}">{t['platform']}</span></td>
                <td class="{side_class}">{t['side'].upper()}</td>
                <td>{t['outcome']}</td>
                <td>{t['price']:.1%}</td>
                <td>&pound;{t['stake']:.2f}</td>
                <td>{t['status']}</td>
                <td>{pnl_str}</td>
                <td style="color:#555">{t['created_at'][:16]}</td>
            </tr>
            """

        return f"""
        <table>
            <thead>
                <tr>
                    <th>Platform</th><th>Side</th><th>Outcome</th>
                    <th>Price</th><th>Stake</th><th>Status</th>
                    <th>P&amp;L</th><th>Time</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        """

    @app.get("/api/analyses", response_class=HTMLResponse)
    async def analyses():
        with db_session() as conn:
            recent = get_recent_analyses(conn, limit=10)

        if not recent:
            return "<p style='color:#444;text-align:center;padding:1rem;'>No analyses yet</p>"

        items = ""
        for a in recent:
            edge_class = "edge-high" if abs(a["edge"]) >= 0.10 else "edge-medium"
            items += f"""
            <div class="analysis-item">
                <div class="question">{a['question']}</div>
                <div class="meta">
                    <span><span class="tag {a['platform']}">{a['platform']}</span></span>
                    <span>Market: {a['current_price']:.1%}</span>
                    <span>AI Est: {a['estimated_probability']:.1%}</span>
                    <span class="{edge_class}">Edge: {a['edge']:+.1%}</span>
                    <span>Confidence: {a['confidence']:.0%}</span>
                </div>
                <div class="reasoning">{a['reasoning'] or ''}</div>
            </div>
            """

        return items

    @app.get("/api/status", response_class=HTMLResponse)
    async def status():
        last = state.get("last_summary", {})
        return f"""
        <div class="status-grid">
            <div>
                <div class="status-item">
                    <span class="key">Mode</span>
                    <span class="val">{config.get('mode', 'paper').upper()}</span>
                </div>
                <div class="status-item">
                    <span class="key">Total Runs</span>
                    <span class="val">{state.get('run_count', 0)}</span>
                </div>
                <div class="status-item">
                    <span class="key">Last Run</span>
                    <span class="val">{(state.get('last_run') or 'Never')}</span>
                </div>
                <div class="status-item">
                    <span class="key">Schedule</span>
                    <span class="val">Every {config.get('schedule', {}).get('interval_hours', 2)}h</span>
                </div>
            </div>
            <div>
                <div class="status-item">
                    <span class="key">Markets Last Run</span>
                    <span class="val">{last.get('markets_fetched', 0)}</span>
                </div>
                <div class="status-item">
                    <span class="key">Edges Found</span>
                    <span class="val">{last.get('edges_found', 0)}</span>
                </div>
                <div class="status-item">
                    <span class="key">Trades Executed</span>
                    <span class="val">{last.get('trades_executed', 0)}</span>
                </div>
                <div class="status-item">
                    <span class="key">Errors</span>
                    <span class="val">{len(last.get('errors', []))}</span>
                </div>
            </div>
        </div>
        """

    return app
