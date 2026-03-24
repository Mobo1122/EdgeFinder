# EdgeFinder Agent

AI-powered prediction market edge detection system. Monitors Betfair Exchange, Smarkets, and Manifold Markets for mispriced outcomes, uses Claude AI to estimate true probabilities, and trades automatically.

**Default mode is paper trading** — no real money at risk until you explicitly switch to live.

## How It Works

1. **Fetches** active markets from Betfair, Smarkets, and Manifold
2. **Analyzes** each market with Claude AI to estimate the "true" probability
3. **Detects edges** where the AI estimate diverges significantly from market price
4. **Sizes positions** using fractional Kelly criterion with safety limits
5. **Executes trades** (paper or live) and tracks everything
6. **Repeats** on a configurable schedule (default: every 2 hours)

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up your API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 3. Run in paper trading mode
python main.py

# Dashboard available at http://localhost:8080
```

## Usage

```bash
python main.py              # Start scheduler + dashboard (paper mode)
python main.py --once       # Run pipeline once then exit
python main.py --live       # Enable live trading (real money!)
python main.py --dashboard  # Dashboard only, no trading
```

## Configuration

Edit `config.yaml` to tune:

- **Platforms**: Enable/disable Betfair, Smarkets, Manifold
- **Risk**: Edge threshold, Kelly fraction, position limits
- **Schedule**: How often the pipeline runs
- **Analysis**: Claude model, confidence threshold

## Platform Setup

### Manifold Markets (easiest — no auth needed)
Works out of the box for reading. For live trading, get an API key from your Manifold profile.

### Betfair Exchange (most liquid)
1. Create a [Betfair developer account](https://developer.betfair.com/)
2. Get an Application Key
3. Generate SSL certificates for cert-based login
4. Add credentials to `.env`

### Smarkets (lowest fees — 2%)
1. Create a Smarkets account
2. Get an API token from developer settings
3. Add to `.env`

## Architecture

```
edgefinder/
  platforms/     — Market data connectors (Betfair, Smarkets, Manifold)
  analysis/      — Claude AI probability estimation engine
  strategy/      — Edge detection + Kelly criterion risk management
  execution/     — Paper trading (default) + live execution
  scheduler/     — Autonomous pipeline runner
  dashboard/     — FastAPI web UI for monitoring
  db/            — SQLite persistence layer
```

## Deploy on a Server

### Option 1: Docker (recommended)

```bash
# 1. Clone and configure
git clone <your-repo-url> && cd edgefinder
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# 2. Start
docker compose up -d

# Dashboard at http://your-server:8080
# View logs
docker compose logs -f
```

### Option 2: systemd (no Docker)

```bash
# 1. Set up on server
sudo useradd -r -s /bin/false edgefinder
sudo cp -r . /opt/edgefinder
cd /opt/edgefinder
python3 -m venv venv
venv/bin/pip install -r requirements.txt
sudo cp .env.example .env
# Edit /opt/edgefinder/.env with your ANTHROPIC_API_KEY

# 2. Install and start the service
sudo cp edgefinder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now edgefinder

# View logs
journalctl -u edgefinder -f
```

## Risk Disclaimer

This is a research and educational tool. Prediction market trading involves risk of loss. Past performance does not guarantee future results. Always start with paper trading to validate the strategy. The authors are not responsible for any financial losses.
