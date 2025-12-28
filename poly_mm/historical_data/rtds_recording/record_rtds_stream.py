#!/usr/bin/env python3
"""
POLYMARKET RTDS STREAM RECORDER

Records real-time Chainlink price updates from Polymarket's RTDS WebSocket
for accurate market replay and backtesting.

This captures tick-by-tick BTC price data that can be used to replay historical
15-minute markets with exact price movements.

Usage:
    python record_rtds_stream.py --asset BTC --duration 3600
    python record_rtds_stream.py --asset ETH --output eth_prices.jsonl
    python record_rtds_stream.py --help

Output Format (JSONL - one JSON per line):
    {"timestamp": 1735329600.123, "asset": "BTC", "price": 96543.21, "stream_id": "btc-usd"}
    {"timestamp": 1735329601.456, "asset": "BTC", "price": 96544.15, "stream_id": "btc-usd"}

Author: Market Making System
Date: December 27, 2025
"""

import asyncio
import json
import time
import argparse
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
import websockets


# Polymarket RTDS WebSocket endpoint
RTDS_WS_URL = "wss://ws-live-data.polymarket.com"

# Stream IDs for different assets
STREAM_IDS = {
    "BTC": "btc-usd",
    "ETH": "eth-usd",
    "SOL": "sol-usd",
    "XRP": "xrp-usd"
}


class RTDSRecorder:
    """Records real-time price data from Polymarket RTDS WebSocket"""
    
    def __init__(self, asset: str, output_file: str):
        self.asset = asset.upper()
        self.stream_id = STREAM_IDS.get(self.asset)
        if not self.stream_id:
            raise ValueError(f"Unsupported asset: {asset}. Supported: {list(STREAM_IDS.keys())}")
        
        self.output_file = output_file
        self.ws = None
        self.running = False
        self.prices_recorded = 0
        self.start_time = None
        self.last_price = None
        
        # Statistics
        self.first_price_time = None
        self.min_price = float('inf')
        self.max_price = float('-inf')
        
    async def connect(self):
        """Connect to RTDS WebSocket"""
        print(f"🔌 Connecting to {RTDS_WS_URL}...")
        self.ws = await websockets.connect(RTDS_WS_URL)
        print(f"✅ Connected!")
        
    async def subscribe(self):
        """Subscribe to asset price stream"""
        # Polymarket RTDS format: action=subscribe with crypto_prices_chainlink topic
        # Filter by symbol (e.g., "btc/usd")
        symbol = self.stream_id.replace('-', '/')  # btc-usd -> btc/usd
        
        subscribe_msg = {
            "action": "subscribe",
            "subscriptions": [
                {
                    "topic": "crypto_prices_chainlink",
                    "type": "*",
                    "filters": json.dumps({"symbol": symbol}, separators=(',', ':'))
                }
            ]
        }
        
        print(f"📡 Subscribing to {self.asset} price stream ({symbol})...")
        await self.ws.send(json.dumps(subscribe_msg))
        print("✅ Subscribed!")
        
    async def record_stream(self, duration: Optional[int] = None):
        """
        Record price updates to file.
        
        Args:
            duration: Optional duration in seconds. If None, runs indefinitely.
        """
        self.running = True
        self.start_time = time.time()
        
        # Open output file in append mode
        output_path = Path(self.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"\n📝 Recording {self.asset} prices to: {self.output_file}")
        if duration:
            print(f"⏱️  Duration: {duration} seconds ({duration//60} minutes)")
        else:
            print(f"⏱️  Duration: Indefinite (press Ctrl+C to stop)")
        print(f"⏰ Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"\n{'='*80}")
        print(f"Recording... (prices will appear below)")
        print(f"{'='*80}\n")
        
        try:
            with open(output_path, 'a') as f:
                while self.running:
                    # Check duration
                    if duration and (time.time() - self.start_time) >= duration:
                        print(f"\n⏰ Duration reached ({duration}s)")
                        break
                    
                    try:
                        # Receive message with timeout
                        message = await asyncio.wait_for(self.ws.recv(), timeout=30)
                        
                        # Skip empty messages
                        if not message or not message.strip():
                            continue
                        
                        data = json.loads(message)
                        
                        # Process price update (only handle "update" type messages)
                        if data.get("type") == "update":
                            await self._process_price_update(data, f)
                            
                    except asyncio.TimeoutError:
                        print(f"⚠️  No data received for 30 seconds")
                        continue
                        
                    except websockets.exceptions.ConnectionClosed:
                        print(f"\n❌ WebSocket connection closed")
                        break
                        
        except KeyboardInterrupt:
            print(f"\n\n⚠️  Interrupted by user")
        finally:
            self.running = False
            
    async def _process_price_update(self, data: Dict[str, Any], file):
        """Process and record a price update"""
        try:
            # Polymarket RTDS format:
            # {"topic": "crypto_prices_chainlink", "type": "update", "payload": {"symbol": "btc/usd", "value": 96543.21, "timestamp": 1735329600123}}
            if data.get("topic") != "crypto_prices_chainlink":
                return
            
            payload = data.get("payload", {})
            symbol = payload.get("symbol", "").lower()
            
            # Check if this is our asset
            expected_symbol = self.stream_id.replace('-', '/')
            if symbol != expected_symbol:
                return
            
            price = float(payload.get("value", 0))
            if price <= 0:
                return
            
            # Record timestamp
            timestamp = time.time()
            if self.first_price_time is None:
                self.first_price_time = timestamp
            
            # Update statistics
            self.min_price = min(self.min_price, price)
            self.max_price = max(self.max_price, price)
            self.last_price = price
            self.prices_recorded += 1
            
            # Write to file (JSONL format)
            record = {
                "timestamp": timestamp,
                "asset": self.asset,
                "price": price,
                "stream_id": self.stream_id
            }
            file.write(json.dumps(record) + "\n")
            file.flush()  # Ensure data is written immediately
            
            # Print progress
            elapsed = timestamp - self.start_time
            if self.prices_recorded == 1 or self.prices_recorded % 10 == 0:
                print(f"[{self.prices_recorded:>5d}] {datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime('%H:%M:%S')} | "
                      f"{self.asset}: ${price:,.2f} | "
                      f"Elapsed: {int(elapsed)}s")
                
        except Exception as e:
            print(f"⚠️  Error processing update: {e}")
    
    async def close(self):
        """Close WebSocket connection"""
        if self.ws:
            await self.ws.close()
            
    def print_summary(self):
        """Print recording summary"""
        if not self.start_time:
            return
        
        duration = time.time() - self.start_time
        
        print(f"\n{'='*80}")
        print(f"RECORDING SUMMARY")
        print(f"{'='*80}\n")
        
        print(f"Asset:             {self.asset}")
        print(f"Output File:       {self.output_file}")
        print(f"Prices Recorded:   {self.prices_recorded:,}")
        print(f"Duration:          {duration:.1f} seconds ({duration/60:.1f} minutes)")
        
        if self.prices_recorded > 0:
            rate = self.prices_recorded / duration
            print(f"Update Rate:       {rate:.2f} updates/second")
            print(f"\nPrice Statistics:")
            print(f"  First:           ${self.last_price:,.2f}" if self.first_price_time else "  First:           N/A")
            print(f"  Last:            ${self.last_price:,.2f}" if self.last_price else "  Last:            N/A")
            print(f"  Min:             ${self.min_price:,.2f}" if self.min_price != float('inf') else "  Min:             N/A")
            print(f"  Max:             ${self.max_price:,.2f}" if self.max_price != float('-inf') else "  Max:             N/A")
            if self.min_price != float('inf') and self.max_price != float('-inf'):
                range_val = self.max_price - self.min_price
                range_pct = (range_val / self.min_price) * 100
                print(f"  Range:           ${range_val:,.2f} ({range_pct:.2f}%)")
        
        print(f"\n✅ Recording complete!")


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Record Polymarket RTDS price stream for historical replay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Record BTC for 1 hour
  python record_rtds_stream.py --asset BTC --duration 3600
  
  # Record ETH indefinitely (press Ctrl+C to stop)
  python record_rtds_stream.py --asset ETH
  
  # Record to custom file
  python record_rtds_stream.py --asset SOL --output my_data/sol_prices.jsonl
  
  # Record for one full day (24 hours)
  python record_rtds_stream.py --asset BTC --duration 86400
        """
    )
    
    parser.add_argument(
        "--asset",
        type=str,
        default="BTC",
        choices=list(STREAM_IDS.keys()),
        help="Asset to record (default: BTC)"
    )
    
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Recording duration in seconds (default: indefinite)"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: rtds_<asset>_<timestamp>.jsonl)"
    )
    
    args = parser.parse_args()
    
    # Generate default output filename
    if args.output is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output = f"rtds_{args.asset.lower()}_{timestamp}.jsonl"
    
    # Print header
    print(f"\n{'='*80}")
    print(f"POLYMARKET RTDS STREAM RECORDER")
    print(f"{'='*80}\n")
    
    # Create recorder
    recorder = RTDSRecorder(args.asset, args.output)
    
    # Setup signal handler for graceful shutdown
    def signal_handler(sig, frame):
        print(f"\n\n⚠️  Shutdown signal received")
        recorder.running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Connect and subscribe
        await recorder.connect()
        await recorder.subscribe()
        
        # Start recording
        await recorder.record_stream(duration=args.duration)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        await recorder.close()
        recorder.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
