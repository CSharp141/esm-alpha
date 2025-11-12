#!/usr/bin/env python3
"""
Test the new 15-minute market discovery methods.
"""

import sys
sys.path.insert(0, 'src')

from helpers.polymarket import PolymarketClient
from config import get_config


def test_market_discovery():
    """Test both discovery strategies for all assets."""
    print("=" * 70)
    print("Testing Polymarket 15-Minute Market Discovery")
    print("=" * 70)
    
    # Load config
    config = get_config()
    
    # Initialize client
    client = PolymarketClient.from_config(config.polymarket)
    
    # Test assets
    assets = ["BTC", "ETH", "SOL", "XRP"]
    
    print("\n" + "=" * 70)
    print("Test 1: Predictive Strategy (Strategy C)")
    print("=" * 70)
    
    for asset in assets:
        print(f"\n[{asset}] Testing predictive discovery...")
        market = client.discover_next_15m_market_predictive(asset)
        
        if market:
            print(f"  ✅ Found: {market.question}")
            print(f"  📅 Expires: {market.minutes_to_expiry():.1f} minutes")
            print(f"  🆔 Market ID: {market.market_id[:16]}...")
            print(f"  💰 YES: bid={market.yes_bid}, ask={market.yes_ask}")
            print(f"  💰 NO:  bid={market.no_bid}, ask={market.no_ask}")
        else:
            print(f"  ⚠️  Not found (market may not be live yet)")
    
    print("\n" + "=" * 70)
    print("Test 2: Scan Strategy (Strategy A) - Fallback")
    print("=" * 70)
    
    for asset in assets:
        print(f"\n[{asset}] Testing scan discovery...")
        market = client.discover_next_15m_market_scan(asset)
        
        if market:
            print(f"  ✅ Found: {market.question}")
            print(f"  📅 Expires: {market.minutes_to_expiry():.1f} minutes")
            print(f"  🆔 Market ID: {market.market_id[:16]}...")
            print(f"  💰 YES: bid={market.yes_bid}, ask={market.yes_ask}")
            print(f"  💰 NO:  bid={market.no_bid}, ask={market.no_ask}")
        else:
            print(f"  ❌ Not found")
    
    print("\n" + "=" * 70)
    print("Test 3: Combined Strategy (main method)")
    print("=" * 70)
    
    markets = client.get_crypto_15min_markets(assets)
    
    print(f"\n📊 Total markets found: {len(markets)}")
    
    for market in markets:
        print(f"\n  Market: {market.question}")
        print(f"    Expires: {market.minutes_to_expiry():.1f} minutes")
        print(f"    Market ID: {market.market_id[:16]}...")
        print(f"    YES: bid={market.yes_bid:.3f}, ask={market.yes_ask:.3f}" if market.yes_bid and market.yes_ask else "    YES: No liquidity")
        print(f"    NO:  bid={market.no_bid:.3f}, ask={market.no_ask:.3f}" if market.no_bid and market.no_ask else "    NO:  No liquidity")
    
    print("\n" + "=" * 70)
    print("✅ All tests completed!")
    print("=" * 70)
    
    if len(markets) == 0:
        print("\n⚠️  WARNING: No markets found!")
        print("Possible reasons:")
        print("  1. Markets not live yet (try again at next 15-minute boundary)")
        print("  2. API issues or rate limiting")
        print("  3. Markets structure changed")
    elif len(markets) < len(assets):
        print(f"\n⚠️  WARNING: Only found {len(markets)}/{len(assets)} markets")
        print("Some assets may not have active markets right now")


if __name__ == "__main__":
    try:
        test_market_discovery()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
