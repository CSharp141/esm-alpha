#!/usr/bin/env python3
"""
Test script to demonstrate precise strike price capture at market start time.

This script:
1. Connects to Polymarket RTDS for BTC price updates
2. Fetches upcoming BTC market with start_time calculated
3. Buffers price ticks with timestamps
4. Captures strike price at exact market start time (within 5 seconds)

Run with:
    python test_strike_timing.py
"""

import asyncio
import time
from datetime import datetime, timezone
from src.config import get_config
from src.helpers.polymarket_rtds import PolymarketRTDSClient
from src.helpers.polymarket import PolymarketClient
from src.helpers.pricing import PricingEngine


async def test_strike_timing():
    """Test precise strike price capture at market start."""
    print("=" * 80)
    print("STRIKE PRICE TIMING TEST")
    print("=" * 80)
    
    # Load config
    config = get_config()
    
    # Initialize Polymarket client
    print("\n[1/4] Initializing Polymarket client...")
    pm_client = PolymarketClient.from_config(config)
    
    # Initialize pricing engine (with price buffer)
    print("[2/4] Initializing pricing engine with price buffer...")
    pricing_engine = PricingEngine(
        lambda_param=config.pricing.lambda_param,
        base_spread=config.trading.base_spread,
        max_inventory=config.trading.max_inventory,
        inventory_skew_factor=config.trading.inventory_skew_factor
    )
    
    # Fetch BTC market
    print("[3/4] Fetching BTC market...")
    markets = pm_client.get_crypto_15min_markets(["BTC"])
    
    if not markets:
        print("❌ No BTC markets found!")
        return
    
    market = markets[0]
    print(f"\n✅ Found market: {market.question}")
    
    # Display timing info
    if market.start_time:
        start_dt = datetime.fromtimestamp(market.start_time, tz=timezone.utc)
        expiry_dt = datetime.fromtimestamp(market.expiry_time, tz=timezone.utc)
        
        print(f"   Start time:  {start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (Unix: {market.start_time})")
        print(f"   Expiry time: {expiry_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (Unix: {market.expiry_time})")
        print(f"   Duration:    {(market.expiry_time - market.start_time) / 60:.0f} minutes")
        
        # Check if market has started
        now = time.time()
        if now < market.start_time:
            seconds_to_start = market.start_time - now
            print(f"\n⏰ Market starts in {seconds_to_start:.0f} seconds")
            print("   Waiting for start time to capture strike price...")
        elif now > market.expiry_time:
            print(f"\n⚠️  Market already expired {(now - market.expiry_time) / 60:.1f} minutes ago")
        else:
            seconds_since_start = now - market.start_time
            print(f"\n✅ Market started {seconds_since_start:.0f} seconds ago")
            print("   Will attempt to retrieve buffered price from start time...")
    else:
        print("⚠️  Market has no start_time field!")
    
    # Initialize RTDS client
    print("\n[4/4] Connecting to Polymarket RTDS...")
    rtds_client = PolymarketRTDSClient(
        ws_url=config.system.rtds_ws_url,
        symbols=["btc/usd"]
    )
    
    # Price update callback
    tick_count = [0]  # Use list to modify in closure
    
    async def handle_price_update(tick):
        """Handle price updates and update pricing engine."""
        tick_count[0] += 1
        pricing_engine.update_price(tick.price, tick.timestamp)
        
        # Print every 10th tick
        if tick_count[0] % 10 == 0:
            dt = datetime.fromtimestamp(tick.timestamp, tz=timezone.utc)
            print(f"[Tick {tick_count[0]:4d}] {tick.symbol}: ${tick.price:.2f} at {dt.strftime('%H:%M:%S')}")
        
        # Check if we can capture strike price
        if market.start_time and market.strike_price is None or market.strike_price == 0:
            if time.time() >= market.start_time:
                # Try to get price at start time
                strike = pricing_engine.get_price_at_timestamp(
                    market.start_time,
                    tolerance_seconds=5.0
                )
                
                if strike:
                    market.strike_price = strike
                    start_dt = datetime.fromtimestamp(market.start_time, tz=timezone.utc)
                    print(f"\n{'=' * 80}")
                    print("✅ STRIKE PRICE CAPTURED!")
                    print(f"{'=' * 80}")
                    print(f"   Price: ${strike:.2f}")
                    print(f"   Time:  {start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    print(f"   Market: {market.question}")
                    print(f"{'=' * 80}\n")
    
    rtds_client.on_price_update = handle_price_update
    
    # Connect and run
    print("\n🔌 Connecting to RTDS WebSocket...")
    try:
        await rtds_client.connect()
        
        # Monitor for strike price capture
        print("\n📊 Monitoring price updates...")
        print("   Press Ctrl+C to stop\n")
        
        # Run for 5 minutes or until strike captured
        start_time = time.time()
        while time.time() - start_time < 300:  # 5 minutes
            await asyncio.sleep(1)
            
            # Check if strike captured
            if market.strike_price and market.strike_price > 0:
                print("\n✅ Strike price captured successfully!")
                
                # Show buffer stats
                buffer_size = len(pricing_engine.price_buffer)
                if buffer_size > 0:
                    oldest = pricing_engine.price_buffer[0]
                    newest = pricing_engine.price_buffer[-1]
                    oldest_dt = datetime.fromtimestamp(oldest[0], tz=timezone.utc)
                    newest_dt = datetime.fromtimestamp(newest[0], tz=timezone.utc)
                    
                    print("\n📈 Price Buffer Statistics:")
                    print(f"   Total ticks: {buffer_size}")
                    print(f"   Oldest: {oldest_dt.strftime('%H:%M:%S')} (${oldest[1]:.2f})")
                    print(f"   Newest: {newest_dt.strftime('%H:%M:%S')} (${newest[1]:.2f})")
                    print(f"   Time span: {(newest[0] - oldest[0]):.0f} seconds")
                
                break
        
        print("\n✅ Test complete!")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🔌 Disconnecting...")
        await rtds_client.disconnect()


if __name__ == "__main__":
    asyncio.run(test_strike_timing())
