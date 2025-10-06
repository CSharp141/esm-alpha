# Cryptocurrency Pair Cointegration Analysis

This repository contains tools for analyzing cointegration relationships between cryptocurrency trading pairs using statistical methods. The project includes data fetching capabilities from multiple exchanges and comprehensive analysis tools for identifying statistically significant price relationships.

## 📁 Project Structure

```
pair_cointegration/
├── README.md                    # This file
├── csv_data_analysis.py         # Main cointegration analysis tool
├── api_analysis.py              # Legacy Kraken API analysis
├── axiom_data/                  # Hyperliquid data directory
│   ├── fetch_hl_candles.py     # Hyperliquid data fetcher
│   ├── tickers.txt             # List of cryptocurrency symbols
│   ├── data_5m/                # 5-minute candle data
│   ├── data_15m/               # 15-minute candle data
│   ├── data_1h/                # 1-hour candle data
│   ├── data_4h/                # 4-hour candle data
│   └── data_1d/                # 1-day candle data
└── .vscode/                    # VS Code configuration
```

## 🚀 Quick Start

### Prerequisites

```bash
pip install pandas numpy statsmodels requests argparse
```

### Basic Usage

1. **Fetch Latest Data** (optional, if data not already present):
```bash
cd axiom_data
python fetch_hl_candles.py --tickers-file tickers.txt --timeframe 1h --lookback 30d
```

2. **Run Cointegration Analysis**:
```bash
python csv_data_analysis.py
```

3. **Custom Analysis**:
```bash
# Use 1-hour timeframe with ETH as base asset
python csv_data_analysis.py --timeframe 1h --base-asset ETH

# Test with limited pairs
python csv_data_analysis.py --max-pairs 10

# Use custom data directory
python csv_data_analysis.py --data-dir /path/to/custom/data
```

## 📊 Available Tools

### 1. Primary Analysis Tool: `csv_data_analysis.py`

The main analysis engine for cointegration testing.

**Command Line Options:**
- `--timeframe`: Choose timeframe (5m, 15m, 1h, 4h, 1d) [default: 5m]
- `--base-asset`: Base asset for comparison [default: BTC]
- `--data-dir`: Data directory path [default: axiom_data]
- `--max-pairs`: Limit number of pairs for testing

**Example Output:**
```
================================================================================
ANALYSIS RESULTS
================================================================================

Valid results for 177 pairs out of 177 total pairs

------------------------------------------------------------
TOP 10 BY LOWEST SCORE (strongest cointegration)
------------------------------------------------------------
 1. AAVE         | Score:    -3.4063 | P-value: 4.165e-02 | n=5021
 2. ACE          | Score:    -3.0781 | P-value: 9.278e-02 | n=5004
 ...

Pairs with statistically significant cointegration (p < 0.05): 1
  AAVE         | P-value: 4.165e-02 | Score:    -3.4063 | n=5021
```

### 2. Data Fetcher: `fetch_hl_candles.py`

Advanced Hyperliquid API client with rate limiting and robust error handling.

**Features:**
- Respects API rate limits (1200 weight/minute)
- Automatic retry logic
- Multiple output formats
- Flexible time range specification

**Usage Examples:**
```bash
# Fetch specific tickers
python fetch_hl_candles.py --tickers BTC,ETH,SOL --timeframe 1h --lookback 90d

# Fetch from file
python fetch_hl_candles.py --tickers-file tickers.txt --timeframe 5m --lookback 48h

# Specific date range
python fetch_hl_candles.py --tickers-file tickers.txt --timeframe 1d --start 2024-01-01
```

### 3. Legacy Tool: `api_analysis.py`

Original Kraken API analysis tool (maintained for compatibility).

## 📈 Data Format

### CSV Structure
Each candle file contains OHLCV data with the following columns:
```
symbol,time,t,open,high,low,close,volume,interval
BTC,2025-09-19T08:00:00+00:00,1758268800000,116957.0,116977.0,116926.0,116937.0,10.70726,5m
```

### Directory Organization
```
axiom_data/
├── data_5m/
│   ├── candles_BTC_5m.csv
│   ├── candles_ETH_5m.csv
│   └── ...
├── data_1h/
│   ├── candles_BTC_1h.csv
│   └── ...
```

## 🔬 Statistical Methodology

### Engle-Granger Cointegration Test

The analysis uses the Engle-Granger two-step method:

1. **Step 1**: Test for unit roots in individual time series
2. **Step 2**: Test for cointegration using residuals from cointegrating regression

**Interpretation:**
- **Score**: Test statistic (more negative = stronger cointegration)
- **P-value**: Statistical significance (< 0.05 = significant at 95% confidence)
- **Critical Values**: Standard thresholds for different confidence levels

### Quality Gates

The analysis includes several quality checks:
- **Minimum Data Points**: Ensures sufficient observations
- **Unique Values**: Filters out flat/illiquid series
- **Standard Deviation**: Removes series with insufficient variance

## 📊 Understanding Results

### Result Categories

1. **Strongest Cointegration** (Lowest Scores):
   - Most negative test statistics
   - Indicates strongest long-term relationships

2. **Most Significant** (Lowest P-values):
   - Highest statistical confidence
   - P-value < 0.05 = statistically significant

3. **Overlap**: Pairs appearing in both top lists are particularly noteworthy

### Practical Applications

**Strong Cointegration (p < 0.05)**:
- Suitable for pairs trading strategies
- Reliable mean reversion opportunities
- Lower risk spread trades

**Moderate Cointegration (0.05 < p < 0.15)**:
- Potential trading opportunities
- Requires additional confirmation
- Higher risk but potentially higher reward

## ⚙️ Configuration

### Supported Timeframes
- `5m`: 5-minute candles
- `15m`: 15-minute candles  
- `1h`: 1-hour candles
- `4h`: 4-hour candles
- `1d`: 1-day candles

### Base Assets
Any available cryptocurrency can be used as a base asset:
- `BTC`: Bitcoin (default)
- `ETH`: Ethereum
- `SOL`: Solana
- And 170+ other supported tokens

### Rate Limiting

The data fetcher implements sophisticated rate limiting:
- Maximum 960 requests/minute (80% of API limit for safety)
- Dynamic weight calculation based on data returned
- Automatic backoff when approaching limits

## 🛠️ Advanced Usage

### Custom Ticker Lists

Edit `axiom_data/tickers.txt` to customize which assets to fetch:
```
BTC
ETH
SOL
AAVE
UNI
```

### Batch Analysis

```bash
# Analyze multiple timeframes
for tf in 5m 1h 4h 1d; do
    python csv_data_analysis.py --timeframe $tf --base-asset BTC > results_${tf}_BTC.txt
done

# Compare different base assets
for base in BTC ETH SOL; do
    python csv_data_analysis.py --base-asset $base > results_1h_${base}.txt
done
```

### Data Management

```bash
# Fetch comprehensive dataset
python fetch_hl_candles.py --tickers-file tickers.txt --timeframe 1h --lookback 365d --outdir data_1h

# Update existing data
python fetch_hl_candles.py --tickers-file tickers.txt --timeframe 5m --lookback 7d --outdir data_5m
```

## 🐛 Troubleshooting

### Common Issues

1. **No Data Found**:
   - Check that data files exist in the expected directory
   - Verify ticker symbols are correct
   - Ensure sufficient historical data

2. **API Rate Limits**:
   - Use built-in rate limiting (`--sleep` parameter)
   - Reduce batch sizes for large ticker lists
   - Check API status and quotas

3. **Memory Issues**:
   - Use `--max-pairs` to limit analysis scope
   - Close other applications to free memory
   - Consider analyzing in smaller batches

### Debug Mode

Enable verbose output:
```bash
python fetch_hl_candles.py --verbose-rate-limit --tickers BTC,ETH --timeframe 1h --lookback 24h
```