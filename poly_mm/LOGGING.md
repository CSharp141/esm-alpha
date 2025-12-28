# Performance Logging System

Complete reference for the 8-file JSONL logging system used for replay, analysis, and debugging.

## Overview

Every session creates a timestamped directory (`logs/YYYYMMDD_HHMMSS/`) with 8 log files that capture **everything** the market maker sees and does.

**Purpose**: Maximum verbosity for complete replay and performance analysis.

## Log Files

### 1. price_ticks.jsonl
Every Chainlink price update (~2 ticks/second).

```json
{
  "timestamp": "2024-12-28T10:32:05.123456",
  "symbol": "BTC",
  "price": 42500.00,
  "volume": 1.5,
  "trade_id": "abc123"
}
```

**Use**: Reconstruct volatility calculations, verify timing.

### 2. markets.jsonl
Market state transitions.

```json
{
  "timestamp": "2024-12-28T10:30:00.000000",
  "market_id": "0x123...",
  "token_id": "456",
  "state": "active",
  "start_time": "2024-12-28T10:30:00",
  "end_time": "2024-12-28T10:45:00",
  "current_price": null,
  "strike_price": 42500.00
}
```

**States**: `waiting`, `active`, `strike_set`, `expired`

**Use**: Track market lifecycle, verify strike price capture.

### 3. orderbooks.jsonl
Order book snapshots before each decision.

```json
{
  "timestamp": "2024-12-28T10:32:15.000000",
  "market_id": "0x123...",
  "yes_bids": [
    {"price": 0.52, "size": 100.0},
    {"price": 0.51, "size": 250.0}
  ],
  "yes_asks": [
    {"price": 0.53, "size": 150.0},
    {"price": 0.54, "size": 200.0}
  ],
  "no_bids": [
    {"price": 0.47, "size": 120.0}
  ],
  "no_asks": [
    {"price": 0.48, "size": 180.0}
  ]
}
```

**Use**: Verify market prices, check liquidity, analyze spreads.

### 4. calculations.jsonl
All pricing calculations with inputs and outputs.

```json
{
  "timestamp": "2024-12-28T10:32:15.000000",
  "market_id": "0x123...",
  "calculation_type": "probability",
  "inputs": {
    "strike_price": 42500.00,
    "current_price": 42550.00,
    "volatility": 0.65,
    "time_to_expiry": 12.75
  },
  "outputs": {
    "prob_up": 0.548,
    "prob_down": 0.452
  }
}
```

**Calculation Types**:
- `volatility` - EWMA calculation
- `probability` - Black-Scholes UP/DOWN
- `sizing` - Position sizing

**Use**: Debug pricing, verify math, optimize parameters.

### 5. decisions.jsonl
Every trade decision with full reasoning.

```json
{
  "timestamp": "2024-12-28T10:32:15.000000",
  "market_id": "0x123...",
  "decision_type": "trade",
  "action": "buy_yes",
  "reasoning": {
    "edge": 0.048,
    "fair_prob_up": 0.548,
    "market_prob_up": 0.500,
    "threshold": 0.02,
    "size": 48.0
  }
}
```

**Decision Types**: `trade`, `pass`, `skip`  
**Actions**: `buy_yes`, `sell_yes`, `buy_no`, `sell_no`

**Use**: Understand why trades were/weren't made, optimize edge threshold.

### 6. trades.jsonl
Executed orders (live trading only).

```json
{
  "timestamp": "2024-12-28T10:32:15.500000",
  "market_id": "0x123...",
  "order_id": "789",
  "side": "BUY",
  "outcome": "YES",
  "size": 48.0,
  "price": 0.50,
  "status": "filled"
}
```

**Use**: Track executions, calculate PnL, match with outcomes.

### 7. performance.jsonl
Metrics every 60 seconds.

```json
{
  "timestamp": "2024-12-28T10:33:00.000000",
  "price_tick_rate": 1.95,
  "total_ticks": 117,
  "volatility_btc": 0.65,
  "active_markets": 3,
  "decisions_made": 12,
  "trades_executed": 2
}
```

**Use**: Monitor system health, verify tick rate, check activity.

### 8. events.jsonl
System events, errors, configuration.

```json
{
  "timestamp": "2024-12-28T10:30:00.000000",
  "event_type": "error",
  "message": "Failed to get order book",
  "context": {
    "market_id": "0x123...",
    "error": "Connection timeout"
  }
}
```

**Event Types**: `info`, `error`, `config`, `startup`, `shutdown`

**Use**: Debug issues, verify configuration, track system lifecycle.

## Usage

### Basic Analysis

```python
import json
from pathlib import Path

# Load logs
session = Path("logs/20241228_103000")
with open(session / "decisions.jsonl") as f:
    decisions = [json.loads(line) for line in f]

# Count trades
trades = [d for d in decisions if d['decision_type'] == 'trade']
print(f"Total trades: {len(trades)}")

# Calculate win rate (if you have outcomes)
buy_yes = [d for d in trades if d['action'] == 'buy_yes']
# ... match with settlement data ...
```

### Provided Analysis Tool

```bash
python logs/analyze_logs.py logs/20241228_103000
```

**Output**:
- Session duration
- Total ticks, markets, decisions
- Trade breakdown by action
- Edge distribution
- Volatility statistics
- Error summary

### Custom Analysis Examples

**1. Replay Volatility:**
```python
with open(session / "price_ticks.jsonl") as f:
    ticks = [json.loads(line) for line in f]

with open(session / "calculations.jsonl") as f:
    vol_calcs = [json.loads(line) for line in f 
                 if line['calculation_type'] == 'volatility']

# Plot volatility over time
import matplotlib.pyplot as plt
times = [c['timestamp'] for c in vol_calcs]
vols = [c['outputs']['annualized_vol'] for c in vol_calcs]
plt.plot(times, vols)
```

**2. Edge vs Outcome:**
```python
# Match decisions with settlement
decisions_df = pd.DataFrame(decisions)
outcomes_df = pd.read_json("historical_data/settlements.jsonl", lines=True)
merged = decisions_df.merge(outcomes_df, on='market_id')

# Calculate profitability by edge bucket
merged['edge_bucket'] = pd.cut(merged['edge'], bins=10)
pnl_by_edge = merged.groupby('edge_bucket')['pnl'].mean()
```

**3. Timing Analysis:**
```python
# Time between decisions
decision_times = [d['timestamp'] for d in decisions]
decision_times = pd.to_datetime(decision_times)
time_diffs = decision_times.diff()
print(f"Avg time between decisions: {time_diffs.mean()}")
```

**4. Order Book Analysis:**
```python
with open(session / "orderbooks.jsonl") as f:
    books = [json.loads(line) for line in f]

# Average spread
spreads = []
for book in books:
    yes_spread = book['yes_asks'][0]['price'] - book['yes_bids'][0]['price']
    spreads.append(yes_spread)
print(f"Average YES spread: {sum(spreads) / len(spreads):.4f}")
```

## Implementation Details

### Logger Class (`src/helpers/performance_logger.py`)

```python
from src.helpers.performance_logger import PerformanceLogger

# Initialize (auto-creates session directory)
logger = PerformanceLogger()

# Log price tick
logger.log_price_tick(tick.symbol, tick.price, tick.volume, tick.trade_id)

# Log market state
logger.log_market_state(market.market_id, market.token_id, "active", 
                        market.start_time, market.end_time, 
                        current_price=42550.00, strike_price=42500.00)

# Log order book
logger.log_orderbook(market_id, yes_bids, yes_asks, no_bids, no_asks)

# Log calculation
logger.log_calculation(market_id, "probability", 
                       inputs={"strike": 42500, "spot": 42550, "vol": 0.65},
                       outputs={"prob_up": 0.548})

# Log decision
logger.log_decision(market_id, "trade", "buy_yes",
                   reasoning={"edge": 0.048, "size": 48.0})

# Log trade (if executed)
logger.log_trade(market_id, order_id, "BUY", "YES", 48.0, 0.50, "filled")

# Log performance (called every 60s)
logger.log_performance(price_tick_rate=1.95, total_ticks=117, 
                      volatility_btc=0.65, active_markets=3)

# Log error
logger.log_error(error_type="API", message="Connection timeout", 
                context={"market_id": market_id})

# Cleanup
logger.close()
```

### Integration Points (main.py)

1. **Initialization** (`__init__`):
   ```python
   self.logger = PerformanceLogger()
   self.logger.log_event("startup", "Market maker initialized", config_dict)
   ```

2. **Price Ticks** (`on_price_tick`):
   ```python
   self.logger.log_price_tick(tick.symbol, tick.price, tick.volume, tick.trade_id)
   ```

3. **Volatility Updates** (`on_price_tick`):
   ```python
   self.logger.log_calculation(None, "volatility",
       inputs={"price": tick.price, "lambda": self.config.pricing.lambda_param},
       outputs={"annualized_vol": vol_state.annualized_vol, 
                "variance": vol_state.variance, 
                "sample_count": vol_state.sample_count})
   ```

4. **Market Discovery** (`discover_markets`):
   ```python
   self.logger.log_market_state(market.market_id, market.token_id, "waiting",
                                 market.start_time, market.end_time)
   ```

5. **Strike Capture** (`update_market_state`):
   ```python
   self.logger.log_market_state(market.market_id, market.token_id, "strike_set",
                                 market.start_time, market.end_time,
                                 strike_price=strike_price)
   ```

6. **Before Decision** (`check_trading_opportunity`):
   ```python
   self.logger.log_orderbook(market.market_id, yes_bids, yes_asks, no_bids, no_asks)
   ```

7. **Probability Calculation** (`check_trading_opportunity`):
   ```python
   self.logger.log_calculation(market.market_id, "probability",
       inputs={"strike": strike, "spot": current_price, "vol": vol, "time": time_to_expiry},
       outputs={"prob_up": prob_up, "prob_down": prob_down})
   ```

8. **Sizing** (`check_trading_opportunity`):
   ```python
   self.logger.log_calculation(market.market_id, "sizing",
       inputs={"edge": edge, "sizing_factor": sizing_factor},
       outputs={"size": size})
   ```

9. **Decision** (`check_trading_opportunity`):
   ```python
   self.logger.log_decision(market.market_id, "trade", action,
       reasoning={"edge": edge, "fair_prob_up": prob_up, 
                  "market_prob_up": market_prob, "size": size})
   ```

10. **Trade Execution** (`place_order`):
    ```python
    self.logger.log_trade(market_id, order_id, side, outcome, size, price, status)
    ```

11. **Performance Metrics** (`check_markets`, every 60s):
    ```python
    self.logger.log_performance(
        price_tick_rate=tick_rate,
        total_ticks=self.tick_count,
        volatility_btc=vol_state.annualized_vol,
        active_markets=len(self.active_markets),
        decisions_made=self.decision_count,
        trades_executed=self.trade_count
    )
    ```

12. **Errors**:
    ```python
    self.logger.log_error("API", f"Failed to get markets: {e}", 
                         context={"symbol": symbol})
    ```

13. **Shutdown**:
    ```python
    self.logger.log_event("shutdown", "Market maker stopped")
    self.logger.close()
    ```

## File Format (JSONL)

Each line is a complete JSON object:
```
{"timestamp": "...", "field1": "value1"}
{"timestamp": "...", "field2": "value2"}
```

**Benefits**:
- Append-only (safe for concurrent writes)
- Line-by-line processing (memory efficient)
- Standard format (works with pandas, jq, etc.)

**Reading**:
```python
# Python
with open("log.jsonl") as f:
    for line in f:
        obj = json.loads(line)

# Pandas
import pandas as pd
df = pd.read_json("log.jsonl", lines=True)

# Command line
jq '.' log.jsonl
grep '"action": "buy_yes"' decisions.jsonl | jq .
```

## Disk Management

**Size**: ~15-20 MB/hour → ~350-500 MB/24h session

**Cleanup** (delete sessions older than 30 days):
```bash
find logs/ -type d -mtime +30 -exec rm -rf {} +
```

**Compression** (archive old sessions):
```bash
tar -czf logs_archive_202412.tar.gz logs/202412*
rm -rf logs/202412*
```

## Safety Features

1. **Graceful shutdown**: Ctrl+C triggers `logger.close()` via try/finally
2. **Double-close protection**: Checks `file.closed` before closing
3. **Auto-directory creation**: Creates `logs/` and session dirs automatically
4. **Atomic writes**: Each log line written atomically (JSON + newline)
5. **Error isolation**: Logging failures don't crash the bot

## Troubleshooting

**No logs directory:**
```bash
mkdir logs
chmod 755 logs
```

**Permission denied:**
```bash
chmod 755 logs/
chmod 644 logs/YYYYMMDD_HHMMSS/*.jsonl
```

**Corrupted log file:**
```python
# Read only valid lines
with open("log.jsonl") as f:
    valid_lines = []
    for i, line in enumerate(f, 1):
        try:
            obj = json.loads(line)
            valid_lines.append(obj)
        except json.JSONDecodeError as e:
            print(f"Skipping line {i}: {e}")
```

**Huge log files:**
- Check `price_ticks.jsonl` size (largest file)
- Verify tick rate is normal (~2/sec for BTC)
- Consider shorter sessions or periodic restarts

## Best Practices

1. **Keep sessions < 24 hours** to manage file sizes
2. **Archive old sessions** regularly
3. **Use analysis scripts** rather than manual inspection
4. **Match with settlement data** for PnL calculation
5. **Track parameter changes** in events.jsonl
6. **Visualize trends** over multiple sessions

## Advanced Analysis

### Multi-Session Comparison
```python
sessions = list(Path("logs").glob("202412*"))
all_decisions = []
for session in sessions:
    with open(session / "decisions.jsonl") as f:
        decisions = [json.loads(line) for line in f]
        for d in decisions:
            d['session'] = session.name
        all_decisions.extend(decisions)

df = pd.DataFrame(all_decisions)
# Compare edge thresholds, win rates, etc.
```

### Real-Time Monitoring
```python
# Tail latest session
import time
session = max(Path("logs").glob("*"), key=lambda p: p.stat().st_mtime)
performance_log = session / "performance.jsonl"

while True:
    with open(performance_log) as f:
        last_line = f.readlines()[-1]
        metrics = json.loads(last_line)
        print(f"Tick rate: {metrics['price_tick_rate']:.2f}, "
              f"Markets: {metrics['active_markets']}")
    time.sleep(60)
```

### Parameter Optimization
```python
# Backtest different edge thresholds
for threshold in [0.01, 0.02, 0.03, 0.04, 0.05]:
    # Filter decisions by threshold
    simulated_trades = [d for d in decisions 
                       if abs(d['reasoning']['edge']) >= threshold]
    # Match with outcomes, calculate PnL
    # ... optimization logic ...
```

---

**Complete logging system** capturing every data point for replay and analysis. Use it to understand, optimize, and validate your market maker!
