# Historical Data Tools

Tools for downloading, recording, and analyzing historical market and price data.

## Overview

Three main tools:
1. **Download Markets** - Download historical Polymarket markets with price history
2. **Record RTDS** - Record live Chainlink price streams
3. **Visualize** - Plot market prices and outcomes

## Tool 1: Download Historical Markets

Download past Polymarket 15-minute markets with complete price history (time-filtered to market duration).

### Location
`historical_data/market_data/download_historical_markets.py`

### Usage

```bash
cd historical_data/market_data

# Download 7 days of BTC markets
python download_historical_markets.py --days 7 --asset BTC

# Multiple assets
python download_historical_markets.py --days 30 --asset BTC,ETH,SOL

# Custom date range
python download_historical_markets.py --start 2024-12-01 --end 2024-12-31 --asset BTC
```

### Output Format

**File**: `historical_btc_Xd.json` or `historical_btc_YYYYMMDD_YYYYMMDD.json`

```json
{
  "metadata": {
    "download_time": "2024-12-28T10:00:00Z",
    "start_date": "2024-12-21T00:00:00Z",
    "end_date": "2024-12-28T10:00:00Z",
    "asset": "BTC",
    "total_markets": 672
  },
  "markets": [
    {
      "market_id": "0x123...",
      "token_id": "456",
      "question": "Will BTC price be higher at 10:45 than 10:30?",
      "start_time": "2024-12-28T10:30:00Z",
      "end_time": "2024-12-28T10:45:00Z",
      "condition_id": "0xabc...",
      "neg_risk": true,
      "outcome": "Yes",
      "settlement_price_yes": 1.0,
      "settlement_price_no": 0.0,
      "price_history": [
        {
          "timestamp": "2024-12-28T10:30:15Z",
          "price": 0.50,
          "side": "BUY"
        },
        {
          "timestamp": "2024-12-28T10:32:00Z",
          "price": 0.52,
          "side": "BUY"
        }
        // ... more price points ...
      ]
    }
    // ... more markets ...
  ]
}
```

### Time Filtering

**Problem**: CLOB API returns full price history (inception → now) per market.
- 15-minute market starting today might have 2,880 price points (48 hours of data)
- Only ~20-40 points actually relevant (during 15-minute window)

**Solution**: Client-side filtering after download.
- Fetch with `interval=max` (full resolution)
- Filter to `start_time <= timestamp <= end_time`
- Reduces data by ~99% for recent markets

**Implementation**:
```python
def fetch_price_history(client, token_id, start_time, end_time):
    """Fetch and filter price history to market duration."""
    # Fetch full history
    raw_history = client.get_price_history(token_id, interval="max", fidelity=10)
    
    # Filter to market window
    start_ts = start_time.timestamp()
    end_ts = end_time.timestamp()
    
    filtered = [
        tick for tick in raw_history
        if start_ts <= tick['timestamp'] <= end_ts
    ]
    
    return filtered
```

### Analysis Examples

**1. Win Rate by Time to Expiry:**
```python
import json
import pandas as pd

with open("historical_btc_30d.json") as f:
    data = json.load(f)

markets = []
for m in data['markets']:
    duration = (pd.to_datetime(m['end_time']) - 
                pd.to_datetime(m['start_time'])).seconds / 60
    markets.append({
        'duration': duration,
        'outcome': m['outcome'],
        'price_points': len(m['price_history'])
    })

df = pd.DataFrame(markets)
print(df.groupby('outcome').size())
```

**2. Initial vs Final Price:**
```python
for m in data['markets']:
    if len(m['price_history']) >= 2:
        initial = m['price_history'][0]['price']
        final = m['price_history'][-1]['price']
        outcome = m['outcome']
        print(f"Initial: {initial:.3f}, Final: {final:.3f}, Outcome: {outcome}")
```

**3. Price Volatility:**
```python
import numpy as np

for m in data['markets']:
    prices = [p['price'] for p in m['price_history']]
    if len(prices) > 1:
        volatility = np.std(prices)
        print(f"Market {m['market_id'][:8]}: vol={volatility:.4f}")
```

## Tool 2: Record RTDS Stream

Record live Chainlink price updates from Polymarket RTDS WebSocket.

### Location
`historical_data/rtds_recording/record_rtds_stream.py`

### Usage

```bash
cd historical_data/rtds_recording

# Record BTC for 1 hour
python record_rtds_stream.py --symbols BTC --duration 3600

# Multiple symbols for 30 minutes
python record_rtds_stream.py --symbols BTC,ETH,SOL --duration 1800

# Run indefinitely (Ctrl+C to stop)
python record_rtds_stream.py --symbols BTC
```

### Output Format

**File**: `rtds_recording_YYYYMMDD_HHMMSS.jsonl`

```json
{"timestamp": "2024-12-28T10:30:15.123456", "symbol": "BTC", "price": 42500.00, "volume": 1.5, "trade_id": "abc123"}
{"timestamp": "2024-12-28T10:30:15.654321", "symbol": "BTC", "price": 42501.25, "volume": 0.8, "trade_id": "def456"}
{"timestamp": "2024-12-28T10:30:16.111111", "symbol": "BTC", "price": 42500.50, "volume": 2.1, "trade_id": "ghi789"}
```

### Analysis Examples

**1. Tick Rate:**
```python
import json
from datetime import datetime

with open("rtds_recording_20241228_103000.jsonl") as f:
    ticks = [json.loads(line) for line in f]

timestamps = [datetime.fromisoformat(t['timestamp']) for t in ticks]
time_diffs = [(timestamps[i+1] - timestamps[i]).total_seconds() 
              for i in range(len(timestamps)-1)]

avg_tick_rate = 1 / (sum(time_diffs) / len(time_diffs))
print(f"Average tick rate: {avg_tick_rate:.2f} ticks/second")
```

**2. Price Range:**
```python
prices = [t['price'] for t in ticks]
print(f"Min: ${min(prices):.2f}, Max: ${max(prices):.2f}, "
      f"Range: ${max(prices) - min(prices):.2f}")
```

**3. Replay for Testing:**
```python
# Simulate live feed from recording
import time

with open("rtds_recording_20241228_103000.jsonl") as f:
    for line in f:
        tick = json.loads(line)
        # Process tick as if it were live
        process_price_tick(tick['symbol'], tick['price'])
        time.sleep(0.5)  # Simulate real-time spacing
```

## Tool 3: Visualize Market Prices

Plot YES token prices over time with market outcome.

### Location
`historical_data/visualizations/plot_market_prices.py`

### Usage

```bash
cd historical_data/visualizations

# Plot specific market (by index in JSON file)
python plot_market_prices.py ../market_data/historical_btc_30d.json --market-index 5

# Interactive selection
python plot_market_prices.py ../market_data/historical_btc_30d.json

# Save to file instead of display
python plot_market_prices.py ../market_data/historical_btc_30d.json --market-index 5 --output market5.png
```

### Output

**Plot**:
- X-axis: Time (market start → end)
- Y-axis: YES token price (0.0 - 1.0)
- Title: Question + outcome
- Markers: Start, strike capture, expiry

**Example**:
```
Will BTC price be higher at 10:45 than 10:30?
Outcome: Yes (Settlement: 1.0)

1.0 |                        ●  (expiry)
    |                    ●●●
0.8 |                ●●●
    |            ●●●
0.6 |        ●●●
    |    ●●●
0.4 |●●●
0.2 |
0.0 |
    +-----|-----|-----|-----|-----
   10:30      10:35     10:40  10:45
   (start)
```

### Use Cases

1. **Understand Market Dynamics**: See how YES price moves before expiry
2. **Validate Pricing Model**: Compare Black-Scholes predictions to actual prices
3. **Spot Patterns**: Identify consistent price trends
4. **Check Data Quality**: Verify price history is complete and reasonable

## Data Directory Structure

```
historical_data/
├── market_data/
│   ├── download_historical_markets.py
│   ├── historical_btc_7d.json
│   ├── historical_btc_30d.json
│   └── historical_eth_30d.json
├── rtds_recording/
│   ├── record_rtds_stream.py
│   ├── rtds_recording_20241228_103000.jsonl
│   └── rtds_recording_20241228_150000.jsonl
└── visualizations/
    ├── plot_market_prices.py
    └── market_plots/
        ├── market_0.png
        ├── market_1.png
        └── ...
```

## Common Workflows

### Workflow 1: Backtest Strategy

```bash
# 1. Download historical markets
cd historical_data/market_data
python download_historical_markets.py --days 30 --asset BTC

# 2. Record current RTDS stream for calibration
cd ../rtds_recording
python record_rtds_stream.py --symbols BTC --duration 3600

# 3. Analyze historical data
python
>>> import json
>>> with open("../market_data/historical_btc_30d.json") as f:
...     data = json.load(f)
>>> # Simulate trading with your strategy
>>> # Compare simulated trades to actual outcomes

# 4. Visualize interesting markets
cd ../visualizations
python plot_market_prices.py ../market_data/historical_btc_30d.json
```

### Workflow 2: Calibrate Volatility

```bash
# 1. Record RTDS for 24 hours
cd historical_data/rtds_recording
python record_rtds_stream.py --symbols BTC --duration 86400

# 2. Calculate EWMA with different lambdas
python
>>> import json
>>> import numpy as np
>>> with open("rtds_recording_20241228_000000.jsonl") as f:
...     ticks = [json.loads(line) for line in f]
>>> prices = [t['price'] for t in ticks]
>>> returns = np.diff(np.log(prices))
>>> 
>>> # Test lambda values
>>> for lam in [0.90, 0.92, 0.94, 0.96, 0.98]:
...     ewma_var = calculate_ewma(returns, lam)
...     print(f"Lambda {lam}: vol={np.sqrt(ewma_var):.4f}")

# 3. Choose best lambda and update config
vim ../../src/.env
# LAMBDA_PARAM=0.94
```

### Workflow 3: Debug Live Issues

```bash
# 1. Download recent markets to check metadata
cd historical_data/market_data
python download_historical_markets.py --days 1 --asset BTC

# 2. Compare with live RTDS stream
cd ../rtds_recording
python record_rtds_stream.py --symbols BTC --duration 300  # 5 min

# 3. Check if strike prices match
python
>>> import json
>>> with open("../market_data/historical_btc_1d.json") as f:
...     data = json.load(f)
>>> with open("rtds_recording_20241228_103000.jsonl") as f:
...     ticks = [json.loads(line) for line in f]
>>> 
>>> # Find market that started at 10:30
>>> market = [m for m in data['markets'] 
...           if "10:30" in m['start_time']][0]
>>> 
>>> # Find RTDS tick at 10:30
>>> tick = [t for t in ticks 
...         if "10:30" in t['timestamp'][:16]][0]
>>> 
>>> print(f"Expected strike: {tick['price']}")
>>> # Compare with what your bot captured
```

## API Details

### Gamma API (Metadata)
```python
from src.helpers.polymarket import PolymarketClient

client = PolymarketClient.from_config(config)
markets = client.get_crypto_15min_markets(['BTC'])

# Returns: List of Market objects with:
# - market_id, token_id
# - start_time, end_time
# - question, condition_id
# - neg_risk flag
```

### CLOB API (Price History)
```python
price_history = client.get_price_history(
    token_id="123456",
    interval="max",  # Full resolution
    fidelity=10      # Recent data priority
)

# Returns: List of dicts:
# [{"timestamp": 1703764800, "price": 0.5, "side": "BUY"}, ...]
```

### RTDS WebSocket (Live Prices)
```python
from src.helpers.polymarket_rtds import PolymarketRTDS

rtds = PolymarketRTDS()
rtds.connect(['BTC'])

async for tick in rtds.get_ticks():
    print(f"{tick.symbol}: ${tick.price}")
    # PriceTick(symbol='BTC', price=42500.0, timestamp=..., 
    #           volume=1.5, trade_id='abc123')
```

## Data Quality Notes

### Price History
- **Completeness**: Older markets have complete 15-min price history
- **Recent Markets**: May have fewer ticks if recently created
- **Gaps**: Possible during low liquidity periods
- **Time Filtering**: Essential to remove pre-market data

### RTDS Stream
- **Tick Rate**: ~1-2 ticks/second for BTC (higher during volatility)
- **Reliability**: Very stable, reconnects automatically
- **Latency**: ~100-200ms typical
- **Symbols**: BTC, ETH, SOL, MATIC, DOGE supported

### Settlement Data
- Markets settle to YES (1.0) or NO (0.0)
- Settlement happens within minutes of expiry
- Can be extracted from `settlement_price_yes` field in downloaded data

## Troubleshooting

**No markets returned:**
```python
# Check date range
markets = client.get_crypto_15min_markets(['BTC'])
if not markets:
    print("No markets in time range")
    # Adjust --days or --start/--end

# Verify asset is correct
# Use: BTC, ETH, SOL (not BTCUSD or btc)
```

**Empty price history:**
```python
# Market might be too new
if len(price_history) == 0:
    print("No price history available yet")
    # Wait for market to accumulate trades

# Or market_id might be wrong
# Verify token_id matches market's YES token
```

**RTDS connection fails:**
```python
# Check internet connection
# Verify symbol is supported: BTC, ETH, SOL, MATIC, DOGE
# Check firewall allows WebSocket connections

# Test connection:
from src.helpers.polymarket_rtds import PolymarketRTDS
rtds = PolymarketRTDS()
success = rtds.connect(['BTC'])
if not success:
    print("Connection failed")
```

**Plot shows weird prices:**
```python
# Check if price history was time-filtered correctly
if price_history[0]['timestamp'] < start_time.timestamp():
    print("Price history includes pre-market data")
    # Re-run download with latest script version

# Verify settlement makes sense
if outcome == "Yes" and final_price < 0.5:
    print("Unexpected: YES won but price was low")
    # Possible data quality issue or late price movement
```

## Best Practices

1. **Download Incrementally**: Don't re-download all history each time
   ```bash
   # Download new data only
   python download_historical_markets.py --days 1 --asset BTC
   # Merge with existing historical_btc_30d.json
   ```

2. **Validate Data**: Check for reasonable values before analysis
   ```python
   assert all(0 <= p['price'] <= 1 for p in price_history)
   assert start_time < end_time
   assert outcome in ['Yes', 'No']
   ```

3. **Handle Missing Data**: Some markets may lack complete history
   ```python
   if len(price_history) < 10:
       print(f"Skipping market {market_id}: insufficient data")
       continue
   ```

4. **Archive Old Data**: Compress historical files periodically
   ```bash
   tar -czf historical_archive_202412.tar.gz historical_*_30d.json
   ```

5. **Version Control**: Track which script version generated data
   ```python
   # In download script
   metadata['script_version'] = "1.2.0"
   metadata['time_filtering'] = True
   ```

## Advanced Usage

### Custom Time Filtering
```python
# Filter to specific time of day (e.g., US market hours)
us_markets = [
    m for m in data['markets']
    if 14 <= pd.to_datetime(m['start_time']).hour <= 21  # 9am-5pm EST
]
```

### Merge Multiple Downloads
```python
import json

files = ['historical_btc_7d.json', 'historical_btc_30d.json']
all_markets = []
for file in files:
    with open(file) as f:
        data = json.load(f)
        all_markets.extend(data['markets'])

# Deduplicate by market_id
unique_markets = {m['market_id']: m for m in all_markets}.values()
```

### Export to CSV
```python
import pandas as pd

# Markets summary
markets_df = pd.DataFrame([
    {
        'market_id': m['market_id'],
        'start_time': m['start_time'],
        'outcome': m['outcome'],
        'price_points': len(m['price_history'])
    }
    for m in data['markets']
])
markets_df.to_csv('markets_summary.csv', index=False)

# All price ticks
ticks_data = []
for m in data['markets']:
    for tick in m['price_history']:
        ticks_data.append({
            'market_id': m['market_id'],
            'timestamp': tick['timestamp'],
            'price': tick['price']
        })
pd.DataFrame(ticks_data).to_csv('all_ticks.csv', index=False)
```

---

**Complete toolkit** for historical data acquisition and analysis. Use these tools to backtest strategies, calibrate parameters, and understand market behavior!
