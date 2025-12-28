#!/usr/bin/env python3
"""
Analyze Historical Market Data

Quick analysis script for downloaded historical Polymarket 15-minute markets.
Generates statistics, charts, and insights from historical data.

Usage:
    python analyze_historical_data.py historical_btc_30d.json
"""

import json
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Any
from collections import defaultdict


def load_data(filepath: str) -> Dict[str, Any]:
    """Load historical market data from JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)


def analyze_market_distribution(markets: List[Dict]) -> None:
    """Analyze market distribution by time."""
    print("\n" + "="*80)
    print("MARKET DISTRIBUTION ANALYSIS")
    print("="*80)
    
    # By hour of day
    hourly_counts = defaultdict(int)
    hourly_volumes = defaultdict(float)
    
    for market in markets:
        dt = datetime.fromtimestamp(market['start_time'], tz=timezone.utc)
        hour = dt.hour
        hourly_counts[hour] += 1
        if market.get('volume'):
            hourly_volumes[hour] += market['volume']
    
    print("\nMarkets by Hour (UTC):")
    print("Hour | Count | Avg Volume")
    print("-----|-------|------------")
    for hour in sorted(hourly_counts.keys()):
        count = hourly_counts[hour]
        avg_vol = hourly_volumes[hour] / count if count > 0 else 0
        print(f"{hour:2d}   | {count:5d} | ${avg_vol:,.2f}")
    
    # By day of week
    dow_counts = defaultdict(int)
    dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    for market in markets:
        dt = datetime.fromtimestamp(market['start_time'], tz=timezone.utc)
        dow = dt.weekday()
        dow_counts[dow] += 1
    
    print("\nMarkets by Day of Week:")
    print("Day    | Count")
    print("-------|------")
    for dow in range(7):
        print(f"{dow_names[dow]:6s} | {dow_counts[dow]:5d}")


def analyze_outcomes(markets: List[Dict]) -> None:
    """Analyze market outcomes and win rates."""
    print("\n" + "="*80)
    print("OUTCOME ANALYSIS")
    print("="*80)
    
    resolved = [m for m in markets if m.get('winning_outcome')]
    
    if not resolved:
        print("\nNo resolved markets found.")
        return
    
    yes_wins = sum(1 for m in resolved if m['winning_outcome'] == 'YES')
    no_wins = sum(1 for m in resolved if m['winning_outcome'] == 'NO')
    
    print(f"\nTotal Resolved: {len(resolved)}")
    print(f"YES Wins:       {yes_wins} ({100*yes_wins/len(resolved):.1f}%)")
    print(f"NO Wins:        {no_wins} ({100*no_wins/len(resolved):.1f}%)")
    
    # Win rate by strike price ranges
    strike_markets = [m for m in resolved if m.get('strike_price')]
    if strike_markets:
        strikes = [m['strike_price'] for m in strike_markets]
        min_strike = min(strikes)
        max_strike = max(strikes)
        
        print("\nStrike Price Range:")
        print(f"  Min: ${min_strike:,.2f}")
        print(f"  Max: ${max_strike:,.2f}")
        print(f"  Avg: ${sum(strikes)/len(strikes):,.2f}")


def analyze_pricing(markets: List[Dict]) -> None:
    """Analyze market pricing and spreads."""
    print("\n" + "="*80)
    print("PRICING ANALYSIS")
    print("="*80)
    
    # Filter markets with book data
    with_books = [m for m in markets 
                  if m.get('yes_bid') and m.get('yes_ask') and 
                     m.get('no_bid') and m.get('no_ask')]
    
    if not with_books:
        print("\nNo markets with book data found.")
        return
    
    print(f"\nMarkets with Book Data: {len(with_books)}")
    
    # Calculate spreads
    yes_spreads = [(m['yes_ask'] - m['yes_bid']) for m in with_books]
    no_spreads = [(m['no_ask'] - m['no_bid']) for m in with_books]
    
    print("\nYES Token Spreads:")
    print(f"  Min:  {min(yes_spreads):.4f} ({100*min(yes_spreads):.2f}%)")
    print(f"  Max:  {max(yes_spreads):.4f} ({100*max(yes_spreads):.2f}%)")
    print(f"  Avg:  {sum(yes_spreads)/len(yes_spreads):.4f} ({100*sum(yes_spreads)/len(yes_spreads):.2f}%)")
    
    print("\nNO Token Spreads:")
    print(f"  Min:  {min(no_spreads):.4f} ({100*min(no_spreads):.2f}%)")
    print(f"  Max:  {max(no_spreads):.4f} ({100*max(no_spreads):.2f}%)")
    print(f"  Avg:  {sum(no_spreads)/len(no_spreads):.4f} ({100*sum(no_spreads)/len(no_spreads):.2f}%)")
    
    # Probability analysis
    yes_mids = [(m['yes_bid'] + m['yes_ask']) / 2 for m in with_books]
    
    print("\nImplied Probabilities (YES mid):")
    print(f"  Min:  {min(yes_mids):.4f} ({100*min(yes_mids):.1f}%)")
    print(f"  Max:  {max(yes_mids):.4f} ({100*max(yes_mids):.1f}%)")
    print(f"  Avg:  {sum(yes_mids)/len(yes_mids):.4f} ({100*sum(yes_mids)/len(yes_mids):.1f}%)")


def analyze_volume(markets: List[Dict]) -> None:
    """Analyze trading volume."""
    print("\n" + "="*80)
    print("VOLUME ANALYSIS")
    print("="*80)
    
    with_volume = [m for m in markets if m.get('volume') and m['volume'] > 0]
    
    if not with_volume:
        print("\nNo volume data found.")
        return
    
    volumes = [m['volume'] for m in with_volume]
    total_volume = sum(volumes)
    
    print(f"\nMarkets with Volume: {len(with_volume)}")
    print(f"Total Volume:        ${total_volume:,.2f}")
    print(f"Average per Market:  ${sum(volumes)/len(volumes):,.2f}")
    print(f"Median per Market:   ${sorted(volumes)[len(volumes)//2]:,.2f}")
    print(f"Min:                 ${min(volumes):,.2f}")
    print(f"Max:                 ${max(volumes):,.2f}")
    
    # Top 10 by volume
    sorted_markets = sorted(with_volume, key=lambda m: m['volume'], reverse=True)[:10]
    print("\nTop 10 Markets by Volume:")
    print("-" * 80)
    for i, m in enumerate(sorted_markets, 1):
        dt = datetime.fromtimestamp(m['start_time'], tz=timezone.utc)
        print(f"{i:2d}. ${m['volume']:>10,.2f} | {dt.strftime('%Y-%m-%d %H:%M')} | {m['question'][:50]}")


def generate_summary_stats(data: Dict[str, Any]) -> None:
    """Generate overall summary statistics."""
    markets = data['markets']
    
    print("\n" + "="*80)
    print("SUMMARY STATISTICS")
    print("="*80)
    
    print(f"\nDownload Date:    {data['download_date']}")
    print(f"Total Markets:    {len(markets)}")
    
    # Status breakdown
    statuses = defaultdict(int)
    for m in markets:
        statuses[m['status']] += 1
    
    print("\nBy Status:")
    for status, count in sorted(statuses.items()):
        print(f"  {status.capitalize():10s}: {count:5d} ({100*count/len(markets):.1f}%)")
    
    # Data completeness
    with_strike = sum(1 for m in markets if m.get('strike_price'))
    with_books = sum(1 for m in markets if m.get('yes_bid'))
    with_volume = sum(1 for m in markets if m.get('volume') and m['volume'] > 0)
    resolved = sum(1 for m in markets if m.get('winning_outcome'))
    
    print("\nData Completeness:")
    print(f"  Strike Prices:    {with_strike:5d} ({100*with_strike/len(markets):.1f}%)")
    print(f"  Order Books:      {with_books:5d} ({100*with_books/len(markets):.1f}%)")
    print(f"  Volume Data:      {with_volume:5d} ({100*with_volume/len(markets):.1f}%)")
    print(f"  Resolved:         {resolved:5d} ({100*resolved/len(markets):.1f}%)")
    
    # Date range
    if markets:
        start_times = [m['start_time'] for m in markets]
        start_date = datetime.fromtimestamp(min(start_times), tz=timezone.utc)
        end_date = datetime.fromtimestamp(max(start_times), tz=timezone.utc)
        duration_days = (end_date - start_date).days
        
        print("\nDate Range:")
        print(f"  First Market: {start_date.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"  Last Market:  {end_date.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"  Duration:     {duration_days} days")
        print(f"  Markets/Day:  {len(markets)/max(1, duration_days):.1f}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze historical Polymarket market data"
    )
    parser.add_argument(
        "file",
        type=str,
        help="Path to historical data JSON file"
    )
    parser.add_argument(
        "--section",
        type=str,
        choices=["all", "summary", "distribution", "outcomes", "pricing", "volume"],
        default="all",
        help="Which analysis section to run (default: all)"
    )
    
    args = parser.parse_args()
    
    print("="*80)
    print("HISTORICAL MARKET DATA ANALYSIS")
    print("="*80)
    print(f"\nFile: {args.file}")
    
    # Load data
    print("\nLoading data...")
    data = load_data(args.file)
    markets = data['markets']
    print(f"Loaded {len(markets)} markets")
    
    # Run analyses
    if args.section in ["all", "summary"]:
        generate_summary_stats(data)
    
    if args.section in ["all", "distribution"]:
        analyze_market_distribution(markets)
    
    if args.section in ["all", "outcomes"]:
        analyze_outcomes(markets)
    
    if args.section in ["all", "pricing"]:
        analyze_pricing(markets)
    
    if args.section in ["all", "volume"]:
        analyze_volume(markets)
    
    print("\n" + "="*80)
    print("Analysis complete!")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
