#!/usr/bin/env python3
"""
Quick log analysis tool for Polymarket Market Maker performance logs.

Provides fast insights into trading session performance:
- Tick rate and data quality
- Market coverage
- Trading decisions summary
- Edge distribution
- Performance metrics

Usage:
    python analyze_logs.py logs/20241228_103203
"""

import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from typing import Dict, List, Any


def load_jsonl(filepath: Path) -> List[Dict[str, Any]]:
    """Load a JSONL file into a list of dicts."""
    if not filepath.exists():
        return []
    
    data = []
    with open(filepath) as f:
        for line in f:
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return data


def analyze_session(session_dir: Path):
    """Analyze a trading session."""
    print("=" * 80)
    print(f"SESSION ANALYSIS: {session_dir.name}")
    print("=" * 80)
    
    # Load all log files
    price_ticks = load_jsonl(session_dir / "price_ticks.jsonl")
    markets = load_jsonl(session_dir / "markets.jsonl")
    orderbooks = load_jsonl(session_dir / "orderbooks.jsonl")
    calculations = load_jsonl(session_dir / "calculations.jsonl")
    decisions = load_jsonl(session_dir / "decisions.jsonl")
    trades = load_jsonl(session_dir / "trades.jsonl")
    performance = load_jsonl(session_dir / "performance.jsonl")
    events = load_jsonl(session_dir / "events.jsonl")
    
    # Session info
    print("\n📊 SESSION INFO")
    print("-" * 80)
    
    session_start = None
    session_end = None
    for event in events:
        if event.get('event_type') == 'session_start':
            session_start = event.get('start_time')
            print(f"Start time: {event.get('start_time_iso', 'N/A')}")
        elif event.get('event_type') == 'session_end':
            session_end = event.get('timestamp')
            print(f"End time: {event.get('timestamp_iso', 'N/A')}")
            print(f"Duration: {event.get('duration_seconds', 0):.1f} seconds")
            print(f"Total ticks: {event.get('total_ticks', 0)}")
            print(f"Total quotes: {event.get('total_quotes', 0)}")
            print(f"Avg tick rate: {event.get('avg_ticks_per_second', 0):.2f} ticks/sec")
    
    # If session didn't close cleanly, estimate duration
    if session_start and not session_end and price_ticks:
        session_end = price_ticks[-1]['timestamp']
        duration = session_end - session_start
        print(f"Duration (estimated): {duration:.1f} seconds")
    
    # Price data analysis
    print("\n💰 PRICE DATA")
    print("-" * 80)
    print(f"Total price ticks: {len(price_ticks)}")
    
    if price_ticks:
        symbols = Counter(tick['symbol'] for tick in price_ticks)
        print(f"Symbols tracked: {', '.join(f'{s}({c})' for s, c in symbols.items())}")
        
        # Calculate tick rate
        if len(price_ticks) > 1:
            first_tick = price_ticks[0]['timestamp']
            last_tick = price_ticks[-1]['timestamp']
            duration = last_tick - first_tick
            if duration > 0:
                tick_rate = len(price_ticks) / duration
                print(f"Average tick rate: {tick_rate:.2f} ticks/second")
        
        # Price range for each symbol
        by_symbol = defaultdict(list)
        for tick in price_ticks:
            by_symbol[tick['symbol']].append(tick['price'])
        
        for symbol, prices in by_symbol.items():
            min_price = min(prices)
            max_price = max(prices)
            print(f"{symbol}: ${min_price:,.2f} - ${max_price:,.2f} (range: ${max_price - min_price:,.2f})")
    
    # Market analysis
    print("\n📈 MARKETS")
    print("-" * 80)
    print(f"Total market state changes: {len(markets)}")
    
    if markets:
        statuses = Counter(m['status'] for m in markets)
        print(f"Status breakdown: {dict(statuses)}")
        
        unique_markets = len(set(m['market_id'] for m in markets))
        print(f"Unique markets tracked: {unique_markets}")
    
    # Order book analysis
    print("\n📖 ORDER BOOKS")
    print("-" * 80)
    print(f"Total orderbook snapshots: {len(orderbooks)}")
    
    if orderbooks:
        # Average spreads
        yes_spreads = [ob['yes_spread'] for ob in orderbooks if ob.get('yes_spread') is not None]
        no_spreads = [ob['no_spread'] for ob in orderbooks if ob.get('no_spread') is not None]
        
        if yes_spreads:
            print(f"Average YES spread: {sum(yes_spreads)/len(yes_spreads):.4f}")
        if no_spreads:
            print(f"Average NO spread: {sum(no_spreads)/len(no_spreads):.4f}")
    
    # Calculation analysis
    print("\n🧮 CALCULATIONS")
    print("-" * 80)
    print(f"Total calculations: {len(calculations)}")
    
    if calculations:
        calc_types = Counter(c['calculation_type'] for c in calculations)
        print(f"Calculation types: {dict(calc_types)}")
        
        # Volatility stats
        vol_calcs = [c for c in calculations if c['calculation_type'] == 'volatility']
        if vol_calcs:
            vols = [c['outputs']['annualized_vol'] for c in vol_calcs]
            print(f"Volatility range: {min(vols):.1%} - {max(vols):.1%}")
            print(f"Average volatility: {sum(vols)/len(vols):.1%}")
    
    # Decision analysis
    print("\n🎯 TRADING DECISIONS")
    print("-" * 80)
    print(f"Total decisions: {len(decisions)}")
    
    if decisions:
        decision_types = Counter(d['decision'] for d in decisions)
        print(f"Decision breakdown:")
        for decision, count in decision_types.most_common():
            percentage = (count / len(decisions)) * 100
            print(f"  {decision}: {count} ({percentage:.1f}%)")
        
        # Analyze edges
        edges = []
        for d in decisions:
            if 'edge' in d['reasoning']:
                edges.append(d['reasoning']['edge'])
            elif 'edge_up' in d['reasoning']:
                edges.append(d['reasoning']['edge_up'])
        
        if edges:
            print(f"\nEdge statistics:")
            print(f"  Min edge: {min(edges):+.1%}")
            print(f"  Max edge: {max(edges):+.1%}")
            print(f"  Avg edge: {sum(edges)/len(edges):+.1%}")
            
            # Count significant edges
            threshold = 0.02  # Default threshold
            if decisions and 'threshold' in decisions[0]['reasoning']:
                threshold = decisions[0]['reasoning']['threshold']
            
            significant = [e for e in edges if abs(e) >= threshold]
            print(f"  Edges above threshold ({threshold:.1%}): {len(significant)} ({len(significant)/len(edges)*100:.1f}%)")
    
    # Trade analysis
    print("\n💼 TRADES")
    print("-" * 80)
    print(f"Total trade operations: {len(trades)}")
    
    if trades:
        trade_types = Counter(t['trade_type'] for t in trades)
        print(f"Trade types: {dict(trade_types)}")
        
        statuses = Counter(t['status'] for t in trades)
        print(f"Trade statuses: {dict(statuses)}")
        
        sides = Counter(t['side'] for t in trades)
        print(f"Trade sides: {dict(sides)}")
    
    # Performance metrics
    print("\n⚡ PERFORMANCE METRICS")
    print("-" * 80)
    
    if performance:
        latest_perf = performance[-1]
        metrics = latest_perf.get('metrics', {})
        
        print(f"Tick count: {metrics.get('tick_count', 'N/A')}")
        print(f"Tick rate: {metrics.get('avg_tick_rate', 'N/A'):.2f} ticks/sec")
        print(f"Active markets: {metrics.get('active_markets', 'N/A')}")
        print(f"Current spot: ${metrics.get('current_spot', 'N/A'):,.2f}")
        
        if 'volatility' in metrics:
            vol = metrics['volatility']
            print(f"Volatility: {vol.get('annualized', 'N/A'):.1%}")
            print(f"Sample count: {vol.get('sample_count', 'N/A')}")
    
    # Error analysis
    print("\n⚠️  ERRORS")
    print("-" * 80)
    
    errors = [e for e in events if e.get('event_type') == 'error']
    print(f"Total errors: {len(errors)}")
    
    if errors:
        error_types = Counter(e['error_type'] for e in errors)
        print(f"Error types:")
        for error_type, count in error_types.most_common():
            print(f"  {error_type}: {count}")
        
        print(f"\nRecent errors (last 5):")
        for error in errors[-5:]:
            timestamp = datetime.fromtimestamp(error['timestamp'])
            print(f"  [{timestamp}] {error['error_type']}: {error['error_message']}")
    
    print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Analyze Polymarket MM performance logs")
    parser.add_argument("session_dir", type=Path, help="Path to session log directory")
    args = parser.parse_args()
    
    if not args.session_dir.exists():
        print(f"Error: Directory not found: {args.session_dir}")
        return 1
    
    if not args.session_dir.is_dir():
        print(f"Error: Not a directory: {args.session_dir}")
        return 1
    
    analyze_session(args.session_dir)
    return 0


if __name__ == "__main__":
    exit(main())
