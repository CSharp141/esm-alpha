"""
Configuration management for Polymarket HFT Market Maker.

Loads environment variables from .env file and provides
validated configuration objects for the application.
"""

import os
from typing import Optional, List
from dataclasses import dataclass
from dotenv import load_dotenv


# Load .env file from src directory
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))


@dataclass
class PolymarketConfig:
    """Polymarket API configuration."""
    private_key: str
    signature_type: Optional[int] = None
    funder_address: Optional[str] = None
    chain_id: int = 137
    clob_host: str = "https://clob.polymarket.com"
    data_api: str = "https://data-api.polymarket.com"
    
    @classmethod
    def from_env(cls) -> "PolymarketConfig":
        """Load from environment variables."""
        private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
        if not private_key or private_key == "your_polygon_private_key_here":
            raise ValueError(
                "POLYMARKET_PRIVATE_KEY not set in .env file. "
                "Please add your Polygon private key."
            )
        
        sig_type_str = os.getenv("POLYMARKET_SIGNATURE_TYPE", "")
        signature_type = None
        if sig_type_str and sig_type_str.strip():
            signature_type = int(sig_type_str)
        
        funder = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")
        funder_address = funder if funder and funder.strip() else None
        
        return cls(
            private_key=private_key,
            signature_type=signature_type,
            funder_address=funder_address,
            chain_id=int(os.getenv("POLYMARKET_CHAIN_ID", "137")),
            clob_host=os.getenv("POLYMARKET_CLOB_HOST", "https://clob.polymarket.com"),
            data_api=os.getenv("POLYMARKET_DATA_API", "https://data-api.polymarket.com")
        )


@dataclass
class PricingConfig:
    """Pricing engine configuration."""
    lambda_param: float = 0.94
    base_spread: float = 0.02
    max_inventory: float = 100.0
    inventory_skew_factor: float = 0.001
    risk_free_rate: float = 0.05
    
    @classmethod
    def from_env(cls) -> "PricingConfig":
        """Load from environment variables."""
        return cls(
            lambda_param=float(os.getenv("LAMBDA_PARAM", "0.94")),
            base_spread=float(os.getenv("BASE_SPREAD", "0.02")),
            max_inventory=float(os.getenv("MAX_INVENTORY", "100.0")),
            inventory_skew_factor=float(os.getenv("INVENTORY_SKEW_FACTOR", "0.001")),
            risk_free_rate=float(os.getenv("RISK_FREE_RATE", "0.05"))
        )


@dataclass
class TradingConfig:
    """Trading strategy configuration."""
    edge_threshold: float = 0.02
    sizing_factor: float = 20.0
    max_position_size: float = 100.0
    trading_symbols: List[str] = None
    min_time_to_expiry: float = 2.0
    max_time_to_expiry: float = 20.0
    min_liquidity: float = 1000.0
    
    def __post_init__(self):
        if self.trading_symbols is None:
            self.trading_symbols = ["BTC"]
    
    @classmethod
    def from_env(cls) -> "TradingConfig":
        """Load from environment variables."""
        symbols_str = os.getenv("TRADING_SYMBOLS", "BTC")
        symbols = [s.strip() for s in symbols_str.split(",")]
        
        return cls(
            edge_threshold=float(os.getenv("EDGE_THRESHOLD", "0.02")),
            sizing_factor=float(os.getenv("SIZING_FACTOR", "20.0")),
            max_position_size=float(os.getenv("MAX_POSITION_SIZE", "100.0")),
            trading_symbols=symbols,
            min_time_to_expiry=float(os.getenv("MIN_TIME_TO_EXPIRY", "2.0")),
            max_time_to_expiry=float(os.getenv("MAX_TIME_TO_EXPIRY", "20.0")),
            min_liquidity=float(os.getenv("MIN_LIQUIDITY", "1000.0"))
        )


@dataclass
class SystemConfig:
    """System-level configuration."""
    quote_update_interval: float = 5.0
    ticks_per_update: int = 10
    max_total_exposure: float = 500.0
    max_drawdown: float = 0.10
    kill_switch: bool = False
    dry_run: bool = True  # Default to dry run for safety
    log_level: str = "INFO"
    enable_metrics: bool = True
    metrics_interval: int = 60
    rtds_ws_url: str = "wss://ws-live-data.polymarket.com"
    
    @classmethod
    def from_env(cls) -> "SystemConfig":
        """Load from environment variables."""
        kill_switch_str = os.getenv("KILL_SWITCH", "false").lower()
        kill_switch = kill_switch_str in ("true", "1", "yes")
        
        dry_run_str = os.getenv("DRY_RUN", "true").lower()
        dry_run = dry_run_str in ("true", "1", "yes")
        
        enable_metrics_str = os.getenv("ENABLE_METRICS", "true").lower()
        enable_metrics = enable_metrics_str in ("true", "1", "yes")
        
        return cls(
            quote_update_interval=float(os.getenv("QUOTE_UPDATE_INTERVAL", "5.0")),
            ticks_per_update=int(os.getenv("TICKS_PER_UPDATE", "10")),
            max_total_exposure=float(os.getenv("MAX_TOTAL_EXPOSURE", "500.0")),
            max_drawdown=float(os.getenv("MAX_DRAWDOWN", "0.10")),
            kill_switch=kill_switch,
            dry_run=dry_run,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            enable_metrics=enable_metrics,
            metrics_interval=int(os.getenv("METRICS_INTERVAL", "60")),
            rtds_ws_url=os.getenv("RTDS_WS_URL", "wss://ws-live-data.polymarket.com")
        )


@dataclass
class Config:
    """Complete application configuration."""
    polymarket: PolymarketConfig
    pricing: PricingConfig
    trading: TradingConfig
    system: SystemConfig
    
    @classmethod
    def load(cls) -> "Config":
        """
        Load complete configuration from environment.
        
        Raises:
            ValueError: If required configuration is missing
        """
        return cls(
            polymarket=PolymarketConfig.from_env(),
            pricing=PricingConfig.from_env(),
            trading=TradingConfig.from_env(),
            system=SystemConfig.from_env()
        )
    
    def validate(self):
        """
        Validate configuration values.
        
        Raises:
            ValueError: If configuration is invalid
        """
        # Validate pricing parameters
        if not 0.5 <= self.pricing.lambda_param <= 0.99:
            raise ValueError("LAMBDA_PARAM must be between 0.5 and 0.99")
        
        if not 0.001 <= self.pricing.base_spread <= 0.2:
            raise ValueError("BASE_SPREAD must be between 0.001 and 0.2")
        
        if self.pricing.max_inventory <= 0:
            raise ValueError("MAX_INVENTORY must be positive")
        
        # Validate trading parameters
        if not 0.0 <= self.trading.edge_threshold <= 0.5:
            raise ValueError("EDGE_THRESHOLD must be between 0 and 0.5")
        
        if self.trading.sizing_factor <= 0:
            raise ValueError("SIZING_FACTOR must be positive")
        
        if self.trading.max_position_size <= 0:
            raise ValueError("MAX_POSITION_SIZE must be positive")
        
        # Validate system parameters
        if self.system.quote_update_interval <= 0:
            raise ValueError("QUOTE_UPDATE_INTERVAL must be positive")
        
        if self.system.ticks_per_update <= 0:
            raise ValueError("TICKS_PER_UPDATE must be positive")
        
        if not 0.0 < self.system.max_drawdown <= 1.0:
            raise ValueError("MAX_DRAWDOWN must be between 0 and 1")
        
        print("✓ Configuration validated successfully")


# Global config instance (load once)
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global configuration instance.
    
    Loads and validates on first call, then returns cached instance.
    """
    global _config
    if _config is None:
        _config = Config.load()
        _config.validate()
    return _config


if __name__ == "__main__":
    # Test configuration loading
    try:
        config = get_config()
        print("Configuration loaded successfully!")
        print(f"Trading symbols: {config.trading.trading_symbols}")
        print(f"Lambda param: {config.pricing.lambda_param}")
        print(f"Edge threshold: {config.trading.edge_threshold}")
        print(f"Chain ID: {config.polymarket.chain_id}")
    except ValueError as e:
        print(f"Configuration error: {e}")
