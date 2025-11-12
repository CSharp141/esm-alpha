"""
HFT Pricing Engine for Polymarket Binary Options Market Making.

Implements:
- Black-Scholes probability model for binary options
- EWMA volatility estimation (RiskMetrics style)
- Market making quote generation with bid-ask spread
- Inventory risk skewing for delta-neutral positioning
"""

import numpy as np
from scipy.stats import norm
from collections import deque
from typing import Optional, Dict
from dataclasses import dataclass
import time
import math


@dataclass
class MarketQuote:
    """Represents a two-sided market quote."""
    bid: float  # Price to buy YES at
    ask: float  # Price to sell YES at
    mid: float  # Fair value (mid price)
    spread: float  # Bid-ask spread
    skew: float  # Applied skew due to inventory
    timestamp: float  # Unix timestamp
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/API."""
        return {
            "bid": round(self.bid, 4),
            "ask": round(self.ask, 4),
            "mid": round(self.mid, 4),
            "spread": round(self.spread, 4),
            "skew": round(self.skew, 4),
            "timestamp": self.timestamp
        }


@dataclass
class VolatilityState:
    """Current volatility estimate and metadata."""
    annualized_vol: float  # σ (annualized)
    variance: float  # σ²
    last_update: float  # Unix timestamp
    sample_count: int  # Number of returns used
    
    def age_seconds(self) -> float:
        """Get age of volatility estimate."""
        return time.time() - self.last_update


class EWMAVolatilityEstimator:
    """
    EWMA (Exponentially Weighted Moving Average) volatility estimator.
    
    Uses RiskMetrics-style EWMA for fast reaction to volatility regime changes:
    σ²_t = λσ²_(t-1) + (1-λ)r²_(t-1)
    
    Optimized for high-frequency tick data.
    """
    
    def __init__(
        self,
        lambda_param: float = 0.94,  # Decay factor (0.90-0.97 for short-term)
        min_samples: int = 20,  # Minimum returns before trusting estimate
        tick_buffer_size: int = 1000,  # Keep last N ticks for recomputation
        sampling_frequency: str = "tick"  # "tick" or time-based like "1s", "5s"
    ):
        """
        Initialize EWMA volatility estimator.
        
        Args:
            lambda_param: EWMA decay factor (higher = more persistent)
                         0.94 = ~15 minute half-life for minute data
                         0.97 = ~30 minute half-life
            min_samples: Minimum returns needed for valid estimate
            tick_buffer_size: Size of price history buffer
            sampling_frequency: "tick" for every tick, or time interval
        """
        self.lambda_param = lambda_param
        self.min_samples = min_samples
        self.sampling_frequency = sampling_frequency
        
        # Price history (circular buffer)
        self.prices = deque(maxlen=tick_buffer_size)
        self.timestamps = deque(maxlen=tick_buffer_size)
        
        # EWMA state
        self.ewma_variance: Optional[float] = None
        self.last_price: Optional[float] = None
        self.last_timestamp: Optional[float] = None
        self.sample_count = 0
        
    def add_price(self, price: float, timestamp: float) -> Optional[VolatilityState]:
        """
        Add new price tick and update volatility estimate.
        
        Args:
            price: Current price
            timestamp: Unix timestamp
            
        Returns:
            VolatilityState if estimate is valid, None otherwise
        """
        self.prices.append(price)
        self.timestamps.append(timestamp)
        
        # Need at least 2 prices to compute return
        if self.last_price is None:
            self.last_price = price
            self.last_timestamp = timestamp
            return None
        
        # Compute log return
        log_return = math.log(price / self.last_price)
        
        # Time interval (for annualization)
        dt = timestamp - self.last_timestamp  # in seconds
        
        # Update EWMA variance
        if self.ewma_variance is None:
            # Initialize with squared return
            self.ewma_variance = log_return ** 2
        else:
            # EWMA update: σ²_t = λσ²_(t-1) + (1-λ)r²_(t-1)
            self.ewma_variance = (
                self.lambda_param * self.ewma_variance +
                (1 - self.lambda_param) * (log_return ** 2)
            )
        
        self.sample_count += 1
        self.last_price = price
        self.last_timestamp = timestamp
        
        # Return volatility state if we have enough samples
        if self.sample_count >= self.min_samples:
            # Annualize volatility
            # For tick data, assume average time between ticks
            if dt > 0:
                # Convert variance per dt seconds to annual variance
                seconds_per_year = 365.25 * 24 * 3600
                annualization_factor = seconds_per_year / dt
                annualized_variance = self.ewma_variance * annualization_factor
                annualized_vol = math.sqrt(annualized_variance)
            else:
                # Fallback: assume 1-second intervals
                annualized_vol = math.sqrt(self.ewma_variance * (365.25 * 24 * 3600))
            
            return VolatilityState(
                annualized_vol=annualized_vol,
                variance=self.ewma_variance,
                last_update=timestamp,
                sample_count=self.sample_count
            )
        
        return None
    
    def get_current_volatility(self) -> Optional[VolatilityState]:
        """Get current volatility estimate without updating."""
        if self.ewma_variance is None or self.sample_count < self.min_samples:
            return None
        
        # Compute annualized vol
        if self.last_timestamp and len(self.timestamps) > 1:
            # Estimate average dt from recent ticks
            recent_times = list(self.timestamps)[-10:]
            if len(recent_times) > 1:
                avg_dt = np.mean(np.diff(recent_times))
                seconds_per_year = 365.25 * 24 * 3600
                annualization_factor = seconds_per_year / avg_dt
                annualized_variance = self.ewma_variance * annualization_factor
                annualized_vol = math.sqrt(annualized_variance)
            else:
                annualized_vol = math.sqrt(self.ewma_variance * (365.25 * 24 * 3600))
        else:
            annualized_vol = math.sqrt(self.ewma_variance * (365.25 * 24 * 3600))
        
        return VolatilityState(
            annualized_vol=annualized_vol,
            variance=self.ewma_variance,
            last_update=self.last_timestamp or time.time(),
            sample_count=self.sample_count
        )
    
    def reset(self):
        """Reset volatility estimator."""
        self.prices.clear()
        self.timestamps.clear()
        self.ewma_variance = None
        self.last_price = None
        self.last_timestamp = None
        self.sample_count = 0


class BlackScholesDigitalPricer:
    """
    Black-Scholes probability calculator for binary/digital options.
    
    Computes risk-neutral probability that spot > strike at expiry:
    P(S_T > K) = N(d2)
    
    where d2 = (ln(S/K) + (r - 0.5σ²)T) / (σ√T)
    """
    
    def __init__(self, risk_free_rate: float = 0.05):
        """
        Initialize BS digital pricer.
        
        Args:
            risk_free_rate: Annual risk-free rate (default 5% = 0.05)
        """
        self.risk_free_rate = risk_free_rate
    
    def calculate_probability(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,  # in years
        volatility: float,  # annualized
    ) -> float:
        """
        Calculate risk-neutral probability of S > K at expiry.
        
        Args:
            spot: Current spot price (S)
            strike: Strike/threshold price (K)
            time_to_expiry: Time to expiry in years (T)
            volatility: Annualized volatility (σ)
            
        Returns:
            Probability [0, 1] that spot > strike at expiry
        """
        # Handle edge cases
        if time_to_expiry <= 0:
            return 1.0 if spot > strike else 0.0
        
        if volatility <= 0:
            return 1.0 if spot > strike else 0.0
        
        # Black-Scholes d2 formula
        # d2 = (ln(S/K) + (r - 0.5σ²)T) / (σ√T)
        log_moneyness = math.log(spot / strike)
        vol_squared = volatility ** 2
        sqrt_time = math.sqrt(time_to_expiry)
        
        d2 = (
            log_moneyness +
            (self.risk_free_rate - 0.5 * vol_squared) * time_to_expiry
        ) / (volatility * sqrt_time)
        
        # Probability = N(d2), where N is standard normal CDF
        probability = norm.cdf(d2)
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, probability))
    
    def calculate_probability_minutes(
        self,
        spot: float,
        strike: float,
        minutes_to_expiry: float,
        volatility: float,
    ) -> float:
        """
        Convenience method with time in minutes (common for short-term markets).
        
        Args:
            minutes_to_expiry: Time to expiry in minutes
        """
        # Convert minutes to years
        time_to_expiry = minutes_to_expiry / (365.25 * 24 * 60)
        return self.calculate_probability(spot, strike, time_to_expiry, volatility)
    
    def calculate_up_down_probabilities(
        self,
        spot: float,
        strike: float,
        minutes_to_expiry: float,
        volatility: float,
    ) -> Dict[str, float]:
        """
        Calculate both UP and DOWN probabilities for binary markets.
        
        For Polymarket 15-min markets: "Will BTC be above $X at time T?"
        - UP probability: P(spot > strike at expiry)
        - DOWN probability: P(spot <= strike at expiry) = 1 - UP
        
        Args:
            spot: Current spot price
            strike: Threshold price from Polymarket market
            minutes_to_expiry: Time remaining in minutes
            volatility: Annualized volatility
            
        Returns:
            Dict with 'up' and 'down' probabilities
        """
        prob_up = self.calculate_probability_minutes(
            spot, strike, minutes_to_expiry, volatility
        )
        prob_down = 1.0 - prob_up
        
        return {
            "up": prob_up,      # P(price > strike)
            "down": prob_down   # P(price <= strike)
        }


class MarketMaker:
    """
    Market making engine for binary options.
    
    Combines:
    - Fair value from Black-Scholes
    - Bid-ask spread for profit
    - Inventory skewing for risk control
    """
    
    def __init__(
        self,
        base_spread: float = 0.02,  # 2% base spread (1% each side)
        max_inventory: float = 100.0,  # Max position size
        inventory_skew_factor: float = 0.001,  # Skew per unit of inventory
        min_quote_price: float = 0.01,  # Minimum quote (avoid 0)
        max_quote_price: float = 0.99,  # Maximum quote (avoid 1)
    ):
        """
        Initialize market maker.
        
        Args:
            base_spread: Base bid-ask spread (e.g., 0.02 = 2%)
            max_inventory: Maximum position size before stopping quotes
            inventory_skew_factor: How much to skew per unit of inventory
            min_quote_price: Minimum allowed quote price
            max_quote_price: Maximum allowed quote price
        """
        self.base_spread = base_spread
        self.max_inventory = max_inventory
        self.inventory_skew_factor = inventory_skew_factor
        self.min_quote_price = min_quote_price
        self.max_quote_price = max_quote_price
        
        # Current inventory (positive = long YES, negative = long NO)
        self.inventory = 0.0
    
    def calculate_inventory_skew(self, inventory: float) -> float:
        """
        Calculate price skew based on inventory position.
        
        Positive inventory (long YES) → negative skew (lower quotes)
        Negative inventory (long NO) → positive skew (higher quotes)
        
        Args:
            inventory: Current inventory (positive = long YES)
            
        Returns:
            Skew to add to fair price
        """
        return -inventory * self.inventory_skew_factor
    
    def generate_quote(
        self,
        fair_value: float,
        inventory: Optional[float] = None,
        spread_multiplier: float = 1.0,
    ) -> Optional[MarketQuote]:
        """
        Generate two-sided market quote.
        
        Args:
            fair_value: Fair probability from Black-Scholes [0, 1]
            inventory: Current inventory (None = use internal state)
            spread_multiplier: Multiply base spread (e.g., 2.0 = double spread)
            
        Returns:
            MarketQuote with bid/ask, or None if can't quote
        """
        if inventory is None:
            inventory = self.inventory
        
        # Check if inventory is too large
        if abs(inventory) > self.max_inventory:
            return None  # Stop quoting if max inventory reached
        
        # Calculate skew
        skew = self.calculate_inventory_skew(inventory)
        
        # Apply skew to fair value
        skewed_mid = fair_value + skew
        
        # Calculate spread
        spread = self.base_spread * spread_multiplier
        half_spread = spread / 2.0
        
        # Generate bid/ask
        bid = skewed_mid - half_spread
        ask = skewed_mid + half_spread
        
        # Clamp to valid range
        bid = max(self.min_quote_price, min(bid, self.max_quote_price))
        ask = max(self.min_quote_price, min(ask, self.max_quote_price))
        
        # Ensure bid < ask
        if bid >= ask:
            # If inventory skew caused inversion, widen spread
            mid = (bid + ask) / 2.0
            bid = mid - 0.01
            ask = mid + 0.01
            bid = max(self.min_quote_price, bid)
            ask = min(self.max_quote_price, ask)
        
        return MarketQuote(
            bid=bid,
            ask=ask,
            mid=skewed_mid,
            spread=ask - bid,
            skew=skew,
            timestamp=time.time()
        )
    
    def update_inventory(self, delta: float):
        """
        Update inventory after a trade.
        
        Args:
            delta: Change in inventory (positive = bought YES, negative = sold YES)
        """
        self.inventory += delta
    
    def get_inventory(self) -> float:
        """Get current inventory."""
        return self.inventory
    
    def set_inventory(self, inventory: float):
        """Set inventory to specific value."""
        self.inventory = inventory


class PricingEngine:
    """
    Complete HFT pricing engine combining all components.
    
    Pipeline:
    1. Tick data → EWMA volatility
    2. Spot + vol + strike + time → Black-Scholes fair value
    3. Fair value + inventory → Market quotes
    """
    
    def __init__(
        self,
        lambda_param: float = 0.94,
        base_spread: float = 0.02,
        max_inventory: float = 100.0,
        inventory_skew_factor: float = 0.001,
        risk_free_rate: float = 0.05,
    ):
        """
        Initialize complete pricing engine.
        
        Args:
            lambda_param: EWMA decay factor
            base_spread: Base bid-ask spread
            max_inventory: Maximum position size
            inventory_skew_factor: Inventory skew sensitivity
            risk_free_rate: Annual risk-free rate
        """
        self.vol_estimator = EWMAVolatilityEstimator(lambda_param=lambda_param)
        self.bs_pricer = BlackScholesDigitalPricer(risk_free_rate=risk_free_rate)
        self.market_maker = MarketMaker(
            base_spread=base_spread,
            max_inventory=max_inventory,
            inventory_skew_factor=inventory_skew_factor
        )
        
        # Current state
        self.current_spot: Optional[float] = None
        self.current_volatility: Optional[VolatilityState] = None
    
    def update_price(self, price: float, timestamp: float):
        """
        Update with new price tick.
        
        Args:
            price: Current spot price
            timestamp: Unix timestamp
        """
        self.current_spot = price
        vol_state = self.vol_estimator.add_price(price, timestamp)
        if vol_state:
            self.current_volatility = vol_state
    
    def calculate_fair_value(
        self,
        strike: float,
        minutes_to_expiry: float,
        spot: Optional[float] = None,
        volatility: Optional[float] = None,
    ) -> Optional[float]:
        """
        Calculate fair value probability for UP (price > strike).
        
        Args:
            strike: Strike/threshold price from Polymarket
            minutes_to_expiry: Time to expiry in minutes
            spot: Override spot price (None = use current)
            volatility: Override volatility (None = use current EWMA)
            
        Returns:
            Fair UP probability [0, 1], or None if not enough data
        """
        # Use current spot if not provided
        if spot is None:
            spot = self.current_spot
        if spot is None:
            return None
        
        # Use current volatility if not provided
        if volatility is None:
            if self.current_volatility is None:
                return None
            volatility = self.current_volatility.annualized_vol
        
        # Calculate probability
        prob = self.bs_pricer.calculate_probability_minutes(
            spot=spot,
            strike=strike,
            minutes_to_expiry=minutes_to_expiry,
            volatility=volatility
        )
        
        return prob
    
    def calculate_up_down_probabilities(
        self,
        strike: float,
        minutes_to_expiry: float,
        spot: Optional[float] = None,
        volatility: Optional[float] = None,
    ) -> Optional[Dict[str, float]]:
        """
        Calculate both UP and DOWN probabilities for Polymarket binary markets.
        
        This is the main method for pricing 15-minute up/down markets.
        Returns the fair probabilities you'll use for position sizing.
        
        Args:
            strike: Threshold price from Polymarket market ("Will BTC be above $X?")
            minutes_to_expiry: Time remaining to market expiry
            spot: Override spot price (None = use current from ticks)
            volatility: Override volatility (None = use current EWMA estimate)
            
        Returns:
            Dict with 'up' and 'down' probabilities, or None if insufficient data
            
        Example:
            probs = engine.calculate_up_down_probabilities(
                strike=67000,  # From Polymarket: "BTC > $67,000?"
                minutes_to_expiry=12.5
            )
            # Returns: {'up': 0.753, 'down': 0.247}
        """
        # Use current spot if not provided
        if spot is None:
            spot = self.current_spot
        if spot is None:
            return None
        
        # Use current volatility if not provided
        if volatility is None:
            if self.current_volatility is None:
                return None
            volatility = self.current_volatility.annualized_vol
        
        # Calculate both probabilities
        probs = self.bs_pricer.calculate_up_down_probabilities(
            spot=spot,
            strike=strike,
            minutes_to_expiry=minutes_to_expiry,
            volatility=volatility
        )
        
        return probs
    
    def generate_quotes(
        self,
        strike: float,
        minutes_to_expiry: float,
        spread_multiplier: float = 1.0,
    ) -> Optional[MarketQuote]:
        """
        Generate market maker quotes.
        
        Args:
            strike: Strike/threshold price
            minutes_to_expiry: Time to expiry in minutes
            spread_multiplier: Spread adjustment factor
            
        Returns:
            MarketQuote or None if can't quote
        """
        # Calculate fair value
        fair_value = self.calculate_fair_value(strike, minutes_to_expiry)
        if fair_value is None:
            return None
        
        # Generate quote with inventory skew
        quote = self.market_maker.generate_quote(
            fair_value=fair_value,
            spread_multiplier=spread_multiplier
        )
        
        return quote
    
    def get_status(self) -> Dict:
        """Get current engine status for monitoring."""
        return {
            "spot": self.current_spot,
            "volatility": self.current_volatility.annualized_vol if self.current_volatility else None,
            "vol_samples": self.vol_estimator.sample_count,
            "inventory": self.market_maker.get_inventory(),
            "timestamp": time.time()
        }
