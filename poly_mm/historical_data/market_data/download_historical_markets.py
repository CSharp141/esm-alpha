#!/usr/bin/env python3
"""
Download Historical 15-Minute BTC Markets from Polymarket

This script downloads complete market data for BTC 15-minute "Up or Down" markets
from the last 30 days, including:
- Market metadata (question, strike, expiry, start times)
- Complete price history for both YES and NO tokens (CLOB API)
  * Filtered to only include data between market start and expiry times
- Order book snapshots (bids/asks)
- Settlement results (final prices, winners)

Price history is automatically filtered to each market's active period (between
start_time and expiry_time) to ensure clean, relevant data for backtesting.

Markets occur every 15 minutes at :00, :15, :30, :45 past each hour.
Data saved as JSON files for replay and backtesting.

Usage:
    python download_historical_markets.py [--days 30] [--asset BTC]
    
Note: Price history is limited to ~30 days by the CLOB API, regardless of
how many days of markets you download. Older markets will only have recent
price history available.
"""

import os
import json
import time
import argparse
import re
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict


# Polymarket API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_HOST = "https://clob.polymarket.com"


@dataclass
class PricePoint:
    """Single price data point."""
    timestamp: float  # Unix timestamp
    price: float  # Price from 0.0 to 1.0


@dataclass
class HistoricalMarket:
    """Complete historical market data."""
    # Market identification
    market_id: str
    slug: str
    question: str
    
    # Timing
    start_time: float  # Unix timestamp
    expiry_time: float  # Unix timestamp
    
    # Pricing (if available)
    strike_price: Optional[float]
    
    # Token IDs
    yes_token_id: str
    no_token_id: str
    
    # Settlement (if available)
    settled: bool
    winning_outcome: Optional[str]  # "YES" or "NO"
    
    # Order book snapshot (at time of download)
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    no_bid: Optional[float]
    no_ask: Optional[float]
    
    # Volume data
    volume: Optional[float]
    liquidity: Optional[float]
    
    # Price history (full historical prices from CLOB API)
    yes_price_history: Optional[List[Dict[str, float]]]  # [{"t": timestamp, "p": price}, ...]
    no_price_history: Optional[List[Dict[str, float]]]   # [{"t": timestamp, "p": price}, ...]
    
    # Metadata
    download_time: float  # When we downloaded this data
    status: str  # "active", "closed", "resolved"


def generate_15min_timestamps(days: int = 30) -> List[int]:
    """
    Generate all 15-minute boundary timestamps for the last N days.
    
    Returns timestamps for :00, :15, :30, :45 past each hour.
    
    Args:
        days: Number of days to go back
        
    Returns:
        List of Unix timestamps (sorted oldest to newest)
    """
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)
    
    # Round down to nearest 15-minute boundary
    current_ts = int(start_date.timestamp())
    current_ts = (current_ts // 900) * 900
    
    end_ts = int(now.timestamp())
    
    timestamps = []
    ts = current_ts
    while ts <= end_ts:
        timestamps.append(ts)
        ts += 900  # 15 minutes = 900 seconds
    
    return timestamps


def build_slug(asset: str, expiry_timestamp: int) -> str:
    """
    Build market slug from asset and expiry timestamp.
    
    Args:
        asset: Asset ticker (e.g., "BTC")
        expiry_timestamp: Market expiry Unix timestamp
        
    Returns:
        Slug like "btc-updown-15m-1735315800"
    """
    return f"{asset.lower()}-updown-15m-{expiry_timestamp}"


def fetch_market_by_slug(slug: str, session: requests.Session) -> Optional[Dict[str, Any]]:
    """
    Fetch market data from Gamma API by slug.
    
    Args:
        slug: Market slug
        session: Requests session for connection pooling
        
    Returns:
        Market data dict or None if not found
    """
    try:
        url = f"{GAMMA_API}/events/slug/{slug}"
        resp = session.get(url, timeout=10)
        
        if resp.status_code == 404:
            return None
        
        resp.raise_for_status()
        return resp.json()
        
    except requests.exceptions.RequestException as e:
        print(f"  ⚠️  Error fetching {slug}: {e}")
        return None


def parse_clob_token_ids(raw: str) -> tuple[str, str]:
    """
    Parse clobTokenIds from market data.
    
    Format can be:
    - "123,456" (comma-separated)
    - '["123","456"]' (JSON array)
    
    Returns:
        (yes_token_id, no_token_id)
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Missing clobTokenIds")
    
    if raw.startswith("["):
        arr = json.loads(raw)
        return str(arr[0]), str(arr[1])
    
    parts = [p.strip() for p in raw.split(",")]
    return parts[0], parts[1]


def fetch_order_book(token_id: str, session: requests.Session) -> Dict[str, Any]:
    """
    Fetch order book from CLOB API.
    
    Args:
        token_id: ERC-1155 token ID
        session: Requests session
        
    Returns:
        Order book dict with bids/asks
    """
    try:
        url = f"{CLOB_HOST}/book"
        resp = session.get(url, params={"token_id": token_id}, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {"bids": [], "asks": []}


def fetch_price_history(token_id: str, session: requests.Session, 
                       start_time: Optional[float] = None, 
                       end_time: Optional[float] = None) -> Optional[List[Dict[str, float]]]:
    """
    Fetch price history for a token from CLOB API, filtered by time range.
    
    Uses interval=max to get maximum available history, then filters to only
    include data points between the market's start and end times.
    
    Args:
        token_id: ERC-1155 token ID
        session: Requests session
        start_time: Market start timestamp (Unix). If provided, filters out data before this.
        end_time: Market end timestamp (Unix). If provided, filters out data after this.
        
    Returns:
        List of price points [{"t": timestamp, "p": price}, ...] or None if error
    """
    try:
        url = f"{CLOB_HOST}/prices-history"
        params = {
            "market": token_id,
            "interval": "max"  # Get maximum available history (~30 days)
        }
        resp = session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # Get the history array
        history = data.get("history", [])
        if not history:
            return None
        
        # Filter by time range if provided
        if start_time is not None or end_time is not None:
            filtered_history = []
            for point in history:
                timestamp = point.get("t", 0)
                
                # Skip points before start time
                if start_time is not None and timestamp < start_time:
                    continue
                    
                # Skip points after end time
                if end_time is not None and timestamp > end_time:
                    continue
                    
                filtered_history.append(point)
            
            return filtered_history if filtered_history else None
        
        return history
        
    except requests.exceptions.RequestException as e:
        print(f"  ⚠️  Error fetching price history for token {token_id[:20]}...: {e}")
        return None
    except Exception as e:
        print(f"  ⚠️  Unexpected error fetching price history: {e}")
        return None


def parse_market_data(event: Dict[str, Any], session: requests.Session) -> Optional[HistoricalMarket]:
    """
    Parse market data from Gamma API event response.
    
    Args:
        event: Event JSON from Gamma API
        session: Requests session for fetching order books
        
    Returns:
        HistoricalMarket or None if parsing fails
    """
    try:
        markets = event.get("markets", [])
        if not markets:
            return None
        
        market = markets[0]  # 15-min events have single binary market
        
        # Extract basic info
        market_id = market.get("conditionId")
        if not market_id:
            return None
        
        slug = event.get("slug", "")
        question = market.get("question") or event.get("title", "")
        
        # Parse timing
        end_iso = market.get("endDate") or event.get("endDate")
        if not end_iso:
            return None
        
        expiry_time = datetime.fromisoformat(end_iso.replace('Z', '+00:00')).timestamp()
        start_time = expiry_time - 900  # 15 minutes before
        
        # Parse token IDs
        yes_id, no_id = parse_clob_token_ids(market.get("clobTokenIds", ""))
        
        # Get status
        closed = event.get("closed", False)
        status = "closed" if closed else "active"
        
        # Try to extract strike price from question
        strike_price = None
        strike_match = re.search(r'\$([0-9,]+(?:\.[0-9]+)?)', question)
        if strike_match:
            strike_price = float(strike_match.group(1).replace(',', ''))
        
        # Check if settled - parse outcomePrices to determine winner
        winning_outcome = None
        if closed:
            # Check UMA resolution status
            uma_status = market.get("umaResolutionStatus")
            if uma_status == "resolved":
                status = "resolved"
                
                # Parse outcomePrices: ["0", "1"] means index 1 won
                outcome_prices_str = market.get("outcomePrices", "")
                outcomes_str = market.get("outcomes", "")
                
                if outcome_prices_str and outcomes_str:
                    try:
                        outcome_prices = json.loads(outcome_prices_str)
                        outcomes = json.loads(outcomes_str)
                        
                        # Find which outcome has price of 1.0 (winner)
                        for i, price in enumerate(outcome_prices):
                            if float(price) >= 0.99:  # Winner has price ~1.0
                                if i < len(outcomes):
                                    winning_outcome = outcomes[i].upper()
                                break
                    except (json.JSONDecodeError, ValueError, IndexError):
                        pass
        
        # Fetch order books (for closed markets this may be empty)
        yes_book = fetch_order_book(yes_id, session)
        no_book = fetch_order_book(no_id, session)
        
        yes_bid = float(yes_book.get("bids", [{}])[-1].get("price", 0)) if yes_book.get("bids") else None
        yes_ask = float(yes_book.get("asks", [{}])[-1].get("price", 0)) if yes_book.get("asks") else None
        no_bid = float(no_book.get("bids", [{}])[-1].get("price", 0)) if no_book.get("bids") else None
        no_ask = float(no_book.get("asks", [{}])[-1].get("price", 0)) if no_book.get("asks") else None
        
        # Fetch complete price history for both tokens, filtered to market's time range
        print("    📊 Fetching price history for YES token (filtered to market time range)...")
        yes_price_history = fetch_price_history(yes_id, session, start_time=start_time, end_time=expiry_time)
        time.sleep(0.2)  # Rate limiting
        
        print("    📊 Fetching price history for NO token (filtered to market time range)...")
        no_price_history = fetch_price_history(no_id, session, start_time=start_time, end_time=expiry_time)
        time.sleep(0.2)  # Rate limiting
        
        # Volume/liquidity
        volume = market.get("volume")
        liquidity = market.get("liquidity")
        
        return HistoricalMarket(
            market_id=market_id,
            slug=slug,
            question=question,
            start_time=start_time,
            expiry_time=expiry_time,
            strike_price=strike_price,
            yes_token_id=yes_id,
            no_token_id=no_id,
            settled=closed,
            winning_outcome=winning_outcome,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            volume=volume,
            liquidity=liquidity,
            yes_price_history=yes_price_history,
            no_price_history=no_price_history,
            download_time=time.time(),
            status=status
        )
        
    except Exception as e:
        print(f"  ⚠️  Error parsing market: {e}")
        return None


def save_market_data(markets: List[HistoricalMarket], output_file: str):
    """
    Save market data to JSON file.
    
    Args:
        markets: List of HistoricalMarket objects
        output_file: Output JSON file path
    """
    data = {
        "download_date": datetime.now(timezone.utc).isoformat(),
        "total_markets": len(markets),
        "markets": [asdict(m) for m in markets]
    }
    
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\n✅ Saved {len(markets)} markets to {output_file}")


def generate_summary_report(markets: List[HistoricalMarket]) -> str:
    """
    Generate summary statistics report.
    
    Args:
        markets: List of downloaded markets
        
    Returns:
        Formatted summary string
    """
    if not markets:
        return "No markets found."
    
    total = len(markets)
    active = sum(1 for m in markets if m.status == "active")
    closed = sum(1 for m in markets if m.status == "closed")
    resolved = sum(1 for m in markets if m.status == "resolved")
    
    with_strike = sum(1 for m in markets if m.strike_price is not None)
    with_books = sum(1 for m in markets if m.yes_bid is not None or m.yes_ask is not None)
    with_yes_history = sum(1 for m in markets if m.yes_price_history is not None and len(m.yes_price_history) > 0)
    with_no_history = sum(1 for m in markets if m.no_price_history is not None and len(m.no_price_history) > 0)
    
    # Calculate average price history length
    yes_history_lengths = [len(m.yes_price_history) for m in markets if m.yes_price_history]
    no_history_lengths = [len(m.no_price_history) for m in markets if m.no_price_history]
    avg_yes_points = sum(yes_history_lengths) / len(yes_history_lengths) if yes_history_lengths else 0
    avg_no_points = sum(no_history_lengths) / len(no_history_lengths) if no_history_lengths else 0
    
    # Date range
    start_date = datetime.fromtimestamp(markets[0].start_time, tz=timezone.utc)
    end_date = datetime.fromtimestamp(markets[-1].start_time, tz=timezone.utc)
    
    report = f"""
================================================================================
DOWNLOAD SUMMARY
================================================================================

Total Markets:     {total}
  - Active:        {active}
  - Closed:        {closed}
  - Resolved:      {resolved}

Data Quality:
  - With Strike:   {with_strike} ({100*with_strike/total:.1f}%)
  - With Books:    {with_books} ({100*with_books/total:.1f}%)

Price History:
  - YES History:   {with_yes_history} markets ({100*with_yes_history/total:.1f}%)
  - NO History:    {with_no_history} markets ({100*with_no_history/total:.1f}%)
  - Avg Points:    {avg_yes_points:.0f} YES, {avg_no_points:.0f} NO per market

Date Range:
  Start:           {start_date.strftime('%Y-%m-%d %H:%M UTC')}
  End:             {end_date.strftime('%Y-%m-%d %H:%M UTC')}
  Duration:        {(end_date - start_date).days} days

Markets per Day:   {total / max(1, (end_date - start_date).days):.1f}
Expected (4/hour): 96 per day

================================================================================
"""
    return report


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Download historical 15-minute BTC markets from Polymarket"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to download (default: 30)"
    )
    parser.add_argument(
        "--asset",
        type=str,
        default="BTC",
        choices=["BTC", "ETH", "SOL", "XRP"],
        help="Asset to download (default: BTC)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file (default: historical_{asset}_{days}d.json)"
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=0.2,
        help="Delay between API requests in seconds (default: 0.2)"
    )
    
    args = parser.parse_args()
    
    # Determine output file
    if args.output:
        output_file = args.output
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_file = os.path.join(
            script_dir,
            f"historical_{args.asset.lower()}_{args.days}d.json"
        )
    
    print("="*80)
    print("POLYMARKET HISTORICAL MARKET DOWNLOADER")
    print("="*80)
    print(f"\nAsset:        {args.asset}")
    print(f"Days:         {args.days}")
    print(f"Output:       {output_file}")
    print(f"Rate Limit:   {args.rate_limit}s between requests")
    print()
    
    # Generate timestamps for all 15-minute boundaries
    print(f"[1/4] Generating timestamps for last {args.days} days...")
    timestamps = generate_15min_timestamps(args.days)
    print(f"      Generated {len(timestamps)} timestamps ({len(timestamps)/4:.0f} hours)")
    print(f"      From: {datetime.fromtimestamp(timestamps[0], tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"      To:   {datetime.fromtimestamp(timestamps[-1], tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    
    # Create session for connection pooling
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Polymarket-Historical-Downloader/1.0'
    })
    
    # Download markets
    print(f"\n[2/4] Downloading {args.asset} market data...")
    markets = []
    found_count = 0
    not_found_count = 0
    error_count = 0
    
    for i, ts in enumerate(timestamps, 1):
        slug = build_slug(args.asset, ts)
        dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        
        # Progress indicator
        if i % 10 == 0:
            print(f"      Progress: {i}/{len(timestamps)} ({100*i/len(timestamps):.1f}%) - Found: {found_count}, Missing: {not_found_count}")
        
        # Fetch market
        event = fetch_market_by_slug(slug, session)
        
        if event is None:
            not_found_count += 1
            if i % 50 == 0:  # Only log every 50th missing market to avoid spam
                print(f"      {dt_str}: Not found")
        else:
            market = parse_market_data(event, session)
            if market:
                markets.append(market)
                found_count += 1
            else:
                error_count += 1
                print(f"      {dt_str}: Parse error")
        
        # Rate limiting
        time.sleep(args.rate_limit)
    
    print(f"\n      Complete: {found_count} markets downloaded, {not_found_count} not found, {error_count} errors")
    
    # Sort by start time
    print("\n[3/4] Sorting markets by start time...")
    markets.sort(key=lambda m: m.start_time)
    
    # Save data
    print(f"\n[4/4] Saving to {output_file}...")
    save_market_data(markets, output_file)
    
    # Generate report
    print(generate_summary_report(markets))
    
    # Additional stats
    if markets:
        print("Sample Market:")
        sample = markets[len(markets)//2]  # Middle market
        print(f"  Question:  {sample.question}")
        print(f"  Start:     {datetime.fromtimestamp(sample.start_time, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  Expiry:    {datetime.fromtimestamp(sample.expiry_time, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  Strike:    ${sample.strike_price:,.2f}" if sample.strike_price else "  Strike:    Unknown")
        print(f"  Status:    {sample.status}")
        if sample.winning_outcome:
            print(f"  Winner:    {sample.winning_outcome}")
        
        # Price history info
        yes_hist_len = len(sample.yes_price_history) if sample.yes_price_history else 0
        no_hist_len = len(sample.no_price_history) if sample.no_price_history else 0
        print(f"  Price Pts: {yes_hist_len} YES, {no_hist_len} NO")
        
        if sample.yes_price_history and len(sample.yes_price_history) > 0:
            first_price = sample.yes_price_history[0]['p']
            last_price = sample.yes_price_history[-1]['p']
            print(f"  YES Range: {first_price:.3f} → {last_price:.3f}")
        
        print()
    
    print("✅ Download complete!")
    print()


if __name__ == "__main__":
    main()
