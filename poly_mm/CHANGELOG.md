# Changelog

All notable changes to the Polymarket Market Maker project.

## [2024-12-28] - Documentation Consolidation

### Changed
- **Documentation Structure**: Consolidated 58 markdown files into 4 essential documents
  - `README.md` - Main documentation and quick start
  - `LOGGING.md` - Complete logging system reference
  - `HISTORICAL_DATA.md` - Historical data tools guide
  - `API_REFERENCE.md` - API documentation
- **Backup**: Created `markdown_backup_YYYYMMDD_HHMMSS.tar.gz` with all previous docs

### Removed
- 20+ redundant markdown files from docs/, src/, historical_data/ subdirectories
- Duplicate quick start guides
- Overlapping logging documentation
- Redundant subdirectory READMEs

---

## [2024-12-27] - Comprehensive Logging System

### Added
- **PerformanceLogger** class with 8 separate JSONL log files:
  - `price_ticks.jsonl` - Every Chainlink price update
  - `markets.jsonl` - Market state transitions
  - `orderbooks.jsonl` - Order book snapshots
  - `calculations.jsonl` - All pricing calculations with inputs/outputs
  - `decisions.jsonl` - Trade decisions with reasoning
  - `trades.jsonl` - Order executions
  - `performance.jsonl` - System metrics every 60 seconds
  - `events.jsonl` - System events and errors
- Session-based log directories: `logs/YYYYMMDD_HHMMSS/`
- Analysis tool: `logs/analyze_logs.py`

### Changed
- Integrated logging throughout `main.py`
- Maximum verbosity for replay and performance analysis
- Graceful shutdown with proper file closing

### Fixed
- AttributeError: PriceTick object has no attribute 'market' → Changed to `volume`
- AttributeError: PriceTick object has no attribute 'asset_id' → Changed to `trade_id`
- AttributeError: VolatilityState object has no attribute 'window_size' → Removed references
- ValueError: I/O operation on closed file → Added safety checks in logger.close()

---

## [2024-12-26] - Price History Time Filtering

### Changed
- **download_historical_markets.py**: Updated `fetch_price_history()` to filter price data
  - Accepts `start_time` and `end_time` parameters
  - Filters price points to only include data between market start and expiry
  - Reduces data by ~99% for recent markets (2,880 → ~20-40 points)

### Implementation
- Client-side filtering after API fetch (CLOB API returns full history)
- Uses `interval=max` for full resolution, then filters by timestamp
- Ensures downloaded data only includes relevant market window

---

## [2024-12-20] - Strike Price Timing Implementation

### Added
- **Price Buffer**: 60-second rolling buffer of Chainlink prices
- **Strike Capture**: Retrieves exact price at market start time (±5s tolerance)
- **Market States**: waiting → active → strike_set → expired
- **Skip Logic**: Markets without accurate strike price are skipped

### Changed
- Strike price now captured from live price buffer, not fetched separately
- Ensures pricing accuracy by using exact start-time price
- Prevents trading on markets with uncertain strike prices

### Implementation Details
- PriceBuffer class stores last 60 seconds of ticks
- get_price_at_time() retrieves price within ±5s of target time
- Market maker only trades on markets with strike_set state

---

## [2024-12-15] - RTDS Integration

### Added
- Polymarket RTDS (Real-Time Data Stream) integration
- WebSocket client for Chainlink oracle prices
- Support for BTC, ETH, SOL price streams

### Removed
- Binance WebSocket integration (replaced by RTDS)
- Direct Chainlink API calls (replaced by RTDS)

### Benefits
- Single data source (simpler architecture)
- Prices match settlement (same Chainlink source Polymarket uses)
- No authentication required for crypto prices
- Lower latency (~100ms)

---

## [2024-12-10] - Black-Scholes Pricing

### Added
- Black-Scholes model adapted for binary options
- EWMA volatility estimation
- Kelly-inspired position sizing
- Edge-based trade decisions

### Configuration
- `LAMBDA_PARAM` - EWMA decay factor (default: 0.94)
- `EDGE_THRESHOLD` - Minimum edge to trade (default: 0.02 = 2%)
- `SIZING_FACTOR` - Position sizing multiplier (default: 20.0)

### Formula
```
d₁ = [ln(S/K) + (r + σ²/2)×T] / (σ√T)
prob_up = N(d₁)
edge = prob_up - market_prob
size = edge × sizing_factor
```

---

## [2024-12-05] - Initial Release

### Added
- Market discovery via Gamma API
- Order book retrieval via CLOB API
- Basic market maker structure
- Dry run mode for testing
- Configuration via .env file

### Features
- 15-minute market focus
- Multi-symbol support (BTC, ETH, SOL)
- Dry run testing
- Basic error handling

---

## Configuration History

### Current Defaults
```bash
TRADING_SYMBOLS=BTC
EDGE_THRESHOLD=0.02
MAX_POSITION_SIZE=100.0
MIN_TIME_TO_EXPIRY=2.0
MAX_TIME_TO_EXPIRY=15.0
LAMBDA_PARAM=0.94
RISK_FREE_RATE=0.05
DRY_RUN=true
```

### Previous Versions
- **v1.0**: EDGE_THRESHOLD=0.03 (too conservative)
- **v1.1**: LAMBDA_PARAM=0.90 (too reactive)
- **v1.2**: SIZING_FACTOR=10.0 (too small)

---

## Known Issues

### Active
- None currently

### Resolved
- ✓ Strike price timing (2024-12-20)
- ✓ AttributeError on PriceTick attributes (2024-12-27)
- ✓ File closing errors (2024-12-27)
- ✓ Documentation overload (2024-12-28)

---

## Roadmap

### Short Term
- [ ] Multi-threaded order book fetching
- [ ] Advanced position sizing (Kelly criterion)
- [ ] Stop-loss implementation

### Medium Term
- [ ] Machine learning for volatility prediction
- [ ] Multi-market correlation analysis
- [ ] Automated parameter optimization

### Long Term
- [ ] GUI dashboard for monitoring
- [ ] Cloud deployment
- [ ] Multi-exchange support

---

## Migration Notes

### From v1.x to v2.0 (RTDS Integration)
1. Remove Binance API keys from .env
2. Remove Chainlink API configuration
3. Add RTDS_WS_URL (optional, has default)
4. Update symbol format: `BTC` not `BTCUSD`

### From v2.x to v3.0 (Logging System)
1. Ensure `logs/` directory exists (auto-created)
2. Check disk space (~500 MB per 24h session)
3. Update analysis tools to use JSONL format
4. Configure log rotation if needed

### From v3.x to v4.0 (Documentation Consolidation)
1. All docs now in 4 main files
2. Old docs backed up in `markdown_backup_*.tar.gz`
3. Update bookmarks/references to new file structure

---

## Contributors

- Callum - Primary developer
- GitHub Copilot - Code assistance

---

## License

Private project - All rights reserved

---

**Stay updated** by checking this changelog regularly!
