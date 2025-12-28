"""
Comprehensive logging system for Polymarket Market Maker.

Logs all data with maximum verbosity for performance analysis and replay:
- Price ticks (BTC/ETH/etc from Chainlink via RTDS)
- Market data (strike prices, expiry times, market state)
- Order books (bids/asks for YES and NO tokens)
- Pricing calculations (volatility, probabilities, edges)
- Trading decisions (sizing, order placement)
- Performance metrics (tick rates, latency)

All logs are written in JSONL format (one JSON object per line) for easy replay
and analysis. Each log entry has a timestamp and event type for filtering.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any


class PerformanceLogger:
    """
    High-verbosity logger for market maker performance analysis.
    
    Logs everything to JSONL files organized by session.
    """
    
    def __init__(self, log_dir: str = "logs", session_name: Optional[str] = None):
        """
        Initialize logger.
        
        Args:
            log_dir: Directory to store log files
            session_name: Optional session name. If None, uses timestamp.
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Create session directory
        if session_name is None:
            session_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        self.session_dir = self.log_dir / session_name
        self.session_dir.mkdir(exist_ok=True)
        
        # Open log files
        self.price_log = open(self.session_dir / "price_ticks.jsonl", "w", buffering=1)
        self.market_log = open(self.session_dir / "markets.jsonl", "w", buffering=1)
        self.orderbook_log = open(self.session_dir / "orderbooks.jsonl", "w", buffering=1)
        self.calculation_log = open(self.session_dir / "calculations.jsonl", "w", buffering=1)
        self.decision_log = open(self.session_dir / "decisions.jsonl", "w", buffering=1)
        self.trade_log = open(self.session_dir / "trades.jsonl", "w", buffering=1)
        self.performance_log = open(self.session_dir / "performance.jsonl", "w", buffering=1)
        self.event_log = open(self.session_dir / "events.jsonl", "w", buffering=1)
        
        # Track session start
        self.session_start = time.time()
        self.tick_count = 0
        self.quote_count = 0
        
        # Write session metadata
        self._log_event("session_start", {
            "session_name": session_name,
            "log_dir": str(self.session_dir),
            "start_time": self.session_start,
            "start_time_iso": datetime.fromtimestamp(self.session_start, tz=timezone.utc).isoformat()
        })
        
        print(f"📝 Logging to: {self.session_dir}")
    
    def _write_log(self, file_handle, event_type: str, data: Dict[str, Any]):
        """Write a log entry to a file."""
        entry = {
            "timestamp": time.time(),
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **data
        }
        file_handle.write(json.dumps(entry) + "\n")
    
    def _log_event(self, event_type: str, data: Dict[str, Any]):
        """Log a general event."""
        self._write_log(self.event_log, event_type, data)
    
    def log_price_tick(self, symbol: str, price: float, timestamp: float, 
                       source: str = "rtds", additional_data: Optional[Dict] = None):
        """
        Log a price tick from RTDS or other source.
        
        Args:
            symbol: Asset symbol (e.g., "BTC", "ETH")
            price: Price in USD
            timestamp: Unix timestamp of the price
            source: Data source ("rtds", "chainlink", etc.)
            additional_data: Any additional data to include
        """
        self.tick_count += 1
        
        data = {
            "symbol": symbol,
            "price": price,
            "price_timestamp": timestamp,
            "price_timestamp_iso": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
            "source": source,
            "tick_number": self.tick_count
        }
        
        if additional_data:
            data.update(additional_data)
        
        self._write_log(self.price_log, "price_tick", data)
    
    def log_market_state(self, market_id: str, question: str, strike_price: Optional[float],
                        start_time: float, expiry_time: float, minutes_remaining: float,
                        status: str, additional_data: Optional[Dict] = None):
        """
        Log current market state.
        
        Args:
            market_id: Polymarket market ID
            question: Market question
            strike_price: Strike price (or None if not set yet)
            start_time: Market start timestamp
            expiry_time: Market expiry timestamp
            minutes_remaining: Minutes until expiry
            status: Market status ("waiting", "active", "expired")
            additional_data: Any additional data to include
        """
        data = {
            "market_id": market_id,
            "question": question,
            "strike_price": strike_price,
            "start_time": start_time,
            "start_time_iso": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
            "expiry_time": expiry_time,
            "expiry_time_iso": datetime.fromtimestamp(expiry_time, tz=timezone.utc).isoformat(),
            "minutes_remaining": minutes_remaining,
            "status": status
        }
        
        if additional_data:
            data.update(additional_data)
        
        self._write_log(self.market_log, "market_state", data)
    
    def log_orderbook(self, market_id: str, yes_bid: Optional[float], yes_ask: Optional[float],
                     no_bid: Optional[float], no_ask: Optional[float],
                     yes_token_id: Optional[str] = None, no_token_id: Optional[str] = None,
                     full_book: Optional[Dict] = None):
        """
        Log order book snapshot.
        
        Args:
            market_id: Polymarket market ID
            yes_bid: Best bid for YES token
            yes_ask: Best ask for YES token
            no_bid: Best bid for NO token
            no_ask: Best ask for NO token
            yes_token_id: YES token ID
            no_token_id: NO token ID
            full_book: Full order book data (all levels) if available
        """
        data = {
            "market_id": market_id,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": no_bid,
            "no_ask": no_ask,
            "yes_mid": (yes_bid + yes_ask) / 2 if (yes_bid and yes_ask) else None,
            "no_mid": (no_bid + no_ask) / 2 if (no_bid and no_ask) else None,
            "yes_spread": yes_ask - yes_bid if (yes_bid and yes_ask) else None,
            "no_spread": no_ask - no_bid if (no_bid and no_ask) else None,
            "yes_token_id": yes_token_id,
            "no_token_id": no_token_id
        }
        
        if full_book:
            data["full_book"] = full_book
        
        self._write_log(self.orderbook_log, "orderbook_snapshot", data)
    
    def log_calculation(self, market_id: str, calculation_type: str, 
                       inputs: Dict[str, Any], outputs: Dict[str, Any],
                       additional_data: Optional[Dict] = None):
        """
        Log a pricing calculation.
        
        Args:
            market_id: Polymarket market ID
            calculation_type: Type of calculation ("volatility", "probability", "sizing", etc.)
            inputs: Input parameters to the calculation
            outputs: Output values from the calculation
            additional_data: Any additional data to include
        """
        self.quote_count += 1
        
        data = {
            "market_id": market_id,
            "calculation_type": calculation_type,
            "inputs": inputs,
            "outputs": outputs,
            "quote_number": self.quote_count
        }
        
        if additional_data:
            data.update(additional_data)
        
        self._write_log(self.calculation_log, "calculation", data)
    
    def log_decision(self, market_id: str, decision_type: str, decision: str,
                    reasoning: Dict[str, Any], sizing: Optional[Dict] = None,
                    additional_data: Optional[Dict] = None):
        """
        Log a trading decision.
        
        Args:
            market_id: Polymarket market ID
            decision_type: Type of decision ("trade", "pass", "cancel", etc.)
            decision: The actual decision made ("buy_yes", "sell_no", "pass", etc.)
            reasoning: Explanation of why this decision was made (edges, probabilities, etc.)
            sizing: Position sizing details if applicable
            additional_data: Any additional data to include
        """
        data = {
            "market_id": market_id,
            "decision_type": decision_type,
            "decision": decision,
            "reasoning": reasoning
        }
        
        if sizing:
            data["sizing"] = sizing
        
        if additional_data:
            data.update(additional_data)
        
        self._write_log(self.decision_log, "decision", data)
    
    def log_trade(self, market_id: str, trade_type: str, side: str, size: float,
                 price: Optional[float] = None, order_id: Optional[str] = None,
                 status: str = "pending", additional_data: Optional[Dict] = None):
        """
        Log a trade execution (or attempt).
        
        Args:
            market_id: Polymarket market ID
            trade_type: Type of trade ("order_place", "order_cancel", "order_fill", etc.)
            side: Trade side ("buy_yes", "sell_yes", "buy_no", "sell_no")
            size: Trade size
            price: Trade price if applicable
            order_id: Order ID if applicable
            status: Trade status ("pending", "filled", "cancelled", "rejected")
            additional_data: Any additional data to include
        """
        data = {
            "market_id": market_id,
            "trade_type": trade_type,
            "side": side,
            "size": size,
            "price": price,
            "order_id": order_id,
            "status": status
        }
        
        if additional_data:
            data.update(additional_data)
        
        self._write_log(self.trade_log, "trade", data)
    
    def log_performance(self, metric_type: str, metrics: Dict[str, Any]):
        """
        Log performance metrics.
        
        Args:
            metric_type: Type of metrics ("tick_rate", "latency", "pnl", etc.)
            metrics: The metrics to log
        """
        data = {
            "metric_type": metric_type,
            "metrics": metrics,
            "session_uptime": time.time() - self.session_start,
            "total_ticks": self.tick_count,
            "total_quotes": self.quote_count
        }
        
        self._write_log(self.performance_log, "performance", data)
    
    def log_error(self, error_type: str, error_message: str, 
                 context: Optional[Dict] = None):
        """
        Log an error.
        
        Args:
            error_type: Type of error
            error_message: Error message
            context: Additional context about the error
        """
        data = {
            "error_type": error_type,
            "error_message": error_message
        }
        
        if context:
            data["context"] = context
        
        self._log_event("error", data)
    
    def log_config(self, config: Dict[str, Any]):
        """
        Log configuration at startup.
        
        Args:
            config: Configuration dictionary
        """
        self._log_event("config", {"config": config})
    
    def close(self):
        """Close all log files."""
        # Check if already closed
        if not hasattr(self, 'price_log') or self.price_log.closed:
            return
        
        # Log session end
        session_duration = time.time() - self.session_start
        self._log_event("session_end", {
            "duration_seconds": session_duration,
            "total_ticks": self.tick_count,
            "total_quotes": self.quote_count,
            "avg_ticks_per_second": self.tick_count / session_duration if session_duration > 0 else 0
        })
        
        # Close files safely
        for log_file in [self.price_log, self.market_log, self.orderbook_log, 
                         self.calculation_log, self.decision_log, self.trade_log,
                         self.performance_log, self.event_log]:
            if log_file and not log_file.closed:
                log_file.close()
        
        print(f"📝 Session logs saved to: {self.session_dir}")
        print(f"   Total ticks: {self.tick_count}")
        print(f"   Total quotes: {self.quote_count}")
        print(f"   Duration: {session_duration:.1f}s")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
