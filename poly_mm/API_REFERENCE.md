# API Reference

Complete reference for Polymarket APIs and integrations used in the market maker.

## Polymarket RTDS (Real-Time Data Stream)

WebSocket API for live Chainlink oracle prices.

### Connection

```python
from src.helpers.polymarket_rtds import PolymarketRTDS

rtds = PolymarketRTDS()
success = rtds.connect(['BTC', 'ETH'])  # Symbols: BTC, ETH, SOL
```

**Endpoint**: `wss://ws-live-data.polymarket.com`  
**Authentication**: Not required for crypto prices  
**Topic**: `crypto_prices_chainlink`

### Price Updates

```python
async for tick in rtds.get_ticks():
    # tick is a PriceTick dataclass
    print(f"{tick.symbol}: ${tick.price}")
```

**PriceTick Format**:
```python
@dataclass
class PriceTick:
    symbol: str          # "BTC", "ETH", "SOL"
    price: float         # Current price in USD
    timestamp: datetime  # Update time
    volume: float        # Trade volume
    trade_id: str        # Unique trade identifier
```

**Update Rate**: ~1-2 ticks/second for BTC (higher during volatility)

### Supported Symbols

| Symbol | Full Name | Format |
|--------|-----------|--------|
| BTC | Bitcoin | "btc/usd" (in WebSocket) |
| ETH | Ethereum | "eth/usd" |
| SOL | Solana | "sol/usd" |
| MATIC | Polygon | "matic/usd" |
| DOGE | Dogecoin | "doge/usd" |

### Message Format

**Subscribe**:
```json
{
  "type": "subscribe",
  "channel": "crypto_prices_chainlink",
  "symbols": ["btc/usd", "eth/usd"]
}
```

**Price Update**:
```json
{
  "type": "price_update",
  "channel": "crypto_prices_chainlink",
  "data": {
    "symbol": "btc/usd",
    "price": 42500.00,
    "timestamp": "2024-12-28T10:30:15.123456Z",
    "volume": 1.5,
    "trade_id": "abc123"
  }
}
```

### Error Handling

```python
try:
    rtds.connect(['BTC'])
except ConnectionError as e:
    print(f"Failed to connect: {e}")
    # Auto-reconnect after 5 seconds

# Reconnection is automatic
# Check connection: rtds.is_connected()
```

---

## Gamma API (Market Discovery)

REST API for discovering and querying Polymarket markets.

### Endpoint

**Base URL**: `https://gamma-api.polymarket.com`

### Get Markets by Events

```python
from src.helpers.polymarket import PolymarketClient

client = PolymarketClient.from_config(config)
markets = client.get_crypto_15min_markets(['BTC'])
```

**Request**:
```
GET /events?slug=btc-15-minute
```

**Response**:
```json
{
  "id": "event_123",
  "slug": "btc-15-minute",
  "title": "BTC 15-Minute Markets",
  "markets": [
    {
      "id": "0x123...",
      "question": "Will BTC price be higher at 10:45 than 10:30?",
      "condition_id": "0xabc...",
      "neg_risk": true,
      "tokens": [
        {"token_id": "456", "outcome": "Yes", "winner": null},
        {"token_id": "789", "outcome": "No", "winner": null}
      ],
      "start_date_iso": "2024-12-28T10:30:00Z",
      "end_date_iso": "2024-12-28T10:45:00Z",
      "closed": false
    }
  ]
}
```

### Market Object

```python
@dataclass
class Market:
    market_id: str           # "0x123..." - Market ID
    token_id: str            # "456" - YES token ID
    question: str            # Market question
    start_time: datetime     # When market begins
    end_time: datetime       # When market expires
    condition_id: str        # "0xabc..." - Settlement ID
    neg_risk: bool          # True if neg-risk market
    closed: bool            # True if expired/settled
```

### Filter Active Markets

```python
# Get markets starting in next 20 minutes
markets = client.get_crypto_15min_markets(
    symbols=['BTC'],
    min_time_to_expiry=0.5,   # minutes
    max_time_to_expiry=20.0
)
```

---

## CLOB API (Order Book & Trading)

REST API for order books and trade execution.

### Endpoint

**Base URL**: `https://clob.polymarket.com`

### Get Order Book

```python
book = client.get_order_book(token_id="123456")
```

**Request**:
```
GET /book?token_id=123456
```

**Response**:
```json
{
  "bids": [
    {"price": "0.52", "size": "100.0"},
    {"price": "0.51", "size": "250.0"}
  ],
  "asks": [
    {"price": "0.53", "size": "150.0"},
    {"price": "0.54", "size": "200.0"}
  ]
}
```

**Order Object**:
```python
@dataclass
class Order:
    price: float  # Price in probability space (0.0-1.0)
    size: float   # Size in USDC
```

### Get Price History

```python
history = client.get_price_history(
    token_id="123456",
    interval="max",    # Options: "1m", "5m", "1h", "1d", "max"
    fidelity=10       # Recent data priority (1-100)
)
```

**Request**:
```
GET /prices/history?token_id=123456&interval=max&fidelity=10
```

**Response**:
```json
{
  "history": [
    {"t": 1703764800, "p": 0.50, "s": "BUY"},
    {"t": 1703764815, "p": 0.52, "s": "BUY"}
  ]
}
```

**Price Point**:
```python
{
    "timestamp": 1703764800,  # Unix timestamp
    "price": 0.50,            # Price (0.0-1.0)
    "side": "BUY"             # Trade direction
}
```

### Place Order

```python
order_id = client.place_order(
    token_id="123456",
    side="BUY",       # "BUY" or "SELL"
    size=50.0,        # Size in USDC
    price=0.52        # Limit price (0.0-1.0)
)
```

**Request** (requires authentication):
```
POST /order
{
  "token_id": "123456",
  "side": "BUY",
  "size": "50.0",
  "price": "0.52",
  "signature": "0xabc...",
  "expiration": 1703770000
}
```

**Response**:
```json
{
  "order_id": "order_789",
  "status": "pending"
}
```

### Get Order Status

```python
status = client.get_order_status(order_id="order_789")
```

**Statuses**: `pending`, `open`, `matched`, `filled`, `canceled`

---

## Pricing Module

Internal pricing calculations (not an external API).

### Volatility Calculation (EWMA)

```python
from src.helpers.pricing import calculate_volatility, VolatilityState

vol_state = calculate_volatility(
    prev_state=vol_state,
    new_price=42550.00,
    lambda_param=0.94  # Decay factor (0.9-0.99)
)
```

**Returns**:
```python
@dataclass
class VolatilityState:
    annualized_vol: float  # Annualized volatility (e.g., 0.65 = 65%)
    variance: float        # Current variance estimate
    last_update: datetime  # Last update time
    sample_count: int      # Number of samples processed
```

**Algorithm**: Exponentially Weighted Moving Average (EWMA)
```
return = ln(price_t / price_{t-1})
variance_t = λ × variance_{t-1} + (1-λ) × return²
annualized_vol = √(variance × 252 × 24 × 365)  # for crypto
```

### Black-Scholes Probability

```python
from src.helpers.pricing import calculate_probability

prob_up, prob_down = calculate_probability(
    strike_price=42500.00,
    current_price=42550.00,
    volatility=0.65,           # Annualized (0.65 = 65%)
    time_to_expiry=12.5,       # Minutes
    risk_free_rate=0.05        # Annual rate (0.05 = 5%)
)
```

**Returns**: `(prob_up: float, prob_down: float)`  
- Values in range [0.0, 1.0]
- Sum to 1.0

**Formula**:
```
d₁ = [ln(S/K) + (r + σ²/2)×T] / (σ√T)
prob_up = N(d₁)  # Cumulative normal distribution
prob_down = 1 - N(d₁)
```

Where:
- S = current_price (spot)
- K = strike_price
- σ = volatility (annualized)
- T = time_to_expiry (in years)
- r = risk_free_rate (annual)

### Edge Calculation

```python
# Fair probability from Black-Scholes
fair_prob_up = 0.548

# Market probability from order book
market_prob_up = (yes_bid + yes_ask) / 2  # e.g., 0.500

# Edge
edge = fair_prob_up - market_prob_up  # e.g., +0.048 (4.8%)
```

**Interpretation**:
- `edge > 0`: Market underpricing UP (buy YES or sell NO)
- `edge < 0`: Market overpricing UP (sell YES or buy NO)
- `|edge| < threshold`: Pass (no trade)

### Position Sizing

```python
if abs(edge) >= edge_threshold:
    size = abs(edge) * sizing_factor
    size = min(size, max_position_size)
```

**Example**:
```python
edge = 0.048
sizing_factor = 20.0
max_position_size = 100.0

size = 0.048 × 20.0 = 0.96
size = min(0.96, 100.0) = 0.96 USDC
```

---

## Configuration

### Environment Variables (.env)

```bash
# Trading
TRADING_SYMBOLS=BTC,ETH,SOL
EDGE_THRESHOLD=0.02         # 2% minimum edge
MAX_POSITION_SIZE=100.0     # Maximum size per trade
MIN_TIME_TO_EXPIRY=2.0      # Minimum minutes to expiry
MAX_TIME_TO_EXPIRY=15.0     # Maximum minutes to expiry

# Pricing
LAMBDA_PARAM=0.94           # EWMA decay factor
RISK_FREE_RATE=0.05         # Annual risk-free rate

# System
DRY_RUN=true               # true = no real orders
POLYMARKET_PRIVATE_KEY=your_key_here
POLYMARKET_FUNDER_ADDRESS=your_address_here

# Optional
RTDS_WS_URL=wss://ws-live-data.polymarket.com
QUOTE_UPDATE_INTERVAL=5.0  # Seconds between updates
```

### Config Object

```python
from src.config import get_config

config = get_config()

# Access values
config.trading.symbols           # ['BTC', 'ETH']
config.trading.edge_threshold    # 0.02
config.pricing.lambda_param      # 0.94
config.system.dry_run           # True
```

---

## Rate Limits

### RTDS WebSocket
- **Connection**: No explicit limit
- **Messages**: Real-time updates (~2/sec per symbol)
- **Reconnection**: Automatic after 5 seconds

### Gamma API
- **Read operations**: ~100 req/min (unofficial)
- **Best practice**: Cache market data, poll every 30-60 seconds

### CLOB API
- **Order book**: ~60 req/min per token
- **Price history**: ~30 req/min per token
- **Order placement**: ~10 req/min (authenticated)
- **Best practice**: Batch requests, use websockets for real-time data

---

## Authentication

### Private Key (for trading)

```python
from eth_account import Account

# Load from .env
private_key = config.polymarket.private_key
account = Account.from_key(private_key)

# Sign order
message = create_order_message(order_params)
signature = account.sign_message(message)
```

**Required for**:
- Placing orders
- Canceling orders
- Account balances

**NOT required for**:
- RTDS price stream
- Gamma API (market discovery)
- CLOB API (order books, price history)

### Funder Address

Used for Polymarket CTF (Conditional Token Framework) interactions. Set in `.env`:
```bash
POLYMARKET_FUNDER_ADDRESS=0xYourAddress
```

---

## Error Codes

### RTDS WebSocket

| Error | Meaning | Action |
|-------|---------|--------|
| Connection refused | Endpoint down or blocked | Check firewall, retry |
| Invalid symbol | Symbol not supported | Use btc/usd, eth/usd, sol/usd |
| Timeout | No messages for 60s | Auto-reconnect triggered |

### Gamma API

| Status | Meaning | Action |
|--------|---------|--------|
| 404 | Market not found | Check market_id or slug |
| 429 | Rate limit exceeded | Slow down requests |
| 500 | Server error | Retry after delay |

### CLOB API

| Status | Meaning | Action |
|--------|---------|--------|
| 400 | Bad request | Check parameters |
| 401 | Unauthorized | Verify signature |
| 404 | Token not found | Check token_id |
| 429 | Rate limit exceeded | Slow down requests |

---

## Testing

### Test RTDS Connection

```python
from src.helpers.polymarket_rtds import PolymarketRTDS

rtds = PolymarketRTDS()
success = rtds.connect(['BTC'])
if success:
    print("✓ RTDS connected")
else:
    print("✗ RTDS connection failed")
```

### Test Gamma API

```python
from src.helpers.polymarket import PolymarketClient
from src.config import get_config

client = PolymarketClient.from_config(get_config().polymarket)
markets = client.get_crypto_15min_markets(['BTC'])
print(f"Found {len(markets)} BTC markets")
```

### Test Pricing

```python
from src.helpers.pricing import calculate_probability

prob_up, prob_down = calculate_probability(
    strike_price=42500.00,
    current_price=42550.00,
    volatility=0.65,
    time_to_expiry=12.5,
    risk_free_rate=0.05
)
print(f"Prob UP: {prob_up:.3f}, Prob DOWN: {prob_down:.3f}")
```

---

## Best Practices

1. **Cache market data**: Don't fetch markets on every quote update
2. **Batch order book requests**: Get books for all active markets at once
3. **Use RTDS for prices**: Don't poll CLOB price history repeatedly
4. **Handle reconnections**: RTDS auto-reconnects, but verify connectivity
5. **Rate limit awareness**: Space out API calls appropriately
6. **Error handling**: Always catch and log API errors
7. **Dry run first**: Test with `DRY_RUN=true` before live trading

---

## Resources

- **Polymarket Docs**: https://docs.polymarket.com/
- **Gamma API Explorer**: https://gamma-api.polymarket.com/docs
- **CLOB API Docs**: https://docs.polymarket.com/api-reference
- **Chainlink Oracles**: https://data.chain.link/

---

**Complete API reference** for all external integrations. Use this as your quick reference while developing or debugging!
