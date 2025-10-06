import pandas as pd
from statsmodels.tsa.stattools import coint

import requests


API_URL = 'https://api.kraken.com/0/public/'
SECONDS_IN_YEAR = 31536000
BASE_PAIR = 'SOLUSD'

def get_unix_timestamp(years_ago=1):
    return int((pd.Timestamp.now() - pd.DateOffset(years=years_ago)).timestamp())

def get_trading_pairs():
    r = requests.get(f"{API_URL}AssetPairs")
    r.raise_for_status()
    pairs = sorted({
        v.get("wsname").replace("/", "")   # remove the slash
        for v in r.json()["result"].values()
        if v.get("wsname")
    })
    return pairs

def fetch_ohlc_data(pair, since, interval=1):
    end_point = f"{API_URL}OHLC"
    params = {
        'pair': pair,
        'interval': interval,
        'since': since
    }
    response = requests.get(end_point, params=params)
    data = response.json()
    if data['error']:
        raise Exception(f"API Error: {data['error']}")
    data = data['result']
    data.pop('last', None)
    return data

def get_pair_data(asset_to_check, base_asset_data, since, interval=1):
    ohlc_data = fetch_ohlc_data(asset_to_check, since, interval)
    _, candles = next(iter(ohlc_data.items()))
    check_df = pd.DataFrame(candles, columns=['time', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'])

    merged = pd.merge(
        check_df[['time', 'vwap']], 
        base_asset_data[['time', 'vwap']], 
        on='time', 
        how='inner',   # only keep times that exist in both
        suffixes=(f'_{asset_to_check}', '_SOLUSD')
    )

    return merged


def perform_engle_granger_causality_test(df):
    x = df.iloc[:, 1]
    y = df.iloc[:, 2]

    if df.empty:
        return {'score': None, 'pvalue': None, 'timeframe': None}
    
    # Calculate timeframe information
    if len(df) >= 2:
        start_time = pd.to_datetime(df['time'].iloc[0], unit='s')
        end_time = pd.to_datetime(df['time'].iloc[-1], unit='s')
        timeframe = f"{start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')} ({len(df)} data points)"
        print(f"  Timeframe: {timeframe}")
    else:
        timeframe = f"Insufficient data ({len(df)} points)"
        print(f"  Timeframe: {timeframe}")
    
    score, pvalue, _ = coint(y, x)
    return {'score': score, 'pvalue': pvalue, 'timeframe': timeframe}


def main():
    print("Available trading pairs:")
    pairs = get_trading_pairs()
    cleaned_pairs = []
    for p in pairs:
        if p.endswith('USD') and 'SOL' not in p and not p.startswith('USD'):
            cleaned_pairs.append(p)
    
    print(f"Found {len(cleaned_pairs)} pairs to analyze")
    
    since = get_unix_timestamp()
    ohlc_data = fetch_ohlc_data(BASE_PAIR, since, 1440)
    _, candles = next(iter(ohlc_data.items()))
    base_asset_df = pd.DataFrame(candles, columns=['time', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'])
    
    results = {}
    
    for i, p in enumerate(cleaned_pairs, 1):
        print(f"Processing pair {i}/{len(cleaned_pairs)}: {p}")
        try:
            data = get_pair_data(p, base_asset_df, since, 1440)
            result = perform_engle_granger_causality_test(data)
            results[p] = result
        except Exception as e:
            print(f"  Error processing {p}: {e}")
            results[p] = {'score': None, 'pvalue': None, 'timeframe': 'Error'}

    print("\n" + "="*80)
    print("ANALYSIS RESULTS")
    print("="*80)
    
    # Filter out pairs with valid results
    valid_results = {k: v for k, v in results.items() if v['score'] is not None and v['pvalue'] is not None}
    
    if not valid_results:
        print("No valid results found!")
        return
    
    print(f"\nValid results for {len(valid_results)} pairs out of {len(results)} total pairs")
    
    # Sort by score (lowest first - more negative indicates stronger cointegration)
    sorted_by_score = sorted(valid_results.items(), key=lambda x: x[1]['score'])
    
    # Sort by p-value (lowest first - lower p-value indicates stronger significance)
    sorted_by_pvalue = sorted(valid_results.items(), key=lambda x: x[1]['pvalue'])
    
    print("\n" + "-"*60)
    print("TOP 10 PAIRS WITH LOWEST SCORES (Strongest Cointegration)")
    print("-"*60)
    for i, (pair, result) in enumerate(sorted_by_score[:10], 1):
        print(f"{i:2d}. {pair:12s} | Score: {result['score']:8.4f} | P-value: {result['pvalue']:8.4f}")
    
    print("\n" + "-"*60)
    print("TOP 10 PAIRS WITH LOWEST P-VALUES (Most Significant)")
    print("-"*60)
    for i, (pair, result) in enumerate(sorted_by_pvalue[:10], 1):
        print(f"{i:2d}. {pair:12s} | P-value: {result['pvalue']:8.4f} | Score: {result['score']:8.4f}")
    
    # Find pairs that appear in both top 10 lists
    top_score_pairs = set([pair for pair, _ in sorted_by_score[:10]])
    top_pvalue_pairs = set([pair for pair, _ in sorted_by_pvalue[:10]])
    common_pairs = top_score_pairs & top_pvalue_pairs
    
    if common_pairs:
        print("\n" + "-"*60)
        print("PAIRS IN BOTH TOP 10 LISTS (Best Overall)")
        print("-"*60)
        for pair in sorted(common_pairs):
            result = results[pair]
            print(f"{pair:12s} | Score: {result['score']:8.4f} | P-value: {result['pvalue']:8.4f}")
    
    # Show the single best pair by each metric
    best_score_pair = sorted_by_score[0]
    best_pvalue_pair = sorted_by_pvalue[0]
    
    print("\n" + "-"*60)
    print("BEST INDIVIDUAL RESULTS")
    print("-"*60)
    print(f"Lowest Score:  {best_score_pair[0]} (Score: {best_score_pair[1]['score']:.6f})")
    print(f"Lowest P-val:  {best_pvalue_pair[0]} (P-value: {best_pvalue_pair[1]['pvalue']:.6f})")
    
    # Statistical significance threshold
    significant_pairs = [(k, v) for k, v in valid_results.items() if v['pvalue'] < 0.05]
    print(f"\nPairs with statistically significant cointegration (p < 0.05): {len(significant_pairs)}")
    if significant_pairs:
        print("Significant pairs:")
        for pair, result in sorted(significant_pairs, key=lambda x: x[1]['pvalue'])[:5]:
            print(f"  {pair:12s} | P-value: {result['pvalue']:.6f} | Score: {result['score']:.4f}")

    print("\n" + "="*80)


if __name__ == "__main__":
    main()