"""
Example integration of pricing engine with Polymarket 15-minute markets.

Shows complete flow:
1. Binance WebSocket → Price ticks
2. EWMA volatility estimation
3. Black-Scholes UP/DOWN probabilities
4. Compare to Polymarket prices
5. Calculate position sizing
"""

import asyncio
import time
from datetime import datetime, timezone
from config import get_config
from helpers.binance import BinanceWebSocket, PriceTick
from helpers.pricing import PricingEngine
from helpers.polymarket import (
    PolymarketClient,
    PolymarketMarket,
    calculate_sizing_from_probabilities
)


class PolymarketMarketMaker:
    """
    Complete market maker for Polymarket 15-minute binary markets.
    """
    
    def __init__(self, config=None):
        # Load configuration
        self.config = config or get_config()
        
        # Initialize pricing engine with config
        self.pricing_engine = PricingEngine(
            lambda_param=self.config.pricing.lambda_param,
            base_spread=self.config.pricing.base_spread,
            max_inventory=self.config.pricing.max_inventory,
            inventory_skew_factor=self.config.pricing.inventory_skew_factor,
            risk_free_rate=self.config.pricing.risk_free_rate
        )
        
        # Initialize Polymarket client from config
        self.poly_client = PolymarketClient.from_config(self.config.polymarket)
        
        # Track active markets
        self.active_markets = {}
        
        # Performance tracking
        self.tick_count = 0
        self.last_quote_time = time.time()
        self.last_market_refresh = 0.0
        
        # Config shortcuts
        self.edge_threshold = self.config.trading.edge_threshold
        self.sizing_factor = self.config.trading.sizing_factor
        self.ticks_per_update = self.config.system.ticks_per_update
        self.quote_update_interval = self.config.system.quote_update_interval
        self.dry_run = self.config.system.dry_run
    
    async def on_price_tick(self, tick: PriceTick):
        """
        Handle each price tick from Binance.
        
        This is the main event loop - fires on every trade (millisecond-level).
        """
        # Update pricing engine with new tick
        self.pricing_engine.update_price(tick.price, tick.timestamp)
        self.tick_count += 1
        
        # Don't requote on every single tick (too aggressive)
        # Requote every N ticks or every X seconds
        time_since_quote = time.time() - self.last_quote_time
        
        if self.tick_count % self.ticks_per_update == 0 or time_since_quote > self.quote_update_interval:
            await self.update_quotes()
            self.last_quote_time = time.time()
    
    async def update_quotes(self):
        """
        Update quotes for all active markets.
        """
        # Refresh markets periodically (every 60 seconds)
        time_since_refresh = time.time() - self.last_market_refresh
        if time_since_refresh > 60.0:
            await self.refresh_markets()
            self.last_market_refresh = time.time()
        
        # Get current volatility state
        vol_state = self.pricing_engine.current_volatility
        if vol_state is None:
            print("Waiting for volatility estimate...")
            return
        
        print("\n=== Quote Update ===")
        print(f"Spot: ${self.pricing_engine.current_spot:.2f}")
        print(f"Vol: {vol_state.annualized_vol:.1%} (from {vol_state.sample_count} samples)")
        
        # Update each active market
        for market_id, market in list(self.active_markets.items()):
            await self.update_market_quotes(market)
    
    async def refresh_markets(self):
        """
        Refresh market data from Polymarket.
        """
        try:
            print("\n[Refreshing markets from Polymarket...]")
            crypto_markets = self.poly_client.get_crypto_15min_markets(["BTC", "ETH", "SOL", "XRP"])
            
            # Update active markets
            refreshed_count = 0
            for market in crypto_markets:
                mins = market.minutes_to_expiry()
                
                # Apply filters
                if mins < self.config.trading.min_time_to_expiry:
                    # Remove expired markets
                    if market.market_id in self.active_markets:
                        del self.active_markets[market.market_id]
                    continue
                    
                if mins > self.config.trading.max_time_to_expiry:
                    continue
                
                # Update or add market
                self.active_markets[market.market_id] = market
                refreshed_count += 1
            
            print(f"[Refreshed {refreshed_count} markets]")
            
        except Exception as e:
            print(f"[Warning: Market refresh failed: {e}]")
    
    async def update_market_quotes(self, market: PolymarketMarket):
        """
        Update quotes for a specific market.
        """
        # Skip if expired
        if market.is_expired():
            print(f"Market {market.market_id} expired, removing...")
            del self.active_markets[market.market_id]
            return
        
        minutes_remaining = market.minutes_to_expiry()
        
        # For Up/Down markets, set strike to current spot price if not yet set
        # (These markets compare end price vs start price from Chainlink)
        if market.strike_price is None or market.strike_price == 0:
            spot_price = self.pricing_engine.current_spot
            if spot_price:
                market.strike_price = spot_price
                print(f"[{market.market_id[:8]}] Set strike=${spot_price:.2f} (current spot)")
            else:
                print(f"Cannot price {market.market_id} - no spot price available")
                return
        
        # Calculate fair probabilities using Black-Scholes
        probs = self.pricing_engine.calculate_up_down_probabilities(
            strike=market.strike_price,
            minutes_to_expiry=minutes_remaining
        )
        
        if probs is None:
            print(f"Cannot price {market.market_id} - insufficient data")
            return
        
        fair_up = probs['up']
        fair_down = probs['down']
        
        # Format expiry time
        expiry_dt_utc = datetime.fromtimestamp(market.expiry_time, tz=timezone.utc)
        expiry_dt_local = datetime.fromtimestamp(market.expiry_time)
        if expiry_dt_utc.hour == expiry_dt_local.hour and expiry_dt_utc.minute == expiry_dt_local.minute:
            expiry_str = expiry_dt_utc.strftime("%H:%M UTC")
        else:
            expiry_str = f"{expiry_dt_utc.strftime('%H:%M UTC')} ({expiry_dt_local.strftime('%H:%M')} local)"
        
        print(f"\nMarket: {market.question}")
        print(f"Strike: ${market.strike_price:.2f} | Expires: {expiry_str} ({minutes_remaining:.1f} min)")
        print(f"Fair Probs: UP={fair_up:.1%}, DOWN={fair_down:.1%}")
        
        # Get current market prices from Polymarket (use mid of bid/ask)
        # For YES: use ask price if we want to BUY, bid price if we want to SELL
        # For simplicity, use mid price for comparison
        if market.yes_bid is not None and market.yes_ask is not None:
            market_up_price = (market.yes_bid + market.yes_ask) / 2.0
        else:
            print(f"⚠️  No YES prices available for {market.market_id}")
            return
        
        if market.no_bid is not None and market.no_ask is not None:
            market_down_price = (market.no_bid + market.no_ask) / 2.0
        else:
            print(f"⚠️  No NO prices available for {market.market_id}")
            return
        
        print(f"Market Prices: YES={market_up_price:.1%} (bid={market.yes_bid:.3f}, ask={market.yes_ask:.3f})")
        print(f"               NO={market_down_price:.1%} (bid={market.no_bid:.3f}, ask={market.no_ask:.3f})")
        
        # Calculate sizing based on edge
        sizing = calculate_sizing_from_probabilities(
            fair_prob_up=fair_up,
            fair_prob_down=fair_down,
            market_prob_up=market_up_price,
            market_prob_down=market_down_price,
            edge_threshold=self.edge_threshold,
            max_size=self.config.trading.max_position_size,
            sizing_factor=self.sizing_factor
        )
        
        # Display recommended trades
        edge_up = fair_up - market_up_price
        edge_down = fair_down - market_down_price
        
        print(f"Edge: UP={edge_up:+.1%}, DOWN={edge_down:+.1%}")
        
        if sizing["buy_yes"]:
            print(f"→ BUY YES size: {sizing['buy_yes']:.1f} (market underpricing UP)")
            if not self.dry_run:
                await self.place_orders(market, sizing)
            else:
                print("  [DRY RUN] Order not placed")
        elif sizing["sell_yes"]:
            print(f"→ SELL YES size: {sizing['sell_yes']:.1f} (market overpricing UP)")
            if not self.dry_run:
                await self.place_orders(market, sizing)
            else:
                print("  [DRY RUN] Order not placed")
        elif sizing["buy_no"]:
            print(f"→ BUY NO size: {sizing['buy_no']:.1f} (market underpricing DOWN)")
            if not self.dry_run:
                await self.place_orders(market, sizing)
            else:
                print("  [DRY RUN] Order not placed")
        elif sizing["sell_no"]:
            print(f"→ SELL NO size: {sizing['sell_no']:.1f} (market overpricing DOWN)")
            if not self.dry_run:
                await self.place_orders(market, sizing)
            else:
                print("  [DRY RUN] Order not placed")
        else:
            print("→ No edge, pass")
    
    async def place_orders(self, market: PolymarketMarket, sizing: dict):
        """
        Place orders on Polymarket based on sizing.
        
        TODO: Implement actual order placement
        """
        # Example flow:
        # 1. Cancel existing orders
        # 2. Place new orders at fair value +/- spread
        # 3. Adjust for inventory skew
        pass
    
    async def run(self):
        """
        Main event loop.
        """
        print("Starting Polymarket Market Maker...")
        print("=" * 60)
        
        # Dry run warning
        if self.dry_run:
            print("🔵 DRY RUN MODE - NO REAL TRADES WILL BE PLACED")
            print("=" * 60)
        
        print(f"Trading symbols: {self.config.trading.trading_symbols}")
        print(f"Edge threshold: {self.edge_threshold:.1%}")
        print(f"Sizing factor: {self.sizing_factor}")
        print(f"Lambda param: {self.config.pricing.lambda_param}")
        print(f"Dry run: {self.dry_run}")
        print("=" * 60)
        
        # Fetch real markets from Polymarket
        print("\nFetching crypto markets from Polymarket...")
        print("Assets: BTC, ETH, SOL, XRP")
        try:
            # Use optimized multi-asset fetching
            crypto_markets = self.poly_client.get_crypto_15min_markets(["BTC", "ETH", "SOL", "XRP"])
            print(f"Found {len(crypto_markets)} 15-minute markets across all assets")
            
            # Filter by config constraints
            filtered_markets = []
            for market in crypto_markets:
                mins = market.minutes_to_expiry()
                
                # Apply filters from config
                if mins < self.config.trading.min_time_to_expiry:
                    continue
                if mins > self.config.trading.max_time_to_expiry:
                    continue
                
                # Check if market has valid prices
                if market.yes_bid is None or market.yes_ask is None:
                    print(f"Skipping {market.market_id}: No price data")
                    continue
                
                filtered_markets.append(market)
                self.active_markets[market.market_id] = market
            
            print(f"Trading {len(filtered_markets)} markets after filtering")
            
            # Display active markets
            for market in filtered_markets:
                print(f"\n  Market: {market.question}")
                print(f"  Strike: ${market.strike_price:.0f} | Expires in: {market.minutes_to_expiry():.1f} min")
                print(f"  YES: bid={market.yes_bid:.3f} ask={market.yes_ask:.3f}")
                print(f"  NO: bid={market.no_bid:.3f} ask={market.no_ask:.3f}")
            
            if len(filtered_markets) == 0:
                print("\n⚠️  No markets match your criteria. Adjust filters in .env:")
                print(f"   MIN_TIME_TO_EXPIRY={self.config.trading.min_time_to_expiry}")
                print(f"   MAX_TIME_TO_EXPIRY={self.config.trading.max_time_to_expiry}")
                print("\nRunning anyway - will check for new markets periodically...")
        
        except Exception as e:
            print(f"⚠️  Error fetching Polymarket markets: {e}")
            print("This may be due to:")
            print("  1. Invalid POLYMARKET_PRIVATE_KEY in .env")
            print("  2. Network connectivity issues")
            print("  3. Polymarket API rate limits")
            print("\nContinuing without markets - will retry periodically...")
        
        # Start Binance WebSocket for BTC price feed
        print("\nConnecting to Binance WebSocket...")
        ws = BinanceWebSocket(
            symbols=['BTCUSDT'],
            on_tick=lambda tick: asyncio.create_task(self.on_price_tick(tick))
        )
        
        # Start streaming
        await ws.connect()


async def main():
    """Run the market maker."""
    mm = PolymarketMarketMaker()
    await mm.run()


if __name__ == "__main__":
    asyncio.run(main())
