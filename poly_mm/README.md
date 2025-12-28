# Polymarket 15-Minute Market Maker

Complete market-making system for Polymarket's 15-minute binary markets using Black-Scholes pricing and real-time Chainlink oracle prices.

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure .env
cp src/.env.example src/.env
# Edit src/.env with your POLYMARKET_PRIVATE_KEY

# 3. Run (dry run mode by default)
cd src
python main.py
```

## 📊 What It Does

1. **Connects to Polymarket RTDS** → Real-time Chainlink prices
2. **Calculates volatility** → EWMA on price ticks
3. **Prices markets** → Black-Scholes UP/DOWN probabilities  
4. **Finds edge** → Compares fair price vs market price
5. **Sizes positions** → Kelly-inspired edge-based sizing
6. **Logs everything** → 8 log files with complete data for replay/analysis

## 🎯 Key Concepts

### Strike Price Timing
15-minute markets compare BTC price at **start** vs **expiry**:
- Strike = Chainlink price at market **start time** (:00, :15, :30, :45)
- Settlement = Chainlink price at **expiry** (15 min later)
- UP wins if expiry_price > strike_price

**Implementation**: Price buffer keeps last 60s of ticks, retrieves exact price at start_time (±5s tolerance). Skips markets without accurate strike.

### Performance Logging  
Every session creates 8 JSONL log files:
- `price_ticks.jsonl` - Every Chainlink tick (~2/sec)
- `markets.jsonl` - Market state changes
- `orderbooks.jsonl` - YES/NO bids/asks
- `calculations.jsonl` - Volatility, probabilities, sizing (inputs + outputs)
- `decisions.jsonl` - Trade/pass decisions with full reasoning
- `trades.jsonl` - Order executions
- `performance.jsonl` - Metrics every 60s
- `events.jsonl` - System events, errors, config

```bash
# Analyze session
python logs/analyze_logs.py logs/20241228_103203
```

## 📁 Project Structure

```
poly_mm/
├── README.md (this file)
├── src/
│   ├── main.py - Main market maker
│   ├── config.py - Config loader
│   ├── .env - Your settings
│   └── helpers/
│       ├── polymarket_rtds.py - RTDS WebSocket
│       ├── polymarket.py - Gamma/CLOB APIs
│       ├── pricing.py - Volatility & Black-Scholes
│       └── performance_logger.py - Logging system
├── logs/
│   ├── analyze_logs.py - Analysis tool
│   └── YYYYMMDD_HHMMSS/ - Session directories (auto-created)
├── historical_data/
│   ├── market_data/ - Download historical markets
│   │   └── download_historical_markets.py
│   ├── rtds_recording/ - Record live RTDS stream
│   │   └── record_rtds_stream.py
│   └── visualizations/ - Plot market prices
│       └── plot_market_prices.py
├── test/ - Unit tests
└── docs/ - Additional documentation
```

## ⚙️ Configuration (.env)

```bash
# Trading
TRADING_SYMBOLS=BTC  # Comma-separated: BTC,ETH,SOL
EDGE_THRESHOLD=0.02  # 2% minimum edge to trade
MAX_POSITION_SIZE=100.0
MIN_TIME_TO_EXPIRY=2.0  # minutes
MAX_TIME_TO_EXPIRY=15.0

# Pricing  
LAMBDA_PARAM=0.94  # EWMA decay (higher=slower adaptation)
RISK_FREE_RATE=0.05

# System
DRY_RUN=true  # false for live trading
POLYMARKET_PRIVATE_KEY=your_key
POLYMARKET_FUNDER_ADDRESS=your_address
```

## 🔧 Tools

### Historical Data
```bash
# Download 30 days of BTC markets with price history
cd historical_data/market_data
python download_historical_markets.py --days 30 --asset BTC

# Visualize a market
cd ../visualizations  
python plot_market_prices.py ../market_data/historical_btc_30d.json --market-index 5
```

### RTDS Recording
```bash
# Record live Chainlink prices  
cd historical_data/rtds_recording
python record_rtds_stream.py --symbols BTC ETH --duration 3600
```

### Testing
```bash
pytest test/                     # All tests
pytest test/test_strike_timing.py  # Specific test
pytest --cov=src test/           # With coverage
```

## 📈 Trading Strategy

**Edge Calculation:**
```python
fair_prob_up = black_scholes(strike, spot, vol, time)
market_prob_up = (yes_bid + yes_ask) / 2
edge = fair_prob_up - market_prob_up
```

**Position Sizing:**
```python
if abs(edge) >= threshold:
    size = abs(edge) * sizing_factor
    size = min(size, max_position_size)
```

**Decisions:**
- **BUY YES**: edge > threshold (market underpricing UP)
- **SELL YES**: edge < -threshold (market overpricing UP)  
- **BUY NO/SELL NO**: Similar for DOWN
- **PASS**: |edge| < threshold

## 🐛 Troubleshooting

**No markets found:**
```bash
# Check API
python -c "from src.helpers.polymarket import PolymarketClient; from src.config import get_config; pc = PolymarketClient.from_config(get_config().polymarket); print(len(pc.get_crypto_15min_markets(['BTC'])))"

# Adjust time filters in .env
MIN_TIME_TO_EXPIRY=0.5
MAX_TIME_TO_EXPIRY=20.0
```

**Strike price not set:**
- Start bot before market begins (to buffer prices)
- Bot skips markets without accurate strike price
- This ensures pricing accuracy

**Logging errors:**
- Check `logs/` directory exists and has write permissions
- Verify disk space
- Ctrl+C is safe (graceful shutdown)

## 📖 Learn More

**In `docs/` directory:**
- `POLYMARKET_RTDS_GUIDE.md` - RTDS WebSocket details
- `TESTING_GUIDE.md` - Testing strategies  
- `MIGRATION_SUMMARY.md` - System evolution

**Market Mechanics:**
- 15-min markets at :00, :15, :30, :45 each hour
- Settlement to Chainlink oracle price
- Winners get 1.0, losers get 0.0

**Black-Scholes Adaptation:**
- Standard formula adapted for binary outcomes
- UP probability = N(d₁), DOWN = 1 - N(d₁)
- Accounts for volatility and time decay

## 🚨 Best Practices

1. **Start with DRY_RUN=true** to test
2. **Use small positions** initially  
3. **Monitor logs** to understand behavior
4. **Backtest with historical data** before live trading
5. **Adjust parameters** based on performance

## 📊 Analysis Workflow

```bash
# 1. Run market maker
python src/main.py
# ... let it trade for a session ...
# Ctrl+C to stop

# 2. Quick analysis
python logs/analyze_logs.py logs/20241228_150000

# 3. Custom analysis
python
>>> import json
>>> with open('logs/20241228_150000/decisions.jsonl') as f:
...     decisions = [json.loads(line) for line in f]
>>> trades = [d for d in decisions if d['decision_type'] == 'trade']
>>> print(f"Total trades: {len(trades)}")

# 4. Match with outcomes (from historical_data)
# Calculate win rate, PnL, optimal parameters
```

## 🎓 Understanding the System

### Architecture
```
RTDS WebSocket → Price Ticks → EWMA Volatility
                                     ↓
                            Black-Scholes Pricing
                                     ↓
Gamma API → Market Discovery → Fair Probabilities
                 ↓                   ↓
      Strike @ Start Time    Compare with Market
                 ↓                   ↓
     CLOB API Order Books      Calculate Edge
                 ↓                   ↓
          Position Sizing      Trade Decision
                                     ↓
                              Order Placement
```

### Data Flow
1. **RTDS**: Real-time Chainlink prices (BTC/USD, ETH/USD, etc.)
2. **Volatility**: EWMA on price returns → annualized σ
3. **Markets**: Discover active 15-min markets from Gamma API
4. **Strike**: Capture exact price at market start from price buffer
5. **Pricing**: Black-Scholes → fair UP/DOWN probabilities
6. **Order Book**: Get current YES/NO bids/asks from CLOB API
7. **Edge**: Compare fair vs market prices
8. **Size**: Kelly-inspired edge-based sizing
9. **Log**: Everything recorded for analysis

## 💾 Disk Usage

**Logs**: ~15-20 MB/hour per session
- 24-hour session: ~350-500 MB
- Manage with: `find logs/ -type d -mtime +30 -exec rm -rf {} +`

**Historical data**: Varies by days downloaded
- 30 days BTC markets: ~50-100 MB with price history

## 🔐 Security

- Never commit `.env` file (already in .gitignore)
- Keep private keys secure
- Use separate keys for dev/prod
- Monitor for unusual activity

---

**Ready?** Run `python src/main.py` and watch it work!

For detailed API documentation, testing guides, and migration history, see the `docs/` directory.
