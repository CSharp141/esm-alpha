#!/usr/bin/env python3
"""
Market Price History Visualizer

Interactive tool to visualize YES and NO token price histories for 
Polymarket 15-minute binary options markets.

Features:
- Browse and select markets from downloaded data
- Plot YES and NO prices on the same graph
- Show market outcomes and key events
- Export plots as images

Usage:
    python plot_market_prices.py data_file.json
    python plot_market_prices.py data_file.json --market-index 42
    python plot_market_prices.py data_file.json --save-dir ./plots
"""

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter


def load_market_data(file_path: str) -> Dict[str, Any]:
    """Load market data from JSON file."""
    with open(file_path, 'r') as f:
        return json.load(f)


def format_market_info(market: Dict[str, Any], index: int) -> str:
    """Format market information for display."""
    start_dt = datetime.fromtimestamp(market['start_time'], tz=timezone.utc)
    expiry_dt = datetime.fromtimestamp(market['expiry_time'], tz=timezone.utc)
    
    info = f"[{index}] {market['question']}\n"
    info += f"    Start:  {start_dt.strftime('%Y-%m-%d %H:%M UTC')}\n"
    info += f"    Expiry: {expiry_dt.strftime('%Y-%m-%d %H:%M UTC')}\n"
    info += f"    Status: {market['status']}"
    
    if market.get('winning_outcome'):
        info += f" | Winner: {market['winning_outcome']}"
    
    yes_hist = market.get('yes_price_history', [])
    no_hist = market.get('no_price_history', [])
    info += f" | Data: {len(yes_hist)} YES, {len(no_hist)} NO points"
    
    return info


def list_markets(markets: List[Dict[str, Any]], page: int = 0, page_size: int = 20) -> None:
    """Display a paginated list of markets."""
    total = len(markets)
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, total)
    
    print(f"\n{'='*80}")
    print(f"AVAILABLE MARKETS (Page {page + 1} of {(total + page_size - 1) // page_size})")
    print(f"{'='*80}\n")
    
    for i in range(start_idx, end_idx):
        print(format_market_info(markets[i], i))
        print()
    
    print(f"Showing {start_idx + 1}-{end_idx} of {total} markets")


def select_market_interactive(markets: List[Dict[str, Any]]) -> int:
    """Interactive market selection."""
    page = 0
    page_size = 20
    
    while True:
        list_markets(markets, page, page_size)
        
        print(f"\n{'='*80}")
        print("Commands: [n]ext page, [p]revious page, [number] select market, [q]uit")
        print(f"{'='*80}")
        
        choice = input("\nYour choice: ").strip().lower()
        
        if choice == 'q':
            return -1
        elif choice == 'n':
            if (page + 1) * page_size < len(markets):
                page += 1
            else:
                print("Already on last page")
        elif choice == 'p':
            if page > 0:
                page -= 1
            else:
                print("Already on first page")
        elif choice.isdigit():
            idx = int(choice)
            if 0 <= idx < len(markets):
                return idx
            else:
                print(f"Invalid market index. Must be 0-{len(markets) - 1}")
        else:
            print("Invalid command")


def plot_market_prices(
    market: Dict[str, Any],
    save_path: Optional[str] = None,
    show: bool = True
) -> None:
    """
    Plot YES and NO token price histories for a market.
    
    Args:
        market: Market data dict with price histories
        save_path: Optional path to save the plot
        show: Whether to display the plot interactively
    """
    yes_history = market.get('yes_price_history', [])
    no_history = market.get('no_price_history', [])
    
    if not yes_history and not no_history:
        print("❌ No price history available for this market")
        return
    
    # Extract timestamps and prices
    yes_times = [datetime.fromtimestamp(p['t'], tz=timezone.utc) for p in yes_history]
    yes_prices = [p['p'] for p in yes_history]
    
    no_times = [datetime.fromtimestamp(p['t'], tz=timezone.utc) for p in no_history]
    no_prices = [p['p'] for p in no_history]
    
    # Create figure
    fig, ax = plt.subplots(figsize=(14, 8))
    
    # Plot price lines
    if yes_times and yes_prices:
        ax.plot(yes_times, yes_prices, label='YES Token', 
                color='#2ecc71', linewidth=2, alpha=0.8)
    
    if no_times and no_prices:
        ax.plot(no_times, no_prices, label='NO Token',
                color='#e74c3c', linewidth=2, alpha=0.8)
    
    # Add market start and expiry lines
    start_time = datetime.fromtimestamp(market['start_time'], tz=timezone.utc)
    expiry_time = datetime.fromtimestamp(market['expiry_time'], tz=timezone.utc)
    
    ax.axvline(start_time, color='blue', linestyle='--', linewidth=1.5, 
               alpha=0.6, label='Market Start')
    ax.axvline(expiry_time, color='purple', linestyle='--', linewidth=1.5,
               alpha=0.6, label='Market Expiry')
    
    # Add 50% reference line
    ax.axhline(0.5, color='gray', linestyle=':', linewidth=1, alpha=0.4)
    
    # Formatting
    ax.set_xlabel('Time (UTC)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Probability', fontsize=12, fontweight='bold')
    ax.set_ylim(0, 1)
    
    # Format y-axis as percentages
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f'{y*100:.0f}%'))
    
    # Format x-axis dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    fig.autofmt_xdate(rotation=45)
    
    # Add grid
    ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
    
    # Title with market info
    title = market['question']
    if len(title) > 80:
        title = title[:77] + "..."
    
    outcome_text = ""
    if market.get('winning_outcome'):
        outcome_text = f" | Winner: {market['winning_outcome']}"
    
    ax.set_title(f"{title}\n{market['status'].upper()}{outcome_text}",
                 fontsize=13, fontweight='bold', pad=20)
    
    # Add legend
    ax.legend(loc='best', fontsize=10, framealpha=0.9)
    
    # Tight layout
    plt.tight_layout()
    
    # Save if requested
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"✅ Plot saved to: {save_path}")
    
    # Show if requested
    if show:
        plt.show()
    else:
        plt.close()


def generate_filename(market: Dict[str, Any], output_dir: str) -> str:
    """Generate a safe filename for the plot."""
    slug = market.get('slug', 'market')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    filename = f"{slug}_{timestamp}.png"
    return str(Path(output_dir) / filename)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Visualize Polymarket 15-minute market price histories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode - browse and select markets
  python plot_market_prices.py historical_btc_30d.json
  
  # Plot specific market by index
  python plot_market_prices.py historical_btc_30d.json --market-index 42
  
  # Save plots to directory without showing
  python plot_market_prices.py historical_btc_30d.json --save-dir ./plots --no-show
  
  # Plot all markets (batch mode)
  python plot_market_prices.py historical_btc_30d.json --all --save-dir ./plots --no-show
        """
    )
    
    parser.add_argument(
        "data_file",
        help="Path to JSON file with market data"
    )
    
    parser.add_argument(
        "--market-index",
        type=int,
        default=None,
        help="Index of market to plot (0-based)"
    )
    
    parser.add_argument(
        "--save-dir",
        type=str,
        default=None,
        help="Directory to save plot images"
    )
    
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Don't display plots interactively (useful for batch processing)"
    )
    
    parser.add_argument(
        "--all",
        action="store_true",
        help="Plot all markets in batch mode"
    )
    
    parser.add_argument(
        "--filter-resolved",
        action="store_true",
        help="Only show resolved markets"
    )
    
    args = parser.parse_args()
    
    # Load data
    print(f"📂 Loading market data from: {args.data_file}")
    try:
        data = load_market_data(args.data_file)
    except FileNotFoundError:
        print(f"❌ Error: File not found: {args.data_file}")
        return
    except json.JSONDecodeError:
        print(f"❌ Error: Invalid JSON file: {args.data_file}")
        return
    
    markets = data.get('markets', [])
    
    if not markets:
        print("❌ No markets found in data file")
        return
    
    print(f"✅ Loaded {len(markets)} markets")
    
    # Filter if requested
    if args.filter_resolved:
        markets = [m for m in markets if m.get('status') == 'resolved']
        print(f"🔍 Filtered to {len(markets)} resolved markets")
    
    # Create save directory if needed
    if args.save_dir:
        Path(args.save_dir).mkdir(parents=True, exist_ok=True)
        print(f"📁 Plots will be saved to: {args.save_dir}")
    
    # Determine which markets to plot
    if args.all:
        # Batch mode - plot all markets
        print(f"\n🎨 Plotting {len(markets)} markets...")
        
        for i, market in enumerate(markets):
            print(f"\n[{i+1}/{len(markets)}] {market['question'][:60]}...")
            
            if args.save_dir:
                save_path = generate_filename(market, args.save_dir)
            else:
                save_path = None
            
            try:
                plot_market_prices(market, save_path=save_path, show=not args.no_show)
            except Exception as e:
                print(f"⚠️  Error plotting market {i}: {e}")
        
        print(f"\n✅ Completed plotting {len(markets)} markets")
        
    elif args.market_index is not None:
        # Direct index mode
        idx = args.market_index
        
        if idx < 0 or idx >= len(markets):
            print(f"❌ Invalid market index: {idx}. Must be 0-{len(markets) - 1}")
            return
        
        market = markets[idx]
        print(f"\n🎨 Plotting market {idx}:")
        print(format_market_info(market, idx))
        
        if args.save_dir:
            save_path = generate_filename(market, args.save_dir)
        else:
            save_path = None
        
        plot_market_prices(market, save_path=save_path, show=not args.no_show)
        
    else:
        # Interactive mode
        while True:
            idx = select_market_interactive(markets)
            
            if idx == -1:
                print("\n👋 Goodbye!")
                break
            
            market = markets[idx]
            print(f"\n🎨 Plotting market {idx}:")
            print(format_market_info(market, idx))
            
            if args.save_dir:
                save_path = generate_filename(market, args.save_dir)
            else:
                save_path = None
            
            try:
                plot_market_prices(market, save_path=save_path, show=not args.no_show)
            except Exception as e:
                print(f"⚠️  Error: {e}")
            
            # Ask if user wants to continue
            if not args.all and not args.no_show:
                cont = input("\nPlot another market? [y/n]: ").strip().lower()
                if cont != 'y':
                    print("\n👋 Goodbye!")
                    break


if __name__ == "__main__":
    main()
