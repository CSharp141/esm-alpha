"""
Binance WebSocket helper functions for high-frequency price data.
Provides real-time tick-by-tick price updates for volatility estimation.
"""

import asyncio
import json
import time
from typing import Callable, Optional, Dict, Any
from collections import deque
import websockets
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PriceTick:
    """Represents a single price tick from Binance."""
    symbol: str
    price: float
    timestamp: float  # Unix timestamp in seconds
    volume: float = 0.0
    trade_id: Optional[int] = None


class BinanceWebSocket:
    """
    High-performance WebSocket client for Binance real-time price feeds.
    Optimized for low-latency market making applications.
    """
    
    BASE_WS_URL = "wss://stream.binance.com:9443/ws"
    BASE_WS_URL_TESTNET = "wss://testnet.binance.vision/ws"
    
    def __init__(
        self,
        symbols: list[str] = None,
        on_tick: Optional[Callable[[PriceTick], None]] = None,
        tick_buffer_size: int = 10000,
        use_testnet: bool = False
    ):
        """
        Initialize Binance WebSocket client.
        
        Args:
            symbols: List of trading pairs (e.g., ['BTCUSDT', 'ETHUSDT'])
            on_tick: Callback function called on each new tick
            tick_buffer_size: Size of circular buffer for tick history
            use_testnet: Use Binance testnet instead of mainnet
        """
        self.symbols = symbols or ['BTCUSDT']
        self.on_tick = on_tick
        self.tick_buffer_size = tick_buffer_size
        self.base_url = self.BASE_WS_URL_TESTNET if use_testnet else self.BASE_WS_URL
        
        # Tick storage (circular buffer for memory efficiency)
        self.tick_buffer: Dict[str, deque] = {
            symbol: deque(maxlen=tick_buffer_size) for symbol in self.symbols
        }
        
        # Connection state
        self.ws = None
        self.running = False
        self.last_tick_time: Dict[str, float] = {}
        
        # Performance metrics
        self.tick_count = 0
        self.start_time = None
        self.reconnect_count = 0
    
    def _build_stream_url(self) -> str:
        """
        Build WebSocket URL for multiple streams.
        
        Returns:
            WebSocket URL with stream subscriptions
        """
        # Use trade streams for tick-by-tick data (lowest latency)
        streams = [f"{symbol.lower()}@trade" for symbol in self.symbols]
        stream_names = "/".join(streams)
        return f"{self.base_url}/{stream_names}"
    
    def _parse_trade_message(self, msg: Dict[str, Any]) -> Optional[PriceTick]:
        """
        Parse trade message from Binance WebSocket.
        
        Args:
            msg: Raw message dict from Binance
            
        Returns:
            PriceTick object or None if parse fails
        """
        try:
            return PriceTick(
                symbol=msg['s'],
                price=float(msg['p']),
                timestamp=msg['T'] / 1000.0,  # Convert ms to seconds
                volume=float(msg['q']),
                trade_id=msg['t']
            )
        except (KeyError, ValueError) as e:
            print(f"Error parsing trade message: {e}")
            return None
    
    async def _handle_message(self, message: str):
        """
        Handle incoming WebSocket message.
        
        Args:
            message: Raw WebSocket message string
        """
        try:
            msg = json.loads(message)
            
            # Parse trade data
            tick = self._parse_trade_message(msg)
            if tick is None:
                return
            
            # Store in buffer
            if tick.symbol in self.tick_buffer:
                self.tick_buffer[tick.symbol].append(tick)
                self.last_tick_time[tick.symbol] = tick.timestamp
                self.tick_count += 1
            
            # Callback for external handling (volatility updates, etc.)
            if self.on_tick:
                self.on_tick(tick)
                
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
        except Exception as e:
            print(f"Error handling message: {e}")
    
    async def connect(self):
        """
        Establish WebSocket connection and start receiving data.
        This is the main event loop for the WebSocket.
        """
        url = self._build_stream_url()
        self.running = True
        self.start_time = time.time()
        
        print(f"Connecting to Binance WebSocket: {url}")
        
        while self.running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self.ws = ws
                    print("Connected to Binance WebSocket")
                    
                    # Receive messages
                    async for message in ws:
                        if not self.running:
                            break
                        await self._handle_message(message)
                        
            except websockets.exceptions.ConnectionClosed:
                self.reconnect_count += 1
                print(f"Connection closed. Reconnecting... (attempt {self.reconnect_count})")
                await asyncio.sleep(1)
            except Exception as e:
                self.reconnect_count += 1
                print(f"WebSocket error: {e}. Reconnecting... (attempt {self.reconnect_count})")
                await asyncio.sleep(1)
    
    async def disconnect(self):
        """Gracefully disconnect from WebSocket."""
        self.running = False
        if self.ws:
            await self.ws.close()
        print("Disconnected from Binance WebSocket")
    
    def get_latest_tick(self, symbol: str) -> Optional[PriceTick]:
        """
        Get the most recent tick for a symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Latest PriceTick or None if no data
        """
        if symbol in self.tick_buffer and len(self.tick_buffer[symbol]) > 0:
            return self.tick_buffer[symbol][-1]
        return None
    
    def get_tick_history(self, symbol: str, n: int = None) -> list[PriceTick]:
        """
        Get recent tick history for a symbol.
        
        Args:
            symbol: Trading pair symbol
            n: Number of recent ticks to return (None = all)
            
        Returns:
            List of PriceTick objects
        """
        if symbol not in self.tick_buffer:
            return []
        
        buffer = self.tick_buffer[symbol]
        if n is None:
            return list(buffer)
        else:
            return list(buffer)[-n:]
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get performance statistics.
        
        Returns:
            Dictionary with performance metrics
        """
        uptime = time.time() - self.start_time if self.start_time else 0
        ticks_per_second = self.tick_count / uptime if uptime > 0 else 0
        
        return {
            "uptime_seconds": uptime,
            "total_ticks": self.tick_count,
            "ticks_per_second": ticks_per_second,
            "reconnect_count": self.reconnect_count,
            "symbols": self.symbols,
            "last_tick_times": self.last_tick_time.copy(),
            "buffer_sizes": {s: len(self.tick_buffer[s]) for s in self.symbols}
        }


# Convenience function for simple usage
async def stream_btc_price(
    on_tick: Callable[[PriceTick], None],
    symbols: list[str] = None
) -> BinanceWebSocket:
    """
    Start streaming BTC (or other crypto) prices from Binance.
    
    Args:
        on_tick: Callback function for each new tick
        symbols: List of symbols to stream (default: ['BTCUSDT'])
        
    Returns:
        BinanceWebSocket instance
        
    Example:
        async def handle_tick(tick: PriceTick):
            print(f"BTC: ${tick.price:.2f}")
        
        ws = await stream_btc_price(handle_tick)
        # ... later ...
        await ws.disconnect()
    """
    if symbols is None:
        symbols = ['BTCUSDT']
    
    ws = BinanceWebSocket(symbols=symbols, on_tick=on_tick)
    
    # Start connection in background
    asyncio.create_task(ws.connect())
    
    # Give it a moment to connect
    await asyncio.sleep(0.5)
    
    return ws


# Simple example/test function
async def print_btc_ticks(duration: int = 10):
    """
    Print BTC ticks for a specified duration (for testing).
    
    Args:
        duration: How many seconds to run
    """
    tick_count = [0]  # Use list for closure
    
    def on_tick(tick: PriceTick):
        tick_count[0] += 1
        print(f"[{tick_count[0]}] {tick.symbol}: ${tick.price:.2f} @ {datetime.fromtimestamp(tick.timestamp)}")
    
    ws = await stream_btc_price(on_tick)
    
    print(f"Streaming BTC prices for {duration} seconds...")
    await asyncio.sleep(duration)
    
    await ws.disconnect()
    stats = ws.get_statistics()
    print(f"\nStatistics: {stats}")


if __name__ == "__main__":
    # Test the WebSocket connection
    asyncio.run(print_btc_ticks(duration=10))
