"""
Example integration of pricing engine with Polymarket 15-minute markets.

Shows complete flow:
1. Polymarket RTDS WebSocket → Price ticks (from Chainlink oracles)
2. EWMA volatility estimation
3. Black-Scholes UP/DOWN probabilities
4. Compare to Polymarket prices
5. Calculate position sizing
"""

import asyncio
import time
from datetime import datetime, timezone
from config import get_config
from helpers.polymarket_rtds import PolymarketRTDSClient, PriceTick
from helpers.pricing import PricingEngine
from helpers.polymarket import (
    PolymarketClient,
    PolymarketMarket,
    calculate_sizing_from_probabilities
)
from helpers.performance_logger import PerformanceLogger


class PolymarketMarketMaker:
    """
    Complete market maker for Polymarket 15-minute binary markets.
    """
    
    def __init__(self, config=None, logger: PerformanceLogger = None):
        # Load configuration
        self.config = config or get_config()
        
        # Initialize performance logger
        self.logger = logger or PerformanceLogger()
        
        # Log configuration
        config_dict = {
            "pricing": {
                "lambda_param": self.config.pricing.lambda_param,
                "base_spread": self.config.pricing.base_spread,
                "max_inventory": self.config.pricing.max_inventory,
                "inventory_skew_factor": self.config.pricing.inventory_skew_factor,
                "risk_free_rate": self.config.pricing.risk_free_rate
            },
            "trading": {
                "trading_symbols": self.config.trading.trading_symbols,
                "edge_threshold": self.config.trading.edge_threshold,
                "sizing_factor": self.config.trading.sizing_factor,
                "max_position_size": self.config.trading.max_position_size,
                "min_time_to_expiry": self.config.trading.min_time_to_expiry,
                "max_time_to_expiry": self.config.trading.max_time_to_expiry
            },
            "system": {
                "ticks_per_update": self.config.system.ticks_per_update,
                "quote_update_interval": self.config.system.quote_update_interval,
                "dry_run": self.config.system.dry_run
            }
        }
        self.logger.log_config(config_dict)
        
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
        self.last_performance_log = time.time()
        
        # Config shortcuts
        self.edge_threshold = self.config.trading.edge_threshold
        self.sizing_factor = self.config.trading.sizing_factor
        self.ticks_per_update = self.config.system.ticks_per_update
        self.quote_update_interval = self.config.system.quote_update_interval
        self.dry_run = self.config.system.dry_run
    
    async def on_price_tick(self, tick: PriceTick):
        """
        Handle each price tick from Polymarket RTDS.
        
        This is the main event loop - fires on every Chainlink price update.
        """
        # Log the price tick
        self.logger.log_price_tick(
            symbol=tick.symbol,
            price=tick.price,
            timestamp=tick.timestamp,
            source="polymarket_rtds",
            additional_data={
                "volume": tick.volume,
                "trade_id": tick.trade_id
            }
        )
        
        # Debug print to confirm we're receiving ticks
        print(f"📊 {tick.symbol}: ${tick.price:,.2f} @ {datetime.fromtimestamp(tick.timestamp).strftime('%H:%M:%S')}")
        
        # Update pricing engine with new tick
        self.pricing_engine.update_price(tick.price, tick.timestamp)
        self.tick_count += 1
        
        # Log performance metrics every 60 seconds
        time_since_perf_log = time.time() - self.last_performance_log
        if time_since_perf_log > 60.0:
            vol_state = self.pricing_engine.current_volatility
            metrics = {
                "tick_count": self.tick_count,
                "avg_tick_rate": self.tick_count / (time.time() - self.logger.session_start),
                "active_markets": len(self.active_markets),
                "current_spot": self.pricing_engine.current_spot
            }
            if vol_state:
                metrics["volatility"] = {
                    "annualized": vol_state.annualized_vol,
                    "sample_count": vol_state.sample_count
                }
            self.logger.log_performance("tick_metrics", metrics)
            self.last_performance_log = time.time()
        
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
            crypto_markets = self.poly_client.get_crypto_15min_markets(["BTC"]) #(["BTC", "ETH", "SOL", "XRP"])
            
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
            self.logger.log_market_state(
                market_id=market.market_id,
                question=market.question,
                strike_price=market.strike_price,
                start_time=market.start_time,
                expiry_time=market.expiry_time,
                minutes_remaining=0,
                status="expired"
            )
            del self.active_markets[market.market_id]
            return
        
        minutes_remaining = market.minutes_to_expiry()
        
        # For Up/Down markets, set strike price at precise market start time
        # These markets compare end price vs start price from Chainlink oracle
        if market.strike_price is None or market.strike_price == 0:
            if market.start_time is None:
                print(f"[{market.market_id[:8]}] ERROR: Market has no start_time")
                self.logger.log_error("missing_start_time", "Market has no start_time", {
                    "market_id": market.market_id,
                    "question": market.question
                })
                return
            
            # Check if market has started
            if market.has_started():
                # Market already started - try to get price from exact start time
                strike_price = self.pricing_engine.get_price_at_timestamp(
                    market.start_time,
                    tolerance_seconds=5.0  # Accept price within 5 seconds
                )
                
                if strike_price:
                    market.strike_price = strike_price
                    start_dt = datetime.fromtimestamp(market.start_time, tz=timezone.utc)
                    print(f"[{market.market_id[:8]}] Set strike=${strike_price:.2f} at {start_dt.strftime('%H:%M:%S UTC')} (market start)")
                    
                    # Log strike price setting
                    self.logger.log_market_state(
                        market_id=market.market_id,
                        question=market.question,
                        strike_price=strike_price,
                        start_time=market.start_time,
                        expiry_time=market.expiry_time,
                        minutes_remaining=minutes_remaining,
                        status="strike_set"
                    )
                else:
                    # No buffered price at start time - skip this market to avoid inaccurate pricing
                    # Remove from active markets and wait for next market
                    start_dt = datetime.fromtimestamp(market.start_time, tz=timezone.utc)
                    print(f"[{market.market_id[:8]}] ⚠️  No buffered price at start time {start_dt.strftime('%H:%M:%S UTC')}")
                    print(f"[{market.market_id[:8]}] Skipping market to ensure accurate pricing. Will trade next market.")
                    
                    # Log missing strike price
                    self.logger.log_error("missing_strike_price", "No buffered price at market start time", {
                        "market_id": market.market_id,
                        "question": market.question,
                        "start_time": market.start_time,
                        "start_time_iso": start_dt.isoformat()
                    })
                    
                    del self.active_markets[market.market_id]
                    return
            else:
                # Market hasn't started yet - wait for start time
                seconds_to_start = market.seconds_to_start()
                start_dt = datetime.fromtimestamp(market.start_time, tz=timezone.utc)
                print(f"[{market.market_id[:8]}] Waiting for market start at {start_dt.strftime('%H:%M:%S UTC')} ({seconds_to_start:.0f}s)")
                
                # Log waiting state
                self.logger.log_market_state(
                    market_id=market.market_id,
                    question=market.question,
                    strike_price=None,
                    start_time=market.start_time,
                    expiry_time=market.expiry_time,
                    minutes_remaining=minutes_remaining,
                    status="waiting",
                    additional_data={"seconds_to_start": seconds_to_start}
                )
                return
        
        # Log current market state
        self.logger.log_market_state(
            market_id=market.market_id,
            question=market.question,
            strike_price=market.strike_price,
            start_time=market.start_time,
            expiry_time=market.expiry_time,
            minutes_remaining=minutes_remaining,
            status="active"
        )
        
        # Calculate fair probabilities using Black-Scholes
        probs = self.pricing_engine.calculate_up_down_probabilities(
            strike=market.strike_price,
            minutes_to_expiry=minutes_remaining
        )
        
        if probs is None:
            print(f"Cannot price {market.market_id} - insufficient data")
            self.logger.log_error("pricing_failed", "Insufficient data for pricing", {
                "market_id": market.market_id,
                "strike": market.strike_price,
                "minutes_remaining": minutes_remaining
            })
            return
        
        fair_up = probs['up']
        fair_down = probs['down']
        
        # Log volatility calculation
        vol_state = self.pricing_engine.current_volatility
        if vol_state:
            self.logger.log_calculation(
                market_id=market.market_id,
                calculation_type="volatility",
                inputs={
                    "current_spot": self.pricing_engine.current_spot,
                    "lambda_param": self.config.pricing.lambda_param
                },
                outputs={
                    "annualized_vol": vol_state.annualized_vol,
                    "sample_count": vol_state.sample_count
                }
            )
        
        # Log probability calculation
        self.logger.log_calculation(
            market_id=market.market_id,
            calculation_type="probability",
            inputs={
                "strike": market.strike_price,
                "spot": self.pricing_engine.current_spot,
                "volatility": vol_state.annualized_vol if vol_state else None,
                "time_to_expiry_minutes": minutes_remaining,
                "risk_free_rate": self.config.pricing.risk_free_rate
            },
            outputs={
                "prob_up": fair_up,
                "prob_down": fair_down
            }
        )
        
        # Format expiry time
        expiry_dt_utc = datetime.fromtimestamp(market.expiry_time, tz=timezone.utc)
        expiry_dt_local = datetime.fromtimestamp(market.expiry_time)
        if expiry_dt_utc.hour == expiry_dt_local.hour and expiry_dt_utc.minute == expiry_dt_local.minute:
            expiry_str = expiry_dt_utc.strftime("%H:%M UTC")
        else:
            expiry_str = f"{expiry_dt_utc.strftime('%H:%M UTC')} ({expiry_dt_local.strftime('%H:%M')} local)"
        
        strike_str = f"${market.strike_price:.2f}" if market.strike_price else "TBD (will be set to spot)"
        print(f"\nMarket: {market.question}")
        print(f"Strike: {strike_str} | Expires: {expiry_str} ({minutes_remaining:.1f} min)")
        print(f"Fair Probs: UP={fair_up:.1%}, DOWN={fair_down:.1%}")
        
        # Get current market prices from Polymarket (use mid of bid/ask)
        # For YES: use ask price if we want to BUY, bid price if we want to SELL
        # For simplicity, use mid price for comparison
        if market.yes_bid is not None and market.yes_ask is not None:
            market_up_price = (market.yes_bid + market.yes_ask) / 2.0
        else:
            print(f"⚠️  No YES prices available for {market.market_id}")
            self.logger.log_error("missing_orderbook", "No YES prices available", {
                "market_id": market.market_id
            })
            return
        
        if market.no_bid is not None and market.no_ask is not None:
            market_down_price = (market.no_bid + market.no_ask) / 2.0
        else:
            print(f"⚠️  No NO prices available for {market.market_id}")
            self.logger.log_error("missing_orderbook", "No NO prices available", {
                "market_id": market.market_id
            })
            return
        
        # Log orderbook snapshot
        self.logger.log_orderbook(
            market_id=market.market_id,
            yes_bid=market.yes_bid,
            yes_ask=market.yes_ask,
            no_bid=market.no_bid,
            no_ask=market.no_ask,
            yes_token_id=market.yes_token_id,
            no_token_id=market.no_token_id
        )
        
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
        
        # Log sizing calculation
        self.logger.log_calculation(
            market_id=market.market_id,
            calculation_type="sizing",
            inputs={
                "fair_prob_up": fair_up,
                "fair_prob_down": fair_down,
                "market_prob_up": market_up_price,
                "market_prob_down": market_down_price,
                "edge_up": edge_up,
                "edge_down": edge_down,
                "edge_threshold": self.edge_threshold,
                "sizing_factor": self.sizing_factor,
                "max_position_size": self.config.trading.max_position_size
            },
            outputs=sizing
        )
        
        print(f"Edge: UP={edge_up:+.1%}, DOWN={edge_down:+.1%}")
        
        # Determine decision and log it
        if sizing["buy_yes"]:
            print(f"→ BUY YES size: {sizing['buy_yes']:.1f} (market underpricing UP)")
            
            self.logger.log_decision(
                market_id=market.market_id,
                decision_type="trade",
                decision="buy_yes",
                reasoning={
                    "edge": edge_up,
                    "fair_prob": fair_up,
                    "market_prob": market_up_price,
                    "threshold": self.edge_threshold,
                    "explanation": "Market underpricing UP outcome"
                },
                sizing=sizing
            )
            
            if not self.dry_run:
                await self.place_orders(market, sizing)
            else:
                print("  [DRY RUN] Order not placed")
                
        elif sizing["sell_yes"]:
            print(f"→ SELL YES size: {sizing['sell_yes']:.1f} (market overpricing UP)")
            
            self.logger.log_decision(
                market_id=market.market_id,
                decision_type="trade",
                decision="sell_yes",
                reasoning={
                    "edge": edge_up,
                    "fair_prob": fair_up,
                    "market_prob": market_up_price,
                    "threshold": self.edge_threshold,
                    "explanation": "Market overpricing UP outcome"
                },
                sizing=sizing
            )
            
            if not self.dry_run:
                await self.place_orders(market, sizing)
            else:
                print("  [DRY RUN] Order not placed")
                
        elif sizing["buy_no"]:
            print(f"→ BUY NO size: {sizing['buy_no']:.1f} (market underpricing DOWN)")
            
            self.logger.log_decision(
                market_id=market.market_id,
                decision_type="trade",
                decision="buy_no",
                reasoning={
                    "edge": edge_down,
                    "fair_prob": fair_down,
                    "market_prob": market_down_price,
                    "threshold": self.edge_threshold,
                    "explanation": "Market underpricing DOWN outcome"
                },
                sizing=sizing
            )
            
            if not self.dry_run:
                await self.place_orders(market, sizing)
            else:
                print("  [DRY RUN] Order not placed")
                
        elif sizing["sell_no"]:
            print(f"→ SELL NO size: {sizing['sell_no']:.1f} (market overpricing DOWN)")
            
            self.logger.log_decision(
                market_id=market.market_id,
                decision_type="trade",
                decision="sell_no",
                reasoning={
                    "edge": edge_down,
                    "fair_prob": fair_down,
                    "market_prob": market_down_price,
                    "threshold": self.edge_threshold,
                    "explanation": "Market overpricing DOWN outcome"
                },
                sizing=sizing
            )
            
            if not self.dry_run:
                await self.place_orders(market, sizing)
            else:
                print("  [DRY RUN] Order not placed")
        else:
            print("→ No edge, pass")
            
            self.logger.log_decision(
                market_id=market.market_id,
                decision_type="pass",
                decision="no_edge",
                reasoning={
                    "edge_up": edge_up,
                    "edge_down": edge_down,
                    "threshold": self.edge_threshold,
                    "explanation": "No edge exceeds threshold"
                },
                sizing=sizing
            )
    
    async def place_orders(self, market: PolymarketMarket, sizing: dict):
        """
        Place orders on Polymarket based on sizing.
        
        TODO: Implement actual order placement
        """
        # Log trade attempt
        for key, value in sizing.items():
            if value and value > 0:
                self.logger.log_trade(
                    market_id=market.market_id,
                    trade_type="order_place",
                    side=key,
                    size=value,
                    price=None,  # Would be filled in with actual order price
                    order_id=None,  # Would be filled in with actual order ID
                    status="dry_run" if self.dry_run else "pending"
                )
        
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
        print(f"Assets: {', '.join(self.config.trading.trading_symbols)}")
        try:
            # Use optimized multi-asset fetching - respects TRADING_SYMBOLS from .env
            crypto_markets = self.poly_client.get_crypto_15min_markets(self.config.trading.trading_symbols)
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
                strike_str = f"${market.strike_price:.0f}" if market.strike_price else "TBD"
                print(f"  Strike: {strike_str} | Expires in: {market.minutes_to_expiry():.1f} min")
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
        
        # Start Polymarket RTDS WebSocket for crypto price feed (from Chainlink oracles)
        print("\nConnecting to Polymarket RTDS...")
        
        # Create callback that properly handles async
        async def handle_tick(tick: PriceTick):
            await self.on_price_tick(tick)
        
        # Convert trading symbols to RTDS format (e.g., BTC -> btc/usd)
        rtds_symbols = [f"{symbol.lower()}/usd" for symbol in self.config.trading.trading_symbols]
        
        ws = PolymarketRTDSClient(
            symbols=rtds_symbols,
            on_tick=handle_tick
        )
        
        # Start streaming
        try:
            await ws.connect()
        except KeyboardInterrupt:
            print("\n\n🛑 Shutting down...")
        except Exception as e:
            print(f"\n\n❌ Error: {e}")
            self.logger.log_error("runtime_error", str(e))
        finally:
            # Close logger
            self.logger.close()


async def main():
    """Run the market maker."""
    mm = PolymarketMarketMaker()
    try:
        await mm.run()
    except KeyboardInterrupt:
        print("\nShutdown initiated by user")
    finally:
        # Ensure logger is closed
        if hasattr(mm, 'logger'):
            mm.logger.close()


if __name__ == "__main__":
    asyncio.run(main())
