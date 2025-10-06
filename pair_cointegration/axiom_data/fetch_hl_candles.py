#!/usr/bin/env python3
"""
Fetch historical OHLCV candles for a list of Hyperliquid tickers.

Usage examples:
  python fetch_hyperliquid_candles.py --tickers-file tickers.txt --timeframe 1h --lookback 90d
  python fetch_hyperliquid_candles.py --tickers BTC,ETH,SOL,FARTCOIN --timeframe 5m --lookback 48h
  python fetch_hyperliquid_candles.py --tickers-file tickers.txt --timeframe 1d --start 2024-01-01

Outputs:
  - data/candles_<SYMBOL>_<timeframe>.csv  (one per coin)
  - data/all_candles_<timeframe>.csv       (combined)
"""

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from typing import Iterable, List, Dict, Any, Optional
from collections import deque
import threading

import requests

HL_INFO_URL = "https://api.hyperliquid.xyz/info"

# Common Hyperliquid intervals. (Feel free to add others if your account supports them.)
VALID_INTERVALS = {
    "1m","3m","5m","15m","30m",
    "1h","2h","4h","8h","12h",
    "1d","3d","1w","1M"
}

class RateLimiter:
    """
    Rate limiter for Hyperliquid API based on documentation:
    - REST requests share an aggregated weight limit of 1200 per minute
    - candleSnapshot has weight 20 + additional weight per 60 items returned
    """
    def __init__(self, max_weight_per_minute=1200, safety_margin=0.8, verbose=False):
        self.max_weight_per_minute = int(max_weight_per_minute * safety_margin)  # Use 80% of limit for safety
        self.requests = deque()  # Store (timestamp, weight) tuples
        self.lock = threading.Lock()
        self.verbose = verbose
        
    def _cleanup_old_requests(self):
        """Remove requests older than 1 minute"""
        current_time = time.time()
        while self.requests and current_time - self.requests[0][0] > 60:
            self.requests.popleft()
    
    def _current_weight(self):
        """Calculate current weight in the last minute"""
        self._cleanup_old_requests()
        return sum(weight for _, weight in self.requests)
    
    def wait_if_needed(self, request_weight=20):
        """Wait if making this request would exceed rate limit"""
        with self.lock:
            self._cleanup_old_requests()
            current_weight = self._current_weight()
            
            if current_weight + request_weight > self.max_weight_per_minute:
                # Calculate how long to wait for the oldest request to expire
                if self.requests:
                    oldest_time = self.requests[0][0]
                    wait_time = 61 - (time.time() - oldest_time)  # Wait for oldest to expire + 1 sec buffer
                    if wait_time > 0:
                        print(f"Rate limit approaching. Waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        self._cleanup_old_requests()
    
    def record_request(self, weight=20, items_returned=0):
        """Record a request with its weight"""
        # candleSnapshot weight = 20 + floor(items_returned / 60)
        actual_weight = weight + (items_returned // 60)
        
        with self.lock:
            self.requests.append((time.time(), actual_weight))
            if self.verbose:
                print(f"Request recorded: weight {actual_weight} (base: {weight}, items: {items_returned})")

# Global rate limiter instance
rate_limiter = RateLimiter(verbose=False)


def parse_args():
    p = argparse.ArgumentParser(description="Fetch Hyperliquid historical candles for many coins.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--tickers", help="Comma-separated tickers (e.g., BTC,ETH,SOL)")
    g.add_argument("--tickers-file", help="Text file with one ticker per line")
    p.add_argument("--timeframe", default="1h", help=f"HL interval: {sorted(VALID_INTERVALS)} (default: 1h)")
    p.add_argument("--lookback", help="How far back (e.g. 90d, 48h, 30m, 2y). Ignored if --start given.")
    p.add_argument("--start", help="Start time (YYYY-MM-DD or full ISO like 2024-01-01T00:00:00).")
    p.add_argument("--end", help="End time (default now). Same format as --start.")
    p.add_argument("--outdir", default="data", help="Output directory (default: data)")
    p.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between coins (default: 1.0 for rate limiting)")
    p.add_argument("--verbose-rate-limit", action="store_true", help="Show detailed rate limiting info")
    return p.parse_args()

def read_tickers(args) -> List[str]:
    if args.tickers:
        raw = [t.strip() for t in args.tickers.split(",")]
    else:
        with open(args.tickers_file, "r", encoding="utf-8") as f:
            raw = [line.strip() for line in f if line.strip()]
    # de-dup preserve order
    seen = set()
    out = []
    for t in raw:
        t = t.upper()
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

def parse_iso_guess(s: str) -> dt.datetime:
    # Accept YYYY-MM-DD or full ISO; interpret naive as UTC.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)
    # Try full ISO
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        raise ValueError(f"Could not parse date/time: {s}")

def parse_lookback(s: str) -> dt.timedelta:
    # e.g., 90d, 48h, 30m, 2y
    m = re.fullmatch(r"(\d+)\s*([mhdwy])", s.strip().lower())
    if not m:
        raise ValueError("Lookback must look like '90d', '48h', '30m', '2y', etc.")
    n, unit = int(m.group(1)), m.group(2)
    if unit == "m":
        return dt.timedelta(minutes=n)
    if unit == "h":
        return dt.timedelta(hours=n)
    if unit == "d":
        return dt.timedelta(days=n)
    if unit == "w":
        return dt.timedelta(weeks=n)
    if unit == "y":
        return dt.timedelta(days=365 * n)  # simple year
    raise ValueError(f"Unsupported lookback unit: {unit}")

def to_ms(ts: dt.datetime) -> int:
    return int(ts.timestamp() * 1000)

def from_ms(ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc)

def timeframe_to_ms(tf: str) -> int:
    if tf.endswith("m"):
        return int(tf[:-1]) * 60_000
    if tf.endswith("h"):
        return int(tf[:-1]) * 60 * 60_000
    if tf.endswith("d"):
        return int(tf[:-1]) * 24 * 60 * 60_000
    raise ValueError(f"Unsupported timeframe: {tf}")

def fetch_hl_candles(symbol: str, interval: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    rows_all: List[Dict[str, Any]] = []
    step_ms = timeframe_to_ms(interval)

    cur_start = start_ms
    while cur_start < end_ms:
        # Wait if needed to respect rate limits
        rate_limiter.wait_if_needed(request_weight=20)
        
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": cur_start,
                "endTime": end_ms,
            },
        }
        
        try:
            r = requests.post(HL_INFO_URL, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()

            bars = data if isinstance(data, list) else data.get("data") or data.get("candles")
            if not bars:
                # Record the request even if no data returned
                rate_limiter.record_request(weight=20, items_returned=0)
                break

            normalized = []
            for b in bars:
                # HL example keys: T (end), t (start), o,h,l,c,v, i (interval), s (symbol)
                t = int(b.get("t", b.get("time")))  # start of bar (ms)
                o = b.get("o", b.get("open"))
                h = b.get("h", b.get("high"))
                l = b.get("l", b.get("low"))
                c = b.get("c", b.get("close"))
                v = b.get("v", b.get("volume"))
                if t is None or o is None or h is None or l is None or c is None:
                    continue
                normalized.append({
                    "symbol": symbol,
                    "time": from_ms(t).isoformat(),
                    "t": t,
                    "open": float(o),
                    "high": float(h),
                    "low": float(l),
                    "close": float(c),
                    "volume": float(v) if v is not None else None,
                    "interval": interval,
                })

            # Record the request with actual items returned
            rate_limiter.record_request(weight=20, items_returned=len(bars))
            rows_all.extend(normalized)

            # Stop if we didn't get any new progress (avoid infinite loop on edge cases)
            last_t = normalized[-1]["t"] if normalized else cur_start
            next_start = last_t + step_ms
            if next_start <= cur_start:
                break
            cur_start = next_start

        except requests.exceptions.RequestException as e:
            print(f"Request failed for {symbol}: {e}")
            # Still record the request attempt for rate limiting
            rate_limiter.record_request(weight=20, items_returned=0)
            # Wait a bit longer on error
            time.sleep(1.0)
            break
        except Exception as e:
            print(f"Unexpected error for {symbol}: {e}")
            rate_limiter.record_request(weight=20, items_returned=0)
            break

    return rows_all


def write_csv(path: str, rows: List[Dict[str, Any]]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not rows:
        # create empty with header
        header = ["symbol","time","t","open","high","low","close","volume","interval"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)
        return
    header = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)

def main():
    args = parse_args()

    # Update rate limiter verbosity based on command line argument
    rate_limiter.verbose = args.verbose_rate_limit

    tf = args.timeframe
    if tf not in VALID_INTERVALS:
        print(f"[!] Invalid timeframe {tf}. Valid: {sorted(VALID_INTERVALS)}", file=sys.stderr)
        sys.exit(2)

    end_dt = parse_iso_guess(args.end) if args.end else dt.datetime.now(dt.timezone.utc)
    if args.start:
        start_dt = parse_iso_guess(args.start)
    else:
        if not args.lookback:
            print("[!] Provide either --lookback (e.g., 90d) or --start YYYY-MM-DD", file=sys.stderr)
            sys.exit(2)
        start_dt = end_dt - parse_lookback(args.lookback)

    start_ms = to_ms(start_dt)
    end_ms = to_ms(end_dt)

    tickers = read_tickers(args)
    print(f"Tickers ({len(tickers)}): {', '.join(tickers[:8])}{'...' if len(tickers)>8 else ''}")
    print(f"Timeframe: {tf} | From: {start_dt.isoformat()}  To: {end_dt.isoformat()}")
    print(f"Rate limiting: Max 960 weight/minute (80% of 1200 limit), candleSnapshot weight: 20 + items/60")
    print(f"Sleep between tickers: {args.sleep}s")

    all_rows: List[Dict[str, Any]] = []
    failures: List[str] = []

    for i, sym in enumerate(tickers, 1):
        try:
            print(f"\n[{i}/{len(tickers)}] Fetching {sym}...")
            rows = fetch_hl_candles(sym, tf, start_ms, end_ms)
            out_path = os.path.join(args.outdir, f"candles_{sym}_{tf}.csv")
            write_csv(out_path, rows)
            print(f"[{i}/{len(tickers)}] {sym}: {len(rows)} bars -> {out_path}")
            all_rows.extend(rows)
            
            # Sleep between tickers to be extra polite to the API
            if i < len(tickers):  # Don't sleep after the last ticker
                time.sleep(args.sleep)
                
        except Exception as e:
            print(f"[{i}/{len(tickers)}] {sym}: ERROR -> {e}", file=sys.stderr)
            failures.append(sym)

    if all_rows:
        combined = os.path.join(args.outdir, f"all_candles_{tf}.csv")
        # Sort combined by time then symbol for readability
        all_rows.sort(key=lambda r: (r["t"], r["symbol"]))
        write_csv(combined, all_rows)
        print(f"\nCombined CSV -> {combined}  (rows: {len(all_rows)})")

    if failures:
        print(f"\n[!] Failed tickers ({len(failures)}): {', '.join(failures)}", file=sys.stderr)

if __name__ == "__main__":
    main()
