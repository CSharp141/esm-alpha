"""
Polymarket integration helper functions.

Handles all Polymarket-specific logic:
- Market data fetching
- Order placement/cancellation
- Position tracking
- Market parsing (extract strike prices, expiry times)

Dependencies:
    pip install py-clob-client requests
Docs:
    Quickstart (Python first trade): https://docs.polymarket.com/quickstart/orders/first-order
    Get markets (CLOB):             https://docs.polymarket.com/developers/CLOB/markets/get-markets
    Get book (CLOB):                https://docs.polymarket.com/developers/CLOB/prices-books/get-book
    Cancel orders:                  https://docs.polymarket.com/developers/CLOB/orders/cancel-orders
    Positions (Data API):           https://docs.polymarket.com/developers/CLOB/endpoints  (data-api)
"""

from typing import Optional, Dict, List, Any, Tuple, Union
from dataclasses import dataclass
from datetime import datetime, timezone
import time
import re
import json
import requests

# ---- Polymarket client libs
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL


CLOB_HOST = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

# Map asset → slug prefix for 15-minute Up/Down markets
ASSET_SLUG_PREFIX = {
    "BTC": "btc-updown-15m-",
    "ETH": "eth-updown-15m-",
    "SOL": "sol-updown-15m-",
    "XRP": "xrp-updown-15m-",
}


@dataclass
class PolymarketMarket:
    """
    Represents a Polymarket binary market.

    For 15-minute up/down markets like:
    "Will BTC be above $67,000 at 3:15 PM UTC?"
    """
    market_id: str                 # condition_id
    question: str
    strike_price: float            # Threshold price to beat
    expiry_time: float             # Unix timestamp (market end)
    
    # Slug for predictive next market discovery
    slug: Optional[str] = None
    
    # Market start time (for precise strike price capture)
    start_time: Optional[float] = None  # Unix timestamp (market start)

    # Token IDs (ERC-1155) for each outcome
    yes_token_id: Optional[str] = None
    no_token_id: Optional[str] = None

    # Current market prices
    yes_bid: Optional[float] = None  # Best bid for YES
    yes_ask: Optional[float] = None  # Best ask for YES
    no_bid: Optional[float] = None   # Best bid for NO
    no_ask: Optional[float] = None   # Best ask for NO

    # Volume/liquidity (top-of-book sizes if available)
    yes_bid_size: Optional[float] = None
    yes_ask_size: Optional[float] = None
    no_bid_size: Optional[float] = None
    no_ask_size: Optional[float] = None

    # Optional totals from book summary (if you later extend)
    yes_volume: float = 0.0
    no_volume: float = 0.0

    def minutes_to_expiry(self) -> float:
        """Calculate minutes remaining to expiry."""
        seconds_remaining = self.expiry_time - time.time()
        return max(0.0, seconds_remaining / 60.0)
    
    def seconds_to_start(self) -> float:
        """Calculate seconds until market start (negative if already started)."""
        if self.start_time is None:
            return 0.0
        return self.start_time - time.time()
    
    def has_started(self) -> bool:
        """Check if market has started."""
        if self.start_time is None:
            return True  # Assume started if no start time
        return time.time() >= self.start_time

    def is_expired(self) -> bool:
        """Check if market has expired."""
        return time.time() >= self.expiry_time

    def to_dict(self) -> Dict:
        """Convert to dictionary for logging."""
        return {
            "market_id": self.market_id,
            "question": self.question,
            "strike_price": self.strike_price,
            "expiry_time": datetime.fromtimestamp(self.expiry_time).isoformat(),
            "minutes_to_expiry": round(self.minutes_to_expiry(), 2),
            "yes_token_id": self.yes_token_id,
            "no_token_id": self.no_token_id,
            "yes_bid": self.yes_bid,
            "yes_ask": self.yes_ask,
            "no_bid": self.no_bid,
            "no_ask": self.no_ask,
            "yes_bid_size": self.yes_bid_size,
            "yes_ask_size": self.yes_ask_size,
            "no_bid_size": self.no_bid_size,
            "no_ask_size": self.no_ask_size,
        }


@dataclass
class Position:
    """Current position in a Polymarket market."""
    market_id: str
    yes_quantity: float  # Positive = long YES, negative = short YES
    no_quantity: float   # Positive = long NO, negative = short NO
    avg_yes_price: float = 0.0
    avg_no_price: float = 0.0

    def net_exposure(self) -> float:
        """
        Calculate net delta exposure.

        Positive = long UP/YES, negative = long DOWN/NO
        """
        return self.yes_quantity - self.no_quantity

    def total_risk(self) -> float:
        """Total capital at risk."""
        return abs(self.yes_quantity) + abs(self.no_quantity)


class PolymarketClient:
    """
    Client for interacting with Polymarket.

    Wraps the official CLOB Python client (signing + orders) and hits
    REST & Data API for markets, books, and positions.
    """

    def __init__(
        self,
        api_private_key: str,
        signature_type: Optional[int] = None,
        funder_address: Optional[str] = None,
        chain_id: int = 137,
        clob_host: str = CLOB_HOST,
        data_api: str = DATA_API,
        session: Optional[requests.Session] = None,
    ):
        """
        Initialize Polymarket client.

        Args:
            api_private_key: Polygon private key controlling funds (or EOA)
            signature_type: 1 (Magic/email proxy) or 2 (browser wallet proxy) or None (EOA)
            funder_address: Proxy/funder address shown on profile (if using proxy)
            chain_id: 137 (Polygon mainnet)
            clob_host: CLOB REST host
            data_api: Data API base
            session: optional requests.Session for reuse
        """
        self.api_key = api_private_key
        self.funder = funder_address
        self.testnet = False
        self.clob_host = clob_host
        self.data_api = data_api
        self.http = session or requests.Session()

        # ---- Underlying signed client (per quickstart)
        if signature_type in (1, 2):
            self._clob = ClobClient(
                clob_host, key=api_private_key, chain_id=chain_id,
                signature_type=signature_type, funder=funder_address
            )
        else:
            # EOA direct
            self._clob = ClobClient(clob_host, key=api_private_key, chain_id=chain_id)

        # create (or derive) API creds for L2
        self._clob.set_api_creds(self._clob.create_or_derive_api_creds())

        # Cache of active markets keyed by condition_id
        self._markets: Dict[str, PolymarketMarket] = {}

        # Positions cache (optional; you can keep it fresh externally)
        self._positions: Dict[str, Position] = {}
    
    @classmethod
    def from_config(cls, config):
        """
        Create PolymarketClient from Config object.
        
        Args:
            config: PolymarketConfig instance or Config with .polymarket attribute
            
        Returns:
            PolymarketClient instance
            
        Example:
            from config import get_config
            config = get_config()
            client = PolymarketClient.from_config(config.polymarket)
        """
        # Handle both PolymarketConfig and Config objects
        if hasattr(config, 'polymarket'):
            config = config.polymarket
        
        return cls(
            api_private_key=config.private_key,
            signature_type=config.signature_type,
            funder_address=config.funder_address,
            chain_id=config.chain_id,
            clob_host=config.clob_host,
            data_api=config.data_api
        )

    # ---------- Market discovery ----------
    
    # Tag mappings for fast market filtering
    # Based on Polymarket's tag system for crypto 15-minute markets
    CRYPTO_TAGS = {
        "BTC": ["15M", "up-or-down", "crypto-prices", "bitcoin", "crypto"],
        "ETH": ["15M", "up-or-down", "crypto-prices", "ethereum", "crypto"],
        "SOL": ["15M", "up-or-down", "crypto-prices", "solana", "crypto"],
        "XRP": ["15M", "up-or-down", "crypto-prices", "ripple", "crypto"],
    }

    @staticmethod
    def _format_expiry_time(expiry_timestamp: float) -> str:
        """
        Format expiry time to show both UTC and local timezone.
        
        Args:
            expiry_timestamp: Unix timestamp of market expiry
            
        Returns:
            Formatted string like "23:45 UTC (00:45 local)"
        """
        try:
            utc_time = datetime.fromtimestamp(expiry_timestamp, tz=timezone.utc)
            local_time = datetime.fromtimestamp(expiry_timestamp)
            
            utc_str = utc_time.strftime("%H:%M UTC")
            local_str = local_time.strftime("%H:%M")
            
            # Only show local if different from UTC
            if utc_time.hour == local_time.hour and utc_time.minute == local_time.minute:
                return utc_str
            else:
                return f"{utc_str} ({local_str} local)"
        except Exception:
            return f"timestamp {expiry_timestamp}"

    @staticmethod
    def _current_15m_boundary_ts(now_s: Optional[int] = None) -> int:
        """
        Calculate the current 15-minute boundary timestamp (market that's live now).
        
        Args:
            now_s: Current timestamp (defaults to now)
            
        Returns:
            Unix timestamp of current 15-minute boundary (rounds down)
        """
        now = int(now_s or time.time())
        return (now // 900) * 900  # 900 = 15*60
    
    @staticmethod
    def _next_15m_boundary_ts(now_s: Optional[int] = None) -> int:
        """
        Calculate the next 15-minute boundary timestamp.
        
        Args:
            now_s: Current timestamp (defaults to now)
            
        Returns:
            Unix timestamp of next 15-minute boundary
        """
        now = int(now_s or time.time())
        return ((now // 900) + 1) * 900  # 900 = 15*60
    
    @staticmethod
    def _extract_timestamp_from_slug(slug: str) -> Optional[int]:
        """
        Extract timestamp from a market slug.
        
        Args:
            slug: Market slug like 'btc-updown-15m-1762811100'
            
        Returns:
            Unix timestamp (e.g., 1762811100) or None if not found
        """
        try:
            # Slug format: {asset}-updown-15m-{timestamp}
            parts = slug.split('-')
            if len(parts) >= 4 and parts[-2] == '15m':
                return int(parts[-1])
        except (ValueError, IndexError):
            pass
        return None
    
    @staticmethod
    def _predict_next_market_slug(current_slug: str) -> Optional[str]:
        """
        Predict the next market slug by incrementing timestamp by 900 seconds.
        
        Args:
            current_slug: Current market slug like 'btc-updown-15m-1762811100'
            
        Returns:
            Next market slug like 'btc-updown-15m-1762812000' or None if parse fails
        """
        current_ts = PolymarketClient._extract_timestamp_from_slug(current_slug)
        if current_ts is None:
            return None
        
        next_ts = current_ts + 900  # Add 15 minutes
        
        # Reconstruct slug with new timestamp
        parts = current_slug.rsplit('-', 1)  # Split from right, once
        if len(parts) == 2:
            return f"{parts[0]}-{next_ts}"
        return None
    
    @staticmethod
    def _split_clob_token_ids(raw: str) -> Tuple[str, str]:
        """
        Parse clobTokenIds which can be:
          - "123,456" (comma-separated string)
          - '["123","456"]' (JSON array)
          
        Returns:
            Tuple of (yes_token_id, no_token_id)
        """
        raw = (raw or "").strip()
        if not raw:
            raise ValueError("Missing clobTokenIds")

        if raw.startswith("["):
            arr = json.loads(raw)
            if len(arr) != 2:
                raise ValueError(f"Unexpected clobTokenIds array: {raw}")
            return str(arr[0]), str(arr[1])

        # comma-separated string
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) != 2:
            raise ValueError(f"Unexpected clobTokenIds string: {raw}")
        return parts[0], parts[1]
    
    def _event_to_market(self, evt_json: dict, asset: str) -> Optional[PolymarketMarket]:
        """
        Convert Gamma Events API response to PolymarketMarket.
        
        Args:
            evt_json: Event JSON from Gamma API
            asset: Asset ticker (BTC, ETH, SOL, XRP)
            
        Returns:
            PolymarketMarket or None if parsing fails
        """
        try:
            markets = evt_json.get("markets") or []
            if not markets:
                return None

            m = markets[0]  # 15m events have a single binary market
            condition_id = m.get("conditionId")
            if not condition_id:
                return None
            
            # Get end date
            end_iso = m.get("endDate") or evt_json.get("endDate")
            if end_iso:
                expiry_time = datetime.fromisoformat(end_iso.replace('Z', '+00:00')).timestamp()
            else:
                return None
            
            # Get question
            question = m.get("question") or evt_json.get("title") or ""
            
            # Parse token IDs
            yes_id, no_id = self._split_clob_token_ids(m.get("clobTokenIds", ""))
            
            # Get slug for predictive next market discovery
            slug = evt_json.get("slug")
            
            # Calculate market start time (15-minute markets: expiry - 900 seconds)
            start_time = expiry_time - 900  # 900 seconds = 15 minutes
            
            # For Up/Down markets, the strike is the Chainlink price at market open.
            # API doesn't provide this, so we'll need to set it later from current spot.
            # Using None as marker that it needs to be filled from pricing engine.
            strike_price = None
            
            market = PolymarketMarket(
                market_id=condition_id,
                question=question,
                strike_price=strike_price,
                expiry_time=expiry_time,
                start_time=start_time,
                slug=slug,
                yes_token_id=yes_id,
                no_token_id=no_id,
            )
            
            # Fetch order book data
            start_time = time.time()
            self._update_market_book(market)

            end_time = time.time()
            elapsed = end_time - start_time
            print(f"  ⏱️  Book query took {elapsed:.2f} seconds")
            
            return market
            
        except Exception as e:
            print(f"[Warning] Failed to parse event: {e}")
            return None
    
    def _update_market_book(self, market: PolymarketMarket):
        """
        Update market with current order book data from CLOB.
        
        Args:
            market: PolymarketMarket to update
        """
        try:
            # Get YES book
            yes_book = self.http.get(
                f"{self.clob_host}/book",
                params={"token_id": market.yes_token_id},
                timeout=5
            ).json()
            
            if yes_book.get("bids"):
                market.yes_bid = float(yes_book["bids"][-1]["price"])
                market.yes_bid_size = float(yes_book["bids"][-1]["size"])
            if yes_book.get("asks"):
                market.yes_ask = float(yes_book["asks"][-1]["price"])
                market.yes_ask_size = float(yes_book["asks"][-1]["size"])

            # Get NO book
            no_book = self.http.get(
                f"{self.clob_host}/book",
                params={"token_id": market.no_token_id},
                timeout=5
            ).json()
            
            if no_book.get("bids"):
                market.no_bid = float(no_book["bids"][-1]["price"])
                market.no_bid_size = float(no_book["bids"][-1]["size"])
            if no_book.get("asks"):
                market.no_ask = float(no_book["asks"][-1]["price"])
                market.no_ask_size = float(no_book["asks"][-1]["size"])

        except Exception as e:
            print(f"[Warning] Failed to fetch order book: {e}")
    
    def discover_next_15m_market_predictive(self, asset: str = "BTC") -> Optional[PolymarketMarket]:
        """
        Strategy C: Predict next 15-minute market by guessing the slug.
        
        Constructs slug as '{asset}-updown-15m-{next_boundary_timestamp}' and
        queries Gamma Events API. This is fast but only works if market is already live.
        
        Args:
            asset: Asset ticker (BTC, ETH, SOL, XRP)
            
        Returns:
            PolymarketMarket if found, None otherwise
        """
        prefix = ASSET_SLUG_PREFIX.get(asset.upper())
        if not prefix:
            return None
        
        # Guess the slug
        next_ts = self._next_15m_boundary_ts()
        slug = f"{prefix[:-1]}-{next_ts}"  # Remove trailing dash, add timestamp
        
        try:
            # Query Gamma Events API by slug
            resp = self.http.get(
                f"{GAMMA_API}/events/slug/{slug}",
                timeout=5
            )
            
            if resp.status_code != 200:
                return None
            
            return self._event_to_market(resp.json(), asset)
            
        except Exception as e:
            print(f"[Debug] Predictive strategy failed for {asset}: {e}")
            return None
    
    def discover_next_15m_market_scan(self, asset: str = "BTC") -> Optional[PolymarketMarket]:
        """
        Strategy A: Scan Gamma Events API for next upcoming 15-minute market.
        
        Queries /events with filters for crypto category and ascending end date,
        then finds the earliest event matching the asset slug prefix.
        
        Args:
            asset: Asset ticker (BTC, ETH, SOL, XRP)
            
        Returns:
            PolymarketMarket if found, None otherwise
        """
        prefix = ASSET_SLUG_PREFIX.get(asset.upper())
        if not prefix:
            return None
        
        try:
            # Query Gamma Events API with filters
            now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            params = {
                "order": "endDate",
                "ascending": "true",
                "limit": "200",
                "closed": "false",
                "category": "Crypto",
                "end_date_min": now_iso,
            }
            
            resp = self.http.get(f"{GAMMA_API}/events", params=params, timeout=10)
            resp.raise_for_status()
            events = resp.json()
            
            # Find first matching event
            for evt in events:
                slug = (evt.get("slug") or "").lower()
                if slug.startswith(prefix):
                    # Fetch full event details
                    evt_detail = self.http.get(
                        f"{GAMMA_API}/events/slug/{slug}",
                        timeout=5
                    ).json()
                    return self._event_to_market(evt_detail, asset)
            
            return None
            
        except Exception as e:
            print(f"[Warning] Scan strategy failed for {asset}: {e}")
            return None
    
    def discover_15m_market_by_slug(self, slug: str, asset: str = "BTC") -> Optional[PolymarketMarket]:
        """
        Discover a specific 15-minute market by its slug.
        
        Used for predictive discovery when you know the exact slug
        (e.g., predicted from previous market's slug).
        
        Args:
            slug: Market slug like 'btc-updown-15m-1762812000'
            asset: Asset ticker (BTC, ETH, SOL, XRP)
            
        Returns:
            PolymarketMarket if found, None otherwise
        """
        try:
            resp = self.http.get(
                f"{GAMMA_API}/events/slug/{slug}",
                timeout=5
            )
            
            if resp.status_code != 200:
                return None
            
            return self._event_to_market(resp.json(), asset)
            
        except Exception as e:
            print(f"[Debug] Slug lookup failed for {slug}: {e}")
            return None
    
    def discover_current_and_next_15m_markets(self, asset: str = "BTC") -> Tuple[Optional[PolymarketMarket], Optional[str]]:
        """
        Smart discovery: Find CURRENT live market and predict NEXT market slug.
        
        This is the recommended method for initial market discovery:
        1. Uses scan to find current live market
        2. Extracts timestamp from current market's slug
        3. Predicts next market's slug by adding 900 seconds
        
        Returns:
            Tuple of (current_market, next_market_slug)
            - current_market: The market that's live right now
            - next_market_slug: Predicted slug for the next 15m market
        
        Example:
            current, next_slug = client.discover_current_and_next_15m_markets("BTC")
            # Trade current market...
            # When it expires, use: next_market = client.discover_15m_market_by_slug(next_slug, "BTC")
        """
        # Find current live market using scan
        current_market = self.discover_next_15m_market_scan(asset)
        
        if current_market is None or current_market.slug is None:
            return None, None
        
        # Predict next market slug
        next_slug = self._predict_next_market_slug(current_market.slug)
        
        return current_market, next_slug

    def _iter_markets_pages(self, next_cursor: str = "", closed: bool = False):
        """
        Generator over paginated markets using Gamma Markets API.
        
        Args:
            next_cursor: Pagination cursor
            closed: Include closed markets (default: False, only active markets)
        """
        cursor = next_cursor or ""
        
        # Use Gamma Markets API which supports filtering for closed/active markets
        # CLOB API doesn't support this filtering
        gamma_api_url = f"{GAMMA_API}/markets"
        
        while True:
            try:
                # Use Gamma API with closed parameter
                params = {"closed": "true" if closed else "false"}
                if cursor:
                    params["next_cursor"] = cursor
                
                resp = self.http.get(gamma_api_url, params=params, timeout=10).json()
                
                # Gamma API returns list directly, not wrapped in {"data": [...]}
                if isinstance(resp, list):
                    data = resp
                    nc = ""  # No pagination for direct list response
                else:
                    data = resp.get("data", [])
                    nc = resp.get("next_cursor", "")
                
            except Exception as e:
                print(f"[Warning] Gamma API failed: {e}, falling back to CLOB API")
                # Fallback to CLOB API (but it returns all markets including closed)
                resp = self._clob.get_markets(next_cursor=cursor)
                data = resp.get("data", [])
                nc = resp.get("next_cursor", "")
            
            for m in data:
                yield m
                
            if not nc or nc == "LTE=":
                break
            cursor = nc

    def get_crypto_15min_markets(
        self, 
        assets: List[str] = ["BTC", "ETH", "SOL", "XRP"],
        max_markets_per_asset: int = 10,
        return_next_slugs: bool = False
    ) -> Union[List[PolymarketMarket], Tuple[List[PolymarketMarket], Dict[str, str]]]:
        """
        Fetch active 15-minute up/down markets for specific crypto assets.
        
        Uses smart discovery strategy:
        1. First call: Uses scan to find CURRENT live markets
        2. Extracts slug and predicts NEXT market for seamless transition
        3. Returns markets + next slugs for predictive discovery
        
        Args:
            assets: List of crypto tickers to fetch (default: BTC, ETH, SOL, XRP)
            max_markets_per_asset: Maximum markets to return per asset (default: 10)
            return_next_slugs: If True, also returns dict of {asset: next_slug}

        Returns:
            If return_next_slugs=False: List of PolymarketMarket
            If return_next_slugs=True: (List of PolymarketMarket, Dict of next slugs)
            
        Performance:
            - Initial scan: 2-3 seconds per asset (finds current market)
            - Subsequent calls: <1 second per asset (use predicted slugs)
        """
        results: List[PolymarketMarket] = []
        next_slugs: Dict[str, str] = {}
        
        for asset in assets:
            # Try current + next discovery (smart strategy)
            current_market, next_slug = self.discover_current_and_next_15m_markets(asset)
            
            if current_market:
                results.append(current_market)
                if next_slug:
                    next_slugs[asset] = next_slug
                
                expiry_str = self._format_expiry_time(current_market.expiry_time)
                mins_left = current_market.minutes_to_expiry()
                print(f"[{asset}] Found: {current_market.question}")
                print(f"       Expires: {expiry_str} ({mins_left:.1f} min remaining)")
                
                if next_slug:
                    next_ts = self._extract_timestamp_from_slug(next_slug)
                    if next_ts:
                        next_time_utc = datetime.fromtimestamp(next_ts, tz=timezone.utc).strftime("%H:%M UTC")
                        print(f"       Next market: {next_slug} (opens at {next_time_utc})")
            else:
                print(f"[{asset}] No active 15-minute market found")
        
        if return_next_slugs:
            return results, next_slugs
        return results
    
    def get_btc_15min_markets(self) -> List[PolymarketMarket]:
        """
        Fetch all active BTC 15-minute up/down markets.
        
        DEPRECATED: Use get_crypto_15min_markets(["BTC"]) instead.
        """
        return self.get_crypto_15min_markets(["BTC"])

    def get_market(self, market_id: str) -> Optional[PolymarketMarket]:
        """
        Get current state of a specific market by condition_id.
        """
        # return from cache if present & not expired
        cached = self._markets.get(market_id)
        if cached and not cached.is_expired():
            # refresh top-of-book
            self._update_market_book(cached)
            return cached

        # otherwise, scan markets and find condition_id
        for m in self._iter_markets_pages():
            if m.get("condition_id") == market_id:
                question = m.get("question", "")
                end_iso = m.get("end_date_iso")
                if not (question and end_iso):
                    return None

                strike = self.parse_strike_from_question(question)
                expiry_ts = self.parse_expiry_from_question(question, {"end_date_iso": end_iso})
                yes_id, no_id = self._extract_yes_no_token_ids(m.get("tokens", []))

                pm = PolymarketMarket(
                    market_id=market_id,
                    question=question,
                    strike_price=strike if strike is not None else 0.0,
                    expiry_time=expiry_ts,
                    yes_token_id=yes_id,
                    no_token_id=no_id,
                )
                self._update_market_book(pm)
                self._markets[pm.market_id] = pm
                return pm

        return None

    def get_orderbook(self, market_id: str) -> Dict[str, Any]:
        """
        Get full top-of-book for a market (YES & NO tokens).

        Returns dict with bids/asks arrays for YES and NO.
        """
        pm = self.get_market(market_id)
        if not pm or not (pm.yes_token_id and pm.no_token_id):
            raise ValueError(f"Unknown market or token IDs not found for {market_id}")

        yes_book = self._clob.get_order_book(pm.yes_token_id)
        no_book = self._clob.get_order_book(pm.no_token_id)

        return {
            "market_id": market_id,
            "question": pm.question,
            "yes": yes_book,
            "no": no_book,
        }

    # ---------- Trading ----------

    def place_order(
        self,
        market_id: str,
        side: str,        # "YES" or "NO"
        direction: str,   # "BUY" or "SELL"
        price: float,     # Limit price [0, 1]
        quantity: float,  # Size (shares)
        tif: OrderType = OrderType.GTC,
        negrisk: Optional[bool] = None,
    ) -> str:
        """
        Place a signed limit order on Polymarket.

        Args:
            market_id: Condition ID
            side: "YES" or "NO"
            direction: "BUY" or "SELL"
            price: 0..1
            quantity: size in shares
            tif: OrderType (GTC, IOC, FOK if supported)
            negrisk: Optional flag for negative risk markets

        Returns:
            Order ID (hex string)
        """
        pm = self.get_market(market_id)
        if not pm:
            raise ValueError(f"Market not found: {market_id}")

        token_id = pm.yes_token_id if side.upper() == "YES" else pm.no_token_id
        if not token_id:
            raise ValueError("Token id missing for requested side.")

        clob_side = BUY if direction.upper() == "BUY" else SELL

        args = OrderArgs(
            price=float(price),
            size=float(quantity),
            side=clob_side,
            token_id=token_id,
            # if you trade neg-risk markets, pass correct flag:
            negrisk=negrisk if negrisk is not None else False,
        )
        signed = self._clob.create_order(args)
        resp = self._clob.post_order(signed, tif)  # returns dict with 'order_id'
        order_id = resp.get("order_id") or resp.get("id") or ""
        if not order_id:
            raise RuntimeError(f"Order placement response missing id: {resp}")
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a single open order.

        Returns True if API reports it was canceled.
        """
        resp = self._clob.cancel(order_id=order_id)
        canceled = resp.get("canceled") or []
        return order_id in canceled

    # ---------- Positions ----------

    def get_position(self, market_id: str) -> Position:
        """
        Get current (net) position in a market using the Data API /positions.

        We look up the caller's proxy/funder (if present) or the EOA address
        derived by py-clob-client, and filter by condition_id = market_id.
        """
        user_addr = self._resolve_user_address()
        if not user_addr:
            raise ValueError(
                "Cannot resolve user address. Provide funder_address for proxy "
                "or use an EOA key."
            )

        params = {
            "user": user_addr,
            "condition_ids": market_id,  # filter a single market
        }
        url = f"{self.data_api}/positions"
        r = self.http.get(url, params=params, timeout=10)
        r.raise_for_status()
        rows = r.json() if r.content else []

        yes_qty = 0.0
        no_qty = 0.0
        yes_avg = 0.0
        no_avg = 0.0

        # The Data API returns per-asset (YES/NO) entries with 'asset', 'size', 'avgPrice', 'outcome'
        # We'll aggregate.
        for row in rows:
            if row.get("conditionId") != market_id:
                continue
            outcome = (row.get("outcome") or "").lower()
            size = float(row.get("size") or 0.0)
            avg = float(row.get("avgPrice") or 0.0)

            if outcome == "yes":
                yes_qty += size
                yes_avg = avg  # overwrite with latest average; adjust if you prefer wtd avg
            elif outcome == "no":
                no_qty += size
                no_avg = avg

        pos = Position(market_id=market_id, yes_quantity=yes_qty, no_quantity=no_qty,
                       avg_yes_price=yes_avg, avg_no_price=no_avg)
        # update cache
        self._positions[market_id] = pos
        return pos

    # ---------- Parsing helpers ----------

    @staticmethod
    def parse_strike_from_question(question: str) -> Optional[float]:
        """
        Extract strike price from market question.

        Examples:
            "Will BTC be above $67,000 at 3:15 PM?" -> 67000.0
            "Will Bitcoin be above $67500.50?" -> 67500.50
        """
        pattern = r"\$([0-9,]+(?:\.[0-9]+)?)"
        match = re.search(pattern, question)
        if not match:
            return None
        price_str = match.group(1).replace(",", "")
        try:
            return float(price_str)
        except ValueError:
            return None

    @staticmethod
    def parse_expiry_from_question(question: str, market_metadata: Dict = None) -> Optional[float]:
        """
        Prefer API metadata end_date_iso, fallback to None.

        market_metadata may contain 'end_date_iso' (ISO string).
        """
        if market_metadata:
            iso = market_metadata.get("end_date_iso") or market_metadata.get("endDate") \
                  or market_metadata.get("end_date")
            if iso:
                try:
                    # end_date_iso is already UTC ISO 8601
                    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                    return dt.timestamp()
                except Exception:
                    pass
        return None

    # ---------- Internal utilities ----------

    @staticmethod
    def _extract_yes_no_token_ids(tokens: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
        yes_id = None
        no_id = None
        for t in tokens or []:
            outcome = (t.get("outcome") or "").lower()
            if outcome == "yes":
                yes_id = t.get("token_id")
            elif outcome == "no":
                no_id = t.get("token_id")
        return yes_id, no_id

    def _fill_top_of_book(self, pm: PolymarketMarket) -> PolymarketMarket:
        """
        Fill best bid/ask + sizes for YES and NO using /book for each token_id.
        
        DEPRECATED: Use _update_market_book instead (modifies in place).
        Kept for backward compatibility.
        """
        self._update_market_book(pm)
        return pm

    def _resolve_user_address(self) -> Optional[str]:
        """
        Determine the address to query Data API with:
          - If using proxy, it's the funder/proxy address you pass at init.
          - Else, use underlying client's address (owner of the private key).
        """
        if self.funder:
            return self.funder
        # py-clob-client exposes an address on the underlying signer
        try:
            # Not part of public docs; best-effort
            return getattr(self._clob, "address", None)
        except Exception:
            return None


# ---------- Sizing helper (unchanged except minor typing) ----------

def calculate_sizing_from_probabilities(
    fair_prob_up: float,
    fair_prob_down: float,
    market_prob_up: float,
    market_prob_down: float,
    edge_threshold: float = 0.02,  # Minimum 2% edge to trade
    max_size: float = 100.0,
    sizing_factor: float = 10.0,   # Size multiplier based on edge
) -> Dict[str, Optional[float]]:
    """
    Calculate position sizes based on probability edge.

    Example:
        Fair: UP=75%, DOWN=25%
        Market: UP=70%, DOWN=30%
        -> Buy YES (market underpricing UP by 5%)
    """
    edge_up = float(fair_prob_up) - float(market_prob_up)
    edge_down = float(fair_prob_down) - float(market_prob_down)

    sizing: Dict[str, Optional[float]] = {
        "buy_yes": None,
        "sell_yes": None,
        "buy_no": None,
        "sell_no": None,
    }

    # Buy YES if market is underpricing UP
    if edge_up > edge_threshold:
        size = min(max_size, edge_up * sizing_factor)
        sizing["buy_yes"] = size
    # Sell YES if market is overpricing UP
    elif edge_up < -edge_threshold:
        size = min(max_size, abs(edge_up) * sizing_factor)
        sizing["sell_yes"] = size

    # Buy NO if market is underpricing DOWN
    if edge_down > edge_threshold:
        size = min(max_size, edge_down * sizing_factor)
        sizing["buy_no"] = size
    # Sell NO if market is overpricing DOWN
    elif edge_down < -edge_threshold:
        size = min(max_size, abs(edge_down) * sizing_factor)
        sizing["sell_no"] = size

    return sizing
