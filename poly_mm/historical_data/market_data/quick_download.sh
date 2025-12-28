#!/bin/bash
#
# Quick Start Script for Downloading Historical Market Data
# Downloads 30 days of BTC 15-minute markets from Polymarket
#
# Usage:
#   ./quick_download.sh
#

set -e  # Exit on error

echo "================================================================================"
echo "POLYMARKET HISTORICAL DATA DOWNLOAD - QUICK START"
echo "================================================================================"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 not found"
    echo "   Please install Python 3.8+ to continue"
    exit 1
fi

echo "✅ Python3 found: $(python3 --version)"
echo ""

# Check for required packages
echo "Checking Python dependencies..."
python3 -c "import requests" 2>/dev/null || {
    echo "❌ Error: 'requests' package not found"
    echo "   Install with: pip install requests"
    exit 1
}
echo "✅ All dependencies available"
echo ""

# Default parameters
DAYS=30
ASSET="BTC"
RATE_LIMIT=0.2

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --days)
            DAYS="$2"
            shift 2
            ;;
        --asset)
            ASSET="$2"
            shift 2
            ;;
        --rate-limit)
            RATE_LIMIT="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --days N          Number of days to download (default: 30)"
            echo "  --asset ASSET     Asset to download: BTC, ETH, SOL, XRP (default: BTC)"
            echo "  --rate-limit N    Seconds between requests (default: 0.2)"
            echo "  --help            Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                      # Download 30 days of BTC"
            echo "  $0 --days 7             # Download 7 days of BTC"
            echo "  $0 --asset ETH          # Download 30 days of ETH"
            echo "  $0 --days 14 --asset SOL  # Download 14 days of SOL"
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $1"
            echo "   Use --help for usage information"
            exit 1
            ;;
    esac
done

# Display configuration
echo "Download Configuration:"
echo "  Asset:       $ASSET"
echo "  Days:        $DAYS"
echo "  Rate Limit:  ${RATE_LIMIT}s"
echo ""

# Confirm with user
read -p "Start download? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Download cancelled."
    exit 0
fi

# Run download
echo ""
echo "Starting download..."
echo "--------------------------------------------------------------------------------"

python3 download_historical_markets.py \
    --days "$DAYS" \
    --asset "$ASSET" \
    --rate-limit "$RATE_LIMIT"

EXIT_CODE=$?

echo "--------------------------------------------------------------------------------"
echo ""

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Download completed successfully!"
    echo ""
    
    # Find output file
    OUTPUT_FILE="historical_${ASSET,,}_${DAYS}d.json"
    
    if [ -f "$OUTPUT_FILE" ]; then
        FILE_SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
        echo "Output file: $OUTPUT_FILE ($FILE_SIZE)"
        echo ""
        
        # Offer to run analysis
        read -p "Run analysis on downloaded data? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo ""
            python3 analyze_historical_data.py "$OUTPUT_FILE"
        fi
    fi
else
    echo "❌ Download failed with exit code $EXIT_CODE"
    exit $EXIT_CODE
fi

echo ""
echo "Next steps:"
echo "  1. Review the data: cat $OUTPUT_FILE | jq '.markets[0]'"
echo "  2. Run analysis:    python3 analyze_historical_data.py $OUTPUT_FILE"
echo "  3. Use in backtest: import json; data = json.load(open('$OUTPUT_FILE'))"
echo ""
echo "For more options, see README.md"
echo ""
