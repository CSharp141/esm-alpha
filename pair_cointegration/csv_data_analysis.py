import os
import math
import gc
import re
import argparse
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

# Updated configuration for axiom_data structure
BASEFOLDER = 'axiom_data'
TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d']  # Available timeframes
DEFAULT_TIMEFRAME = '5m'
BASE_ASSET = 'BTC'  # Changed from SOLUSD to BTC as it's more commonly available

# ---------------- Discovery ----------------
def get_available_timeframes():
    """Get all available timeframe directories"""
    timeframes = []
    for item in os.listdir(BASEFOLDER):
        if os.path.isdir(os.path.join(BASEFOLDER, item)) and item.startswith('data_'):
            tf = item.replace('data_', '')
            timeframes.append(tf)
    return sorted(timeframes)

def get_all_pairs(timeframe=DEFAULT_TIMEFRAME):
    """Get all available trading pairs for a given timeframe"""
    data_dir = os.path.join(BASEFOLDER, f'data_{timeframe}')
    if not os.path.isdir(data_dir):
        print(f"Directory {data_dir} not found!")
        return []
    
    pairs = set()
    for filename in os.listdir(data_dir):
        if filename.startswith('candles_') and filename.endswith(f'_{timeframe}.csv'):
            # Extract symbol: candles_BTC_5m.csv -> BTC
            symbol = filename.replace('candles_', '').replace(f'_{timeframe}.csv', '')
            pairs.add(symbol)
    
    return sorted(pairs)

# ---------------- IO ----------------
def _read_one_csv(file_path):
    """Read a CSV file with headers from axiom_data format"""
    return pd.read_csv(
        file_path,
        usecols=['time', 'close'],
        parse_dates=['time'],
        dtype={'close': 'float64'}
    )

def get_pair_data_from_csv(symbol, timeframe=DEFAULT_TIMEFRAME):
    """Get data for a single pair from axiom_data structure"""
    data_dir = os.path.join(BASEFOLDER, f'data_{timeframe}')
    file_path = os.path.join(data_dir, f'candles_{symbol}_{timeframe}.csv')
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return pd.DataFrame(columns=['time', 'close'])
    
    try:
        data = _read_one_csv(file_path)
        # Rename close column to include symbol
        data = data.rename(columns={'close': f'close_{symbol}'})
        # Sort by time and remove duplicates
        data.sort_values('time', inplace=True)
        data.drop_duplicates(subset=['time'], keep='last', inplace=True)
        data.reset_index(drop=True, inplace=True)
        return data
    except Exception as e:
        print(f"Read error {file_path}: {e}")
        return pd.DataFrame(columns=['time', f'close_{symbol}'])

# ---------------- Merge ----------------
def get_pair_data(asset_to_check, base_asset_data, timeframe=DEFAULT_TIMEFRAME):
    """Merge asset data with base asset data"""
    asset_data = get_pair_data_from_csv(asset_to_check, timeframe)
    if asset_data.empty or base_asset_data.empty:
        return pd.DataFrame()

    merged = pd.merge(
        asset_data,
        base_asset_data,
        on='time',
        how='inner'
    )
    # Drop any rows with NaNs just in case
    merged.dropna(inplace=True)
    return merged

# ---------------- Quality gates ----------------
def _series_quality_ok(a: pd.Series, min_std=1e-6, min_unique=10):
    if len(a) < min_unique:
        return False
    # unique values gate (protects illiquid/flat series)
    if a.nunique(dropna=True) < min_unique:
        return False
    # std gate
    # Convert to float64 for stable std calc
    if float(np.std(a.astype('float64'))) < min_std:
        return False
    return True

# ---------------- Analysis ----------------
def perform_engle_granger_causality_test(df):
    n = len(df)
    if df.empty:
        return {'score': None, 'pvalue': None, 'timeframe': None, 'n': n}

    start_time, end_time = df['time'].iloc[0], df['time'].iloc[-1]
    timeframe = f"{start_time:%Y-%m-%d %H:%M} to {end_time:%Y-%m-%d %H:%M} ({n} pts)"

    # Find the close price columns
    close_cols = [c for c in df.columns if c.startswith('close_')]
    if len(close_cols) != 2:
        return {'score': None, 'pvalue': None, 'timeframe': timeframe, 'n': n}

    # Check data quality for both series
    for col in close_cols:
        if not _series_quality_ok(df[col]):
            return {'score': None, 'pvalue': None, 'timeframe': timeframe, 'n': n}

    y = df[close_cols[0]].astype('float64')
    x = df[close_cols[1]].astype('float64')
    
    try:
        score, pvalue, _ = coint(y, x)
        return {'score': float(score), 'pvalue': float(pvalue), 'timeframe': timeframe, 'n': n}
    except Exception as e:
        print(f"Cointegration test failed: {e}")
        return {'score': None, 'pvalue': None, 'timeframe': timeframe, 'n': n}


# ---------------- Reporting ----------------
def display_analysis_results(results):
    print("\n" + "="*80)
    print("ANALYSIS RESULTS")
    print("="*80)

    valid = {k: v for k, v in results.items() if v['score'] is not None and v['pvalue'] is not None}
    if not valid:
        print("No valid results found!")
        return

    print(f"\nValid results for {len(valid)} pairs out of {len(results)} total pairs")

    sorted_by_score = sorted(valid.items(), key=lambda x: x[1]['score'])
    sorted_by_pvalue = sorted(valid.items(), key=lambda x: x[1]['pvalue'])

    print("\n" + "-"*60)
    print("TOP 10 BY LOWEST SCORE (strongest cointegration)")
    print("-"*60)
    for i, (pair, r) in enumerate(sorted_by_score[:10], 1):
        print(f"{i:2d}. {pair:12s} | Score: {r['score']:>10.4f} | P-value: {r['pvalue']:.3e} | n={r.get('n','?')}")

    print("\n" + "-"*60)
    print("TOP 10 BY LOWEST P-VALUE (most significant)")
    print("-"*60)
    for i, (pair, r) in enumerate(sorted_by_pvalue[:10], 1):
        print(f"{i:2d}. {pair:12s} | P-value: {r['pvalue']:.3e} | Score: {r['score']:>10.4f} | n={r.get('n','?')}")

    overlap = set(dict(sorted_by_score[:10]).keys()) & set(dict(sorted_by_pvalue[:10]).keys())
    if overlap:
        print("\n" + "-"*60)
        print("IN BOTH TOP 10 LISTS")
        print("-"*60)
        for pair in sorted(overlap):
            r = valid[pair]
            print(f"{pair:12s} | Score: {r['score']:>10.4f} | P-value: {r['pvalue']:.3e} | n={r.get('n','?')}")

    best_score_pair = sorted_by_score[0]
    best_pvalue_pair = sorted_by_pvalue[0]
    print("\n" + "-"*60)
    print("BEST INDIVIDUAL RESULTS")
    print("-"*60)
    print(f"Lowest Score:  {best_score_pair[0]} (Score: {best_score_pair[1]['score']:.6f}, n={best_score_pair[1].get('n','?')})")
    print(f"Lowest P-val:  {best_pvalue_pair[0]} (P-value: {best_pvalue_pair[1]['pvalue']:.3e}, n={best_pvalue_pair[1].get('n','?')})")

    significant = [(k, v) for k, v in valid.items() if v['pvalue'] < 0.05]
    print(f"\nPairs with statistically significant cointegration (p < 0.05): {len(significant)}")
    for pair, r in sorted(significant, key=lambda x: x[1]['pvalue'])[:5]:
        print(f"  {pair:12s} | P-value: {r['pvalue']:.3e} | Score: {r['score']:>10.4f} | n={r.get('n','?')}")

    print("\n" + "="*80)


# ---------------- Main ----------------
def parse_args():
    parser = argparse.ArgumentParser(description="Perform cointegration analysis on cryptocurrency pairs")
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, 
                       help=f"Timeframe to analyze (default: {DEFAULT_TIMEFRAME})")
    parser.add_argument("--base-asset", default=BASE_ASSET,
                       help=f"Base asset for comparison (default: {BASE_ASSET})")
    parser.add_argument("--data-dir", default=BASEFOLDER,
                       help=f"Data directory (default: {BASEFOLDER})")
    parser.add_argument("--max-pairs", type=int,
                       help="Maximum number of pairs to analyze (for testing)")
    return parser.parse_args()

def main():
    args = parse_args()
    
    # Update global variables based on command line arguments
    global BASEFOLDER, BASE_ASSET
    BASEFOLDER = args.data_dir
    base_asset = args.base_asset
    timeframe = args.timeframe
    
    print(f"Analyzing data from: {BASEFOLDER}")
    
    # Check available timeframes
    available_timeframes = get_available_timeframes()
    print(f"Available timeframes: {available_timeframes}")
    
    if timeframe not in available_timeframes:
        print(f"Timeframe {timeframe} not available. Using {available_timeframes[0]}")
        timeframe = available_timeframes[0]
    
    print(f"Using timeframe: {timeframe}")

    print("Collecting pairs from CSV files...")
    pairs = get_all_pairs(timeframe)
    print(f"Found {len(pairs)} pairs to analyze")
    
    if base_asset not in pairs:
        print(f"Base asset {base_asset} not found in available pairs!")
        print(f"Available pairs: {pairs[:10]}...")
        return

    print(f"Loading {base_asset} base data...")
    base_df = get_pair_data_from_csv(base_asset, timeframe)
    if base_df.empty:
        print(f"No {base_asset} data found; aborting.")
        return
    
    print(f"Base asset data: {len(base_df)} rows from {base_df['time'].min()} to {base_df['time'].max()}")

    # Remove base asset from pairs to analyze
    pairs_to_analyze = [p for p in pairs if p != base_asset]
    
    # Limit pairs if specified
    if args.max_pairs and args.max_pairs < len(pairs_to_analyze):
        pairs_to_analyze = pairs_to_analyze[:args.max_pairs]
        print(f"Limited to first {args.max_pairs} pairs for testing")
    
    results = {}
    print(f"Starting analysis of {len(pairs_to_analyze)} pairs against {base_asset}...")
    for i, pair in enumerate(pairs_to_analyze, 1):
        df = get_pair_data(pair, base_df, timeframe)
        res = perform_engle_granger_causality_test(df)
        results[pair] = res
        del df
        gc.collect()

    display_analysis_results(results)

if __name__ == "__main__":
    main()
