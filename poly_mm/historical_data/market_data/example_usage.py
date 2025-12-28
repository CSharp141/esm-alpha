#!/usr/bin/env python3
"""
Example: Using Historical Market Data

Demonstrates how to load and use downloaded historical market data
for backtesting, analysis, and strategy development.

This is a template you can modify for your own use cases.
"""

import json
from datetime import datetime, timezone
from typing import List, Dict


def load_historical_data(filepath: str) -> List[Dict]:
    """Load historical market data from JSON file."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    return data['markets']


def example_1_simple_backtest(markets: List[Dict]) -> None:
    """
    Example 1: Simple backtest - Always buy YES
    
    Tests what would happen if we always bought YES tokens
    at market open and held until close.
    """
    print("\n" + "="*80)
    print("EXAMPLE 1: Simple 'Always Buy YES' Backtest")
    print("="*80)
    
    # Filter only resolved markets with all needed data
    resolved = [m for m in markets 
                if m['status'] == 'resolved' 
                and m['winning_outcome']
                and m.get('yes_ask')]
    
    wins = 0
    losses = 0
    total_invested = 0.0
    total_returned = 0.0
    
    for market in resolved:
        # Buy YES at ask price
        entry_price = market['yes_ask']
        position_size = 100.0  # $100 per trade
        shares = position_size / entry_price
        
        total_invested += position_size
        
        # Check outcome
        if market['winning_outcome'] == 'YES':
            # Win: Each share pays $1
            payout = shares * 1.0
            total_returned += payout
            wins += 1
        else:
            # Loss: Shares expire worthless
            losses += 1
    
    profit = total_returned - total_invested
    roi = (profit / total_invested * 100) if total_invested > 0 else 0
    
    print(f"\nResults over {len(resolved)} markets:")
    print(f"  Wins:           {wins} ({100*wins/len(resolved):.1f}%)")
    print(f"  Losses:         {losses} ({100*losses/len(resolved):.1f}%)")
    print(f"  Total Invested: ${total_invested:,.2f}")
    print(f"  Total Returned: ${total_returned:,.2f}")
    print(f"  Profit/Loss:    ${profit:,.2f}")
    print(f"  ROI:            {roi:.2f}%")


def example_2_probability_based(markets: List[Dict]) -> None:
    """
    Example 2: Probability-based strategy
    
    Only trade when market is mispriced (implied probability != 50%).
    Buy YES when market thinks it's less than 50%, buy NO when more than 50%.
    """
    print("\n" + "="*80)
    print("EXAMPLE 2: Mean Reversion Strategy (50% baseline)")
    print("="*80)
    
    resolved = [m for m in markets 
                if m['status'] == 'resolved' 
                and m['winning_outcome']
                and m.get('yes_ask') and m.get('no_ask')]
    
    trades = 0
    wins = 0
    total_invested = 0.0
    total_returned = 0.0
    
    for market in resolved:
        yes_price = market['yes_ask']
        no_price = market['no_ask']
        
        # Only trade if there's significant mispricing (>5% from 50%)
        if yes_price < 0.45:
            # Market underpricing YES - buy YES
            position_size = 100.0
            shares = position_size / yes_price
            total_invested += position_size
            trades += 1
            
            if market['winning_outcome'] == 'YES':
                total_returned += shares * 1.0
                wins += 1
                
        elif no_price < 0.45:
            # Market underpricing NO - buy NO
            position_size = 100.0
            shares = position_size / no_price
            total_invested += position_size
            trades += 1
            
            if market['winning_outcome'] == 'NO':
                total_returned += shares * 1.0
                wins += 1
    
    if trades > 0:
        profit = total_returned - total_invested
        roi = (profit / total_invested * 100) if total_invested > 0 else 0
        win_rate = (wins / trades * 100) if trades > 0 else 0
        
        print("\nResults:")
        print(f"  Total Markets:  {len(resolved)}")
        print(f"  Trades Taken:   {trades} ({100*trades/len(resolved):.1f}% of markets)")
        print(f"  Wins:           {wins} ({win_rate:.1f}%)")
        print(f"  Losses:         {trades - wins}")
        print(f"  Total Invested: ${total_invested:,.2f}")
        print(f"  Total Returned: ${total_returned:,.2f}")
        print(f"  Profit/Loss:    ${profit:,.2f}")
        print(f"  ROI:            {roi:.2f}%")
    else:
        print("\nNo trades met the criteria.")


def example_3_time_analysis(markets: List[Dict]) -> None:
    """
    Example 3: Time-based analysis
    
    Analyze if certain times of day have higher win rates for YES or NO.
    """
    print("\n" + "="*80)
    print("EXAMPLE 3: Time of Day Analysis")
    print("="*80)
    
    resolved = [m for m in markets 
                if m['status'] == 'resolved' 
                and m['winning_outcome']]
    
    # Group by hour
    hourly_stats = {}
    for hour in range(24):
        hourly_stats[hour] = {'total': 0, 'yes_wins': 0, 'no_wins': 0}
    
    for market in resolved:
        dt = datetime.fromtimestamp(market['start_time'], tz=timezone.utc)
        hour = dt.hour
        
        hourly_stats[hour]['total'] += 1
        if market['winning_outcome'] == 'YES':
            hourly_stats[hour]['yes_wins'] += 1
        else:
            hourly_stats[hour]['no_wins'] += 1
    
    print("\nYES Win Rate by Hour (UTC):")
    print("Hour | Markets | YES Wins | Win Rate")
    print("-----|---------|----------|----------")
    
    for hour in range(24):
        stats = hourly_stats[hour]
        if stats['total'] > 0:
            yes_rate = stats['yes_wins'] / stats['total'] * 100
            print(f"{hour:2d}   | {stats['total']:7d} | {stats['yes_wins']:8d} | {yes_rate:6.1f}%")


def example_4_spread_analysis(markets: List[Dict]) -> None:
    """
    Example 4: Spread analysis
    
    Calculate average spreads and identify trading opportunities.
    """
    print("\n" + "="*80)
    print("EXAMPLE 4: Spread and Liquidity Analysis")
    print("="*80)
    
    with_books = [m for m in markets
                  if m.get('yes_bid') and m.get('yes_ask')
                  and m.get('no_bid') and m.get('no_ask')]
    
    if not with_books:
        print("\nNo markets with book data.")
        return
    
    # Calculate spreads
    spreads = []
    for market in with_books:
        yes_spread = market['yes_ask'] - market['yes_bid']
        no_spread = market['no_ask'] - market['no_bid']
        avg_spread = (yes_spread + no_spread) / 2
        spreads.append(avg_spread)
    
    avg_spread = sum(spreads) / len(spreads)
    
    print(f"\nSpread Statistics ({len(with_books)} markets):")
    print(f"  Average Spread:  {avg_spread:.4f} ({100*avg_spread:.2f}%)")
    print(f"  Median Spread:   {sorted(spreads)[len(spreads)//2]:.4f}")
    print(f"  Min Spread:      {min(spreads):.4f} ({100*min(spreads):.2f}%)")
    print(f"  Max Spread:      {max(spreads):.4f} ({100*max(spreads):.2f}%)")
    
    # Find markets with tight spreads (potential high liquidity)
    tight_spread_threshold = 0.02  # 2%
    tight_spreads = [s for s in spreads if s < tight_spread_threshold]
    
    print(f"\nMarkets with tight spreads (<{100*tight_spread_threshold:.0f}%):")
    print(f"  Count:  {len(tight_spreads)} ({100*len(tight_spreads)/len(spreads):.1f}%)")


def main():
    """Main entry point."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python example_usage.py <historical_data.json>")
        print("\nExample:")
        print("  python example_usage.py historical_btc_30d.json")
        sys.exit(1)
    
    filepath = sys.argv[1]
    
    print("="*80)
    print("HISTORICAL MARKET DATA - USAGE EXAMPLES")
    print("="*80)
    print(f"\nLoading data from: {filepath}")
    
    markets = load_historical_data(filepath)
    print(f"Loaded {len(markets)} markets")
    
    # Run examples
    example_1_simple_backtest(markets)
    example_2_probability_based(markets)
    example_3_time_analysis(markets)
    example_4_spread_analysis(markets)
    
    print("\n" + "="*80)
    print("Examples complete!")
    print("="*80)
    print("\nNext steps:")
    print("  1. Modify these examples for your own strategies")
    print("  2. Add more sophisticated pricing models")
    print("  3. Incorporate volatility and Black-Scholes pricing")
    print("  4. Test with different position sizing strategies")
    print("")


if __name__ == "__main__":
    main()
