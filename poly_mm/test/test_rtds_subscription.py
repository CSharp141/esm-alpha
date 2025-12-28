#!/usr/bin/env python3
"""
Test Polymarket RTDS subscription with different configurations
"""
import asyncio
import json
import websockets

RTDS_URL = "wss://ws-live-data.polymarket.com"

async def test_subscription(filters=None, topic="crypto_prices_chainlink"):
    """Test a specific subscription configuration"""
    print(f"\n{'='*60}")
    print(f"Testing topic: {topic}")
    print(f"Filters: {filters}")
    print(f"{'='*60}\n")
    
    subscription = {
        "action": "subscribe",
        "subscriptions": [
            {
                "topic": topic,
                "type": "*",
                "filters": filters if filters is not None else ""
            }
        ]
    }
    
    print(f"Sending subscription: {json.dumps(subscription, indent=2)}\n")
    
    try:
        async with websockets.connect(RTDS_URL, ping_interval=5) as ws:
            # Send subscription
            await ws.send(json.dumps(subscription))
            
            # Listen for messages for 30 seconds
            message_count = 0
            async for message in ws:
                try:
                    msg = json.loads(message)
                    msg_type = msg.get("type")
                    topic_name = msg.get("topic")
                    
                    print(f"[{message_count}] Type: {msg_type}, Topic: {topic_name}")
                    
                    if msg_type == "update":
                        payload = msg.get("payload", {})
                        symbol = payload.get("symbol")
                        value = payload.get("value")
                        print(f"    → {symbol}: ${value:,.2f}")
                    
                    message_count += 1
                    
                    if message_count >= 10:  # Stop after 10 messages
                        print("\n✓ Got 10 messages, test successful!")
                        break
                        
                except json.JSONDecodeError:
                    print(f"Non-JSON message received")
                except Exception as e:
                    print(f"Error: {e}")
                    
    except Exception as e:
        print(f"Connection error: {e}")

async def main():
    print("=== Polymarket RTDS Subscription Test ===\n")
    
    # Test 1: No filter (all symbols)
    print("\n--- TEST 1: No filter (should get all crypto prices) ---")
    await test_subscription(filters="")
    
    await asyncio.sleep(2)
    
    # Test 2: Single symbol filter
    print("\n--- TEST 2: BTC filter ---")
    await test_subscription(filters='{"symbol":"btc/usd"}')
    
    await asyncio.sleep(2)
    
    # Test 3: Try the binance source instead
    print("\n--- TEST 3: Try crypto_prices (Binance source) ---")
    await test_subscription(filters="", topic="crypto_prices")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nStopped by user")
