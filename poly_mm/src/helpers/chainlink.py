"""
Chainlink price feed helper functions for HFT market making.
Optimized for low-latency access with caching and async support.

For HFT strategies:
- Use Binance WebSocket as primary price source (10-50ms latency)
- Use Chainlink as backup/validation only (100-500ms latency)
- Poll Chainlink in background, don't block on-chain reads in hot path
"""

from web3 import Web3
from typing import Dict, Optional, Any
from dataclasses import dataclass
import os
import time
import asyncio
import threading
from datetime import datetime

# Chainlink Price Feed Contract ABI (minimal - only need latestRoundData)
CHAINLINK_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Chainlink Price Feed Addresses on Ethereum Mainnet
PRICE_FEEDS = {
    "BTC": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",  # BTC/USD
    "ETH": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",  # ETH/USD
    "SOL": "0x4ffC43a60e009B551865A93d232E33Fce9f01507",  # SOL/USD
    "XRP": "0xCed2660c6Dd1Ffd856A5A82C67f3482d88C50b12",  # XRP/USD
}


@dataclass
class ChainlinkPrice:
    """Cached price data from Chainlink with metadata."""
    price: float
    timestamp: float  # Unix timestamp when fetched
    round_id: int
    updated_at: int  # On-chain update timestamp
    
    def age_seconds(self) -> float:
        """Get age of cached price in seconds."""
        return time.time() - self.timestamp
    
    def is_stale(self, max_age: float = 30.0) -> bool:
        """Check if price is stale (default: 30 seconds)."""
        return self.age_seconds() > max_age


class ChainlinkPriceFeed:
    """
    HFT-optimized Chainlink price feed client.
    
    Features:
    - Price caching to avoid repeated RPC calls
    - Background polling for non-blocking updates
    - Stale data detection for latency monitoring
    - Pre-initialized contracts for fast access
    
    For HFT: Use as backup/validation only. Primary prices from Binance WebSocket.
    """
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        cache_ttl: float = 12.0,  # Cache for 12 seconds (Ethereum block time)
        auto_refresh: bool = False,
        refresh_interval: float = 12.0
    ):
        """
        Initialize the Chainlink price feed client.
        
        Args:
            rpc_url: Ethereum RPC URL. If None, uses ETH_RPC_URL env var.
            cache_ttl: Time-to-live for cached prices in seconds
            auto_refresh: Enable background price refresh thread
            refresh_interval: How often to refresh prices in background (seconds)
        """
        if rpc_url is None:
            rpc_url = os.getenv("ETH_RPC_URL", "https://eth.llamarpc.com")
        
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(f"Failed to connect to Ethereum node at {rpc_url}")
        
        self.cache_ttl = cache_ttl
        self.refresh_interval = refresh_interval
        
        # Pre-initialize contracts for all feeds (avoid repeated setup)
        self._contracts: Dict[str, Any] = {}
        self._decimals: Dict[str, int] = {}
        self._init_contracts()
        
        # Price cache: {symbol: ChainlinkPrice}
        self._price_cache: Dict[str, ChainlinkPrice] = {}
        self._cache_lock = threading.Lock()
        
        # Background refresh thread
        self._refresh_thread = None
        self._stop_refresh = threading.Event()
        if auto_refresh:
            self.start_background_refresh()
    
    def _init_contracts(self):
        """Pre-initialize all contract instances and cache decimals."""
        for symbol, address in PRICE_FEEDS.items():
            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(address),
                abi=CHAINLINK_ABI
            )
            self._contracts[symbol] = contract
            # Cache decimals (they never change)
            self._decimals[symbol] = contract.functions.decimals().call()
    
    def _fetch_price_from_feed(self, symbol: str) -> ChainlinkPrice:
        """
        Fetch fresh price from Chainlink (blocking RPC call).
        
        Args:
            symbol: Crypto symbol (BTC, ETH, SOL, XRP)
            
        Returns:
            ChainlinkPrice object with fresh data
        """
        contract = self._contracts[symbol]
        decimals = self._decimals[symbol]
        
        # Get latest price data (this is the blocking RPC call)
        latest_data = contract.functions.latestRoundData().call()
        
        price_raw = latest_data[1]  # answer
        price = price_raw / (10 ** decimals)
        
        return ChainlinkPrice(
            price=price,
            timestamp=time.time(),
            round_id=latest_data[0],
            updated_at=latest_data[3]
        )
    
    def _get_cached_or_fetch(self, symbol: str, force_refresh: bool = False) -> ChainlinkPrice:
        """
        Get price from cache or fetch if stale.
        
        Args:
            symbol: Crypto symbol
            force_refresh: Force fetch even if cache is fresh
            
        Returns:
            ChainlinkPrice object
        """
        with self._cache_lock:
            # Check cache first
            if not force_refresh and symbol in self._price_cache:
                cached = self._price_cache[symbol]
                if not cached.is_stale(self.cache_ttl):
                    return cached
        
        # Cache miss or stale - fetch fresh data
        fresh_price = self._fetch_price_from_feed(symbol)
        
        with self._cache_lock:
            self._price_cache[symbol] = fresh_price
        
        return fresh_price
    
    def _background_refresh_loop(self):
        """Background thread loop for refreshing prices."""
        while not self._stop_refresh.is_set():
            try:
                # Refresh all symbols
                for symbol in PRICE_FEEDS.keys():
                    if self._stop_refresh.is_set():
                        break
                    self._get_cached_or_fetch(symbol, force_refresh=True)
            except Exception as e:
                print(f"Chainlink background refresh error: {e}")
            
            # Wait for next refresh
            self._stop_refresh.wait(self.refresh_interval)
    
    def start_background_refresh(self):
        """Start background price refresh thread."""
        if self._refresh_thread is None or not self._refresh_thread.is_alive():
            self._stop_refresh.clear()
            self._refresh_thread = threading.Thread(
                target=self._background_refresh_loop,
                daemon=True
            )
            self._refresh_thread.start()
    
    def stop_background_refresh(self):
        """Stop background price refresh thread."""
        self._stop_refresh.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=2.0)
    
    # Public API methods
    
    def get_btc_price(self, cached: bool = True) -> float:
        """
        Get BTC/USD price.
        
        Args:
            cached: Use cached price if available (fast, <1ms)
                   False = force fresh fetch (slow, 100-500ms)
        
        Returns:
            BTC price in USD
        """
        return self._get_cached_or_fetch("BTC", force_refresh=not cached).price
    
    def get_eth_price(self, cached: bool = True) -> float:
        """
        Get ETH/USD price.
        
        Args:
            cached: Use cached price if available
        
        Returns:
            ETH price in USD
        """
        return self._get_cached_or_fetch("ETH", force_refresh=not cached).price
    
    def get_sol_price(self, cached: bool = True) -> float:
        """
        Get SOL/USD price.
        
        Args:
            cached: Use cached price if available
        
        Returns:
            SOL price in USD
        """
        return self._get_cached_or_fetch("SOL", force_refresh=not cached).price
    
    def get_xrp_price(self, cached: bool = True) -> float:
        """
        Get XRP/USD price.
        
        Args:
            cached: Use cached price if available
        
        Returns:
            XRP price in USD
        """
        return self._get_cached_or_fetch("XRP", force_refresh=not cached).price
    
    def get_all_prices(self, cached: bool = True) -> Dict[str, float]:
        """
        Get all cryptocurrency prices.
        
        Args:
            cached: Use cached prices if available
        
        Returns:
            Dictionary with symbols as keys and prices as values
        """
        return {
            "BTC": self.get_btc_price(cached=cached),
            "ETH": self.get_eth_price(cached=cached),
            "SOL": self.get_sol_price(cached=cached),
            "XRP": self.get_xrp_price(cached=cached),
        }
    
    def get_btc_price_with_metadata(self, cached: bool = True) -> ChainlinkPrice:
        """Get BTC price with full metadata (age, round_id, etc.)."""
        return self._get_cached_or_fetch("BTC", force_refresh=not cached)
    
    def get_eth_price_with_metadata(self, cached: bool = True) -> ChainlinkPrice:
        """Get ETH price with full metadata."""
        return self._get_cached_or_fetch("ETH", force_refresh=not cached)
    
    def get_sol_price_with_metadata(self, cached: bool = True) -> ChainlinkPrice:
        """Get SOL price with full metadata."""
        return self._get_cached_or_fetch("SOL", force_refresh=not cached)
    
    def get_xrp_price_with_metadata(self, cached: bool = True) -> ChainlinkPrice:
        """Get XRP price with full metadata."""
        return self._get_cached_or_fetch("XRP", force_refresh=not cached)
    
    def clear_cache(self):
        """Clear all cached prices (force fresh fetch on next call)."""
        with self._cache_lock:
            self._price_cache.clear()
    
    def get_cache_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get cache statistics for monitoring.
        
        Returns:
            Dictionary with cache info for each symbol
        """
        stats = {}
        with self._cache_lock:
            for symbol, cached_price in self._price_cache.items():
                stats[symbol] = {
                    "price": cached_price.price,
                    "age_seconds": cached_price.age_seconds(),
                    "is_stale": cached_price.is_stale(self.cache_ttl),
                    "round_id": cached_price.round_id,
                    "updated_at": datetime.fromtimestamp(cached_price.updated_at).isoformat()
                }
        return stats


# Singleton instance for convenience (with background refresh enabled)
_default_client: Optional[ChainlinkPriceFeed] = None


def get_default_client() -> ChainlinkPriceFeed:
    """Get or create default Chainlink client with background refresh."""
    global _default_client
    if _default_client is None:
        _default_client = ChainlinkPriceFeed(auto_refresh=True)
    return _default_client


# Convenience functions (now use cached singleton)
def get_btc_price(cached: bool = True) -> float:
    """
    Get BTC/USD price from Chainlink.
    
    Args:
        cached: Use cached value (fast, <1ms) vs fresh fetch (slow, 100-500ms)
    
    Returns:
        BTC price in USD
    """
    return get_default_client().get_btc_price(cached=cached)


def get_eth_price(cached: bool = True) -> float:
    """Get ETH/USD price from Chainlink."""
    return get_default_client().get_eth_price(cached=cached)


def get_sol_price(cached: bool = True) -> float:
    """Get SOL/USD price from Chainlink."""
    return get_default_client().get_sol_price(cached=cached)


def get_xrp_price(cached: bool = True) -> float:
    """Get XRP/USD price from Chainlink."""
    return get_default_client().get_xrp_price(cached=cached)


def get_all_prices(cached: bool = True) -> Dict[str, float]:
    """Get all cryptocurrency prices from Chainlink."""
    return get_default_client().get_all_prices(cached=cached)


async def async_get_btc_price(cached: bool = True) -> float:
    """
    Async wrapper for BTC price (runs in thread pool to avoid blocking event loop).
    
    For HFT: Use this in your async main loop to avoid blocking.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_btc_price, cached)


async def async_get_all_prices(cached: bool = True) -> Dict[str, float]:
    """Async wrapper for all prices."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_all_prices, cached)
