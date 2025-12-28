"""
Polymarket RTDS (Real-Time Data Stream) WebSocket Client for Crypto Prices.

Connects to Polymarket's RTDS API to receive real-time cryptocurrency price updates
from Chainlink oracles. This replaces external data sources (Binance, Chainlink direct)
with Polymarket's unified price feed.

Features:
- Real-time crypto price updates via WebSocket
- No authentication required
- Chainlink oracle prices (same as used for market settlements)
- Supports BTC, ETH, SOL, XRP and more

Documentation:
    https://docs.polymarket.com/developers/RTDS/RTDS-crypto-prices

No external dependencies beyond websockets library.
"""

import asyncio
import json
import time
from typing import Callable, Optional, Dict, Any, List
from collections import deque
import websockets
from dataclasses import dataclass
from datetime import datetime


# Polymarket RTDS WebSocket endpoint
POLYMARKET_RTDS_WS = "wss://ws-live-data.polymarket.com"


@dataclass
class PriceTick:
    """Represents a single price tick from Polymarket RTDS."""
    symbol: str  # e.g., "BTC/USD"
    price: float
    timestamp: float  # Unix timestamp in seconds
    volume: float = 0.0
    trade_id: Optional[int] = None


class PolymarketRTDSClient:
    """
    High-performance WebSocket client for Polymarket RTDS crypto prices.
    
    Subscribes to crypto_prices_chainlink topic for real-time Chainlink oracle prices.
    Optimized for low-latency market making applications.
    """
    
    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        on_tick: Optional[Callable[[PriceTick], None]] = None,
        tick_buffer_size: int = 10000,
        auto_reconnect: bool = True
    ):
        """
        Initialize Polymarket RTDS WebSocket client.
        
        Args:
            symbols: List of trading pairs (e.g., ['btc/usd', 'eth/usd'])
                    If None, subscribes to all available crypto prices
            on_tick: Callback function called on each new price update
            tick_buffer_size: Size of circular buffer for tick history
            auto_reconnect: Automatically reconnect on disconnection
        """
        # Normalize symbols to lowercase for Polymarket format
        if symbols:
            self.symbols = [s.lower() for s in symbols]
        else:
            self.symbols = None  # Subscribe to all
        
        self.on_tick = on_tick
        self.tick_buffer_size = tick_buffer_size
        self.auto_reconnect = auto_reconnect
        
        # Tick storage (circular buffer for memory efficiency)
        self.tick_buffer: Dict[str, deque] = {}
        
        # Connection state
        self.ws = None
        self.running = False
        self.last_tick_time: Dict[str, float] = {}
        
        # Performance metrics
        self.tick_count = 0
        self.start_time = None
        self.reconnect_count = 0
        self.last_heartbeat = time.time()
    
    def _build_subscription_message(self) -> Dict[str, Any]:
        """
        Build subscription message for Polymarket RTDS.
        
        Returns:
            Subscription message dict
        """
        # According to Polymarket docs, for specific symbols we need JSON string filter
        # For all symbols, use empty string filter
        if self.symbols and len(self.symbols) == 1:
            # Single symbol - use JSON filter (NO SPACES in JSON string!)
            filters = json.dumps({"symbol": self.symbols[0]}, separators=(',', ':'))
        elif self.symbols and len(self.symbols) > 1:
            # Multiple symbols - subscribe to all and filter client-side
            # (Polymarket RTDS doesn't support multi-symbol filters in one subscription)
            filters = ""
        else:
            # No symbols specified - subscribe to all
            filters = ""
        
        subscription = {
            "action": "subscribe",
            "subscriptions": [
                {
                    "topic": "crypto_prices_chainlink",
                    "type": "*",
                    "filters": filters
                }
            ]
        }
        
        print(f"[DEBUG] Subscription message: {json.dumps(subscription, indent=2)}")
        return subscription
    
    def _parse_price_message(self, msg: Dict[str, Any]) -> Optional[PriceTick]:
        """
        Parse price update message from Polymarket RTDS.
        
        Expected format:
        {
            "topic": "crypto_prices_chainlink",
            "type": "update",
            "timestamp": 1753314064237,
            "payload": {
                "symbol": "eth/usd",
                "timestamp": 1753314064213,
                "value": 3456.78
            }
        }
        
        Args:
            msg: Raw message dict from Polymarket RTDS
            
        Returns:
            PriceTick object or None if parse fails
        """
        try:
            if msg.get("topic") != "crypto_prices_chainlink":
                return None
            
            payload = msg.get("payload", {})
            symbol = payload.get("symbol")
            
            # Filter by symbols if specified
            if self.symbols and symbol.lower() not in self.symbols:
                return None
            
            return PriceTick(
                symbol=symbol.upper(),  # Normalize to uppercase for consistency
                price=float(payload.get("value")),
                timestamp=payload.get("timestamp") / 1000.0,  # Convert ms to seconds
                volume=0.0,  # Volume not provided in crypto_prices_chainlink
                trade_id=None
            )
        except (KeyError, TypeError, ValueError) as e:
            print(f"Error parsing price message: {e}")
            return None
    
    async def _heartbeat(self):
        """Send periodic ping messages to keep connection alive (every 5 seconds as recommended)."""
        while self.running:
            await asyncio.sleep(5)  # Send ping every 5 seconds per Polymarket docs
            if self.ws:
                try:
                    await self.ws.ping()
                    self.last_heartbeat = time.time()
                except Exception as e:
                    print(f"Heartbeat ping failed: {e}")
    
    async def _handle_message(self, message: str):
        """
        Handle incoming WebSocket message.
        
        Args:
            message: Raw WebSocket message string
        """
        try:
            # Skip empty messages
            if not message or not message.strip():
                return
            
            msg = json.loads(message)
            
            # Handle different message types
            msg_type = msg.get("type")
            
            # Debug: print message type
            if msg_type not in ["update"]:
                print(f"[RTDS] Received message type: {msg_type}")
            
            if msg_type == "update":
                # Price update message
                tick = self._parse_price_message(msg)
                if tick:
                    # Store in buffer
                    if tick.symbol not in self.tick_buffer:
                        self.tick_buffer[tick.symbol] = deque(maxlen=self.tick_buffer_size)
                    self.tick_buffer[tick.symbol].append(tick)
                    
                    # Update tracking
                    self.last_tick_time[tick.symbol] = tick.timestamp
                    self.tick_count += 1
                    
                    # Call user callback
                    if self.on_tick:
                        if asyncio.iscoroutinefunction(self.on_tick):
                            await self.on_tick(tick)
                        else:
                            self.on_tick(tick)
            
            elif msg_type == "subscribed":
                print("✓ Successfully subscribed to crypto_prices_chainlink")
                print("  Waiting for price updates...")
            
            elif msg_type == "error":
                print(f"✗ RTDS Error: {msg.get('message', 'Unknown error')}")
            
            else:
                # Unknown message type, log for debugging
                print(f"[DEBUG] Unknown message type: {msg_type}")
            
        except json.JSONDecodeError as e:
            # Skip non-JSON messages (like pong responses)
            if message and len(message) > 100:
                print(f"Failed to decode long message: {e}")
            # Silently ignore short non-JSON messages (pings/pongs)
        except Exception as e:
            print(f"Error handling message: {e}")
    
    async def connect(self):
        """
        Connect to Polymarket RTDS WebSocket and start receiving price updates.
        
        This is a blocking call that maintains the connection until stopped.
        """
        self.running = True
        self.start_time = time.time()
        
        while self.running:
            try:
                print(f"Connecting to Polymarket RTDS: {POLYMARKET_RTDS_WS}")
                
                async with websockets.connect(
                    POLYMARKET_RTDS_WS,
                    ping_interval=5,  # Ping every 5 seconds per Polymarket docs
                    ping_timeout=10
                ) as ws:
                    self.ws = ws
                    print("✓ Connected to Polymarket RTDS")
                    
                    # Send subscription message
                    sub_msg = self._build_subscription_message()
                    await ws.send(json.dumps(sub_msg))
                    print("Subscribing to crypto_prices_chainlink...")
                    if self.symbols:
                        print(f"  Symbols: {', '.join(self.symbols)}")
                    else:
                        print("  All available symbols")
                    
                    # Start heartbeat task
                    heartbeat_task = asyncio.create_task(self._heartbeat())
                    
                    # Listen for messages
                    async for message in ws:
                        await self._handle_message(message)
                    
                    # Cancel heartbeat on disconnect
                    heartbeat_task.cancel()
                    
            except websockets.exceptions.ConnectionClosed as e:
                print(f"Connection closed: {e}")
                if self.auto_reconnect and self.running:
                    self.reconnect_count += 1
                    wait_time = min(5 * self.reconnect_count, 60)  # Max 60s backoff
                    print(f"Reconnecting in {wait_time}s... (attempt {self.reconnect_count})")
                    await asyncio.sleep(wait_time)
                else:
                    break
                    
            except Exception as e:
                print(f"Connection error: {e}")
                if self.auto_reconnect and self.running:
                    self.reconnect_count += 1
                    print(f"Reconnecting in 5s... (attempt {self.reconnect_count})")
                    await asyncio.sleep(5)
                else:
                    break
    
    async def disconnect(self):
        """Gracefully disconnect from WebSocket."""
        self.running = False
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass  # Ignore errors during close
    
    def get_latest_price(self, symbol: str) -> Optional[PriceTick]:
        """
        Get the most recent price tick for a symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USD')
            
        Returns:
            Latest PriceTick or None if not available
        """
        symbol = symbol.upper()
        if symbol in self.tick_buffer and self.tick_buffer[symbol]:
            return self.tick_buffer[symbol][-1]
        return None
    
    def get_tick_history(self, symbol: str, n: int = 100) -> List[PriceTick]:
        """
        Get recent tick history for a symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USD')
            n: Number of recent ticks to return
            
        Returns:
            List of PriceTick objects (most recent last)
        """
        symbol = symbol.upper()
        if symbol not in self.tick_buffer:
            return []
        
        ticks = list(self.tick_buffer[symbol])
        return ticks[-n:] if len(ticks) > n else ticks
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get client statistics.
        
        Returns:
            Dictionary with connection and performance stats
        """
        uptime = time.time() - self.start_time if self.start_time else 0
        ticks_per_second = self.tick_count / uptime if uptime > 0 else 0
        
        # Check if connected (websockets 14+ doesn't have 'closed' attribute)
        is_connected = self.ws is not None and self.running
        
        return {
            "connected": is_connected,
            "uptime_seconds": round(uptime, 2),
            "tick_count": self.tick_count,
            "ticks_per_second": round(ticks_per_second, 2),
            "reconnect_count": self.reconnect_count,
            "symbols": list(self.tick_buffer.keys()),
            "last_heartbeat": datetime.fromtimestamp(self.last_heartbeat).isoformat()
        }


async def demo():
    """
    Demo usage of PolymarketRTDSClient.
    
    Run with: python -m helpers.polymarket_rtds
    """
    print("=== Polymarket RTDS Demo ===\n")
    
    def on_price_update(tick: PriceTick):
        print(f"{tick.symbol}: ${tick.price:,.2f} @ {datetime.fromtimestamp(tick.timestamp).strftime('%H:%M:%S.%f')[:-3]}")
    
    # Subscribe to BTC and ETH prices
    client = PolymarketRTDSClient(
        symbols=['btc/usd', 'eth/usd', 'sol/usd'],
        on_tick=on_price_update
    )
    
    try:
        await client.connect()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        await client.disconnect()
        print("✓ Disconnected")
        
        # Print final stats
        stats = client.get_stats()
        print("\nFinal Statistics:")
        print(f"  Total ticks received: {stats['tick_count']}")
        print(f"  Uptime: {stats['uptime_seconds']}s")
        print(f"  Avg ticks/second: {stats['ticks_per_second']}")


if __name__ == "__main__":
    asyncio.run(demo())
