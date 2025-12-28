#!/usr/bin/env python3
"""
RTDS STREAM REPLAY TOOL

Replays recorded RTDS price data to simulate historical markets.

This tool reads JSONL files created by record_rtds_stream.py and provides
various analysis and replay capabilities for backtesting.

Usage:
    # Show summary of recorded data
    python replay_rtds_stream.py data.jsonl --summary
    
    # Extract prices for a specific time range (15-minute market)
    python replay_rtds_stream.py data.jsonl --start "2025-12-27 14:00:00" --end "2025-12-27 14:15:00"
    
    # Get price at specific timestamp
    python replay_rtds_stream.py data.jsonl --timestamp 1735329600

Author: Market Making System
Date: December 27, 2025
"""

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


class RTDSReplay:
    """Replay and analyze recorded RTDS price data"""
    
    def __init__(self, filename: str):
        self.filename = filename
        self.prices: List[Dict[str, Any]] = []
        self.load_data()
        
    def load_data(self):
        """Load JSONL data from file"""
        print(f"📂 Loading data from: {self.filename}")
        
        path = Path(self.filename)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {self.filename}")
        
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        self.prices.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        
        print(f"✅ Loaded {len(self.prices):,} price records")
        
    def print_summary(self):
        """Print summary statistics"""
        if not self.prices:
            print("❌ No data loaded")
            return
        
        first = self.prices[0]
        last = self.prices[-1]
        
        timestamps = [p['timestamp'] for p in self.prices]
        prices = [p['price'] for p in self.prices]
        
        first_time = datetime.fromtimestamp(first['timestamp'], tz=timezone.utc)
        last_time = datetime.fromtimestamp(last['timestamp'], tz=timezone.utc)
        duration = last['timestamp'] - first['timestamp']
        
        print(f"\n{'='*80}")
        print(f"RTDS DATA SUMMARY")
        print(f"{'='*80}\n")
        
        print(f"File:              {self.filename}")
        print(f"Asset:             {first.get('asset', 'Unknown')}")
        print(f"Records:           {len(self.prices):,}")
        print(f"\nTime Range:")
        print(f"  Start:           {first_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  End:             {last_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  Duration:        {duration:.1f} seconds ({duration/60:.1f} minutes, {duration/3600:.1f} hours)")
        
        # Calculate update rate
        if duration > 0:
            rate = len(self.prices) / duration
            print(f"  Update Rate:     {rate:.2f} updates/second")
        
        # Price statistics
        min_price = min(prices)
        max_price = max(prices)
        avg_price = sum(prices) / len(prices)
        
        print(f"\nPrice Statistics:")
        print(f"  First:           ${first['price']:,.2f}")
        print(f"  Last:            ${last['price']:,.2f}")
        print(f"  Min:             ${min_price:,.2f}")
        print(f"  Max:             ${max_price:,.2f}")
        print(f"  Average:         ${avg_price:,.2f}")
        print(f"  Range:           ${max_price - min_price:,.2f} ({((max_price - min_price) / min_price * 100):.2f}%)")
        
        # Change statistics
        price_change = last['price'] - first['price']
        price_change_pct = (price_change / first['price']) * 100
        
        print(f"\nOverall Change:")
        print(f"  Absolute:        ${price_change:+,.2f}")
        print(f"  Percentage:      {price_change_pct:+.2f}%")
        
    def get_price_at_time(self, timestamp: float) -> Optional[float]:
        """Get price at specific timestamp (or closest before)"""
        if not self.prices:
            return None
        
        # Binary search for closest timestamp <= target
        left, right = 0, len(self.prices) - 1
        result = None
        
        while left <= right:
            mid = (left + right) // 2
            if self.prices[mid]['timestamp'] <= timestamp:
                result = self.prices[mid]['price']
                left = mid + 1
            else:
                right = mid - 1
        
        return result
    
    def get_price_range(self, start_time: float, end_time: float) -> List[Dict[str, Any]]:
        """Get all prices within time range"""
        return [
            p for p in self.prices
            if start_time <= p['timestamp'] <= end_time
        ]
    
    def replay_market(self, start_time: float, end_time: float):
        """Replay a 15-minute market with statistics"""
        prices_in_range = self.get_price_range(start_time, end_time)
        
        if not prices_in_range:
            print(f"❌ No data found for time range")
            return
        
        start_dt = datetime.fromtimestamp(start_time, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_time, tz=timezone.utc)
        
        start_price = prices_in_range[0]['price']
        end_price = prices_in_range[-1]['price']
        
        all_prices = [p['price'] for p in prices_in_range]
        min_price = min(all_prices)
        max_price = max(all_prices)
        
        outcome = "UP" if end_price >= start_price else "DOWN"
        
        print(f"\n{'='*80}")
        print(f"MARKET REPLAY")
        print(f"{'='*80}\n")
        
        print(f"Time Range:")
        print(f"  Start:           {start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  End:             {end_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  Duration:        {(end_time - start_time)/60:.1f} minutes")
        
        print(f"\nPrice Data:")
        print(f"  Updates:         {len(prices_in_range):,}")
        print(f"  Start Price:     ${start_price:,.2f}")
        print(f"  End Price:       ${end_price:,.2f}")
        print(f"  Min:             ${min_price:,.2f}")
        print(f"  Max:             ${max_price:,.2f}")
        
        price_change = end_price - start_price
        price_change_pct = (price_change / start_price) * 100
        
        print(f"\nOutcome:")
        print(f"  Change:          ${price_change:+,.2f} ({price_change_pct:+.2f}%)")
        print(f"  Result:          {outcome}")
        
        # Show price path
        if len(prices_in_range) > 0:
            print(f"\nPrice Path (sample):")
            step = max(1, len(prices_in_range) // 10)  # Show ~10 samples
            for i in range(0, len(prices_in_range), step):
                p = prices_in_range[i]
                ts = datetime.fromtimestamp(p['timestamp'], tz=timezone.utc)
                elapsed = p['timestamp'] - start_time
                print(f"  +{int(elapsed):>3}s ({ts.strftime('%H:%M:%S')}) | ${p['price']:,.2f}")
            
            # Always show last price if not already shown
            if (len(prices_in_range) - 1) % step != 0:
                p = prices_in_range[-1]
                ts = datetime.fromtimestamp(p['timestamp'], tz=timezone.utc)
                elapsed = p['timestamp'] - start_time
                print(f"  +{int(elapsed):>3}s ({ts.strftime('%H:%M:%S')}) | ${p['price']:,.2f}")
    
    def extract_15min_markets(self) -> List[Tuple[float, float, str]]:
        """
        Extract all 15-minute market boundaries from the data.
        
        Returns:
            List of (start_time, end_time, outcome) tuples
        """
        if not self.prices:
            return []
        
        markets = []
        
        # Get time range
        first_ts = self.prices[0]['timestamp']
        last_ts = self.prices[-1]['timestamp']
        
        # Round down to nearest 15-min boundary
        start_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)
        start_dt = start_dt.replace(minute=(start_dt.minute // 15) * 15, second=0, microsecond=0)
        
        # Generate all 15-min boundaries
        current = start_dt
        end_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc)
        
        while current < end_dt:
            next_boundary = current + timedelta(minutes=15)
            
            start_ts = current.timestamp()
            end_ts = next_boundary.timestamp()
            
            # Get prices for this market
            market_prices = self.get_price_range(start_ts, end_ts)
            
            if len(market_prices) >= 2:  # Need at least start and end
                start_price = market_prices[0]['price']
                end_price = market_prices[-1]['price']
                outcome = "UP" if end_price >= start_price else "DOWN"
                markets.append((start_ts, end_ts, outcome))
            
            current = next_boundary
        
        return markets
    
    def print_all_markets(self):
        """Print all 15-minute markets found in the data"""
        markets = self.extract_15min_markets()
        
        if not markets:
            print("❌ No complete 15-minute markets found in data")
            return
        
        print(f"\n{'='*80}")
        print(f"15-MINUTE MARKETS")
        print(f"{'='*80}\n")
        
        print(f"Found {len(markets)} complete markets:\n")
        
        up_count = sum(1 for _, _, outcome in markets if outcome == "UP")
        down_count = len(markets) - up_count
        
        for start_ts, end_ts, outcome in markets:
            start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)
            
            prices = self.get_price_range(start_ts, end_ts)
            start_price = prices[0]['price']
            end_price = prices[-1]['price']
            change = end_price - start_price
            
            print(f"{start_dt.strftime('%Y-%m-%d %H:%M')} - {end_dt.strftime('%H:%M')} | "
                  f"${start_price:>8,.2f} → ${end_price:>8,.2f} | "
                  f"{change:>+7.2f} | {outcome:>4s} | {len(prices):>4d} updates")
        
        print(f"\n{'='*80}")
        print(f"Summary: {up_count} UP ({up_count/len(markets)*100:.1f}%), "
              f"{down_count} DOWN ({down_count/len(markets)*100:.1f}%)")


def parse_datetime_arg(s: str) -> float:
    """Parse datetime string to Unix timestamp"""
    # Try various formats
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    
    # Try as Unix timestamp
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"Could not parse datetime: {s}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Replay recorded RTDS price data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show summary
  python replay_rtds_stream.py data.jsonl --summary
  
  # List all 15-minute markets
  python replay_rtds_stream.py data.jsonl --markets
  
  # Replay specific market
  python replay_rtds_stream.py data.jsonl --start "2025-12-27 14:00:00" --end "2025-12-27 14:15:00"
  
  # Get price at timestamp
  python replay_rtds_stream.py data.jsonl --timestamp 1735329600
        """
    )
    
    parser.add_argument("file", help="JSONL file with recorded price data")
    parser.add_argument("--summary", action="store_true", help="Show data summary")
    parser.add_argument("--markets", action="store_true", help="List all 15-minute markets")
    parser.add_argument("--start", type=str, help="Start time for market replay (YYYY-MM-DD HH:MM:SS or timestamp)")
    parser.add_argument("--end", type=str, help="End time for market replay")
    parser.add_argument("--timestamp", type=str, help="Get price at specific timestamp")
    
    args = parser.parse_args()
    
    # Load data
    replay = RTDSReplay(args.file)
    
    # Execute commands
    if args.summary:
        replay.print_summary()
        
    elif args.markets:
        replay.print_all_markets()
        
    elif args.start and args.end:
        start_ts = parse_datetime_arg(args.start)
        end_ts = parse_datetime_arg(args.end)
        replay.replay_market(start_ts, end_ts)
        
    elif args.timestamp:
        ts = parse_datetime_arg(args.timestamp)
        price = replay.get_price_at_time(ts)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        if price:
            print(f"\nPrice at {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}: ${price:,.2f}")
        else:
            print(f"\n❌ No price data available at {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    else:
        # Default: show summary
        replay.print_summary()


if __name__ == "__main__":
    main()
