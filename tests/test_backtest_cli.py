"""
Unit tests for Step 6: Advanced Backtest CLI

Tests parameter parsing, overlay logic, result saving, and CLI argument handling.
"""
import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from run_backtest import parse_params, overlay_params, save_results
from app.config.models import BotConfig, StrategyConfig, ExchangeConfig, RiskConfig
from pydantic import SecretStr


@pytest.fixture
def sample_config():
    """Create a sample BotConfig for testing."""
    return BotConfig(
        exchange=ExchangeConfig(
            name="binance",
            api_key=SecretStr("test-key"),
            api_secret=SecretStr("test-secret"),
            sandbox_mode=True,
        ),
        risk=RiskConfig(
            max_position_size_usd=1000,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
        ),
        strategy=StrategyConfig(
            name="sma_cross",
            symbol="BTC/USDT",
            timeframe="1h",
            params={
                "fast_window": 10,
                "slow_window": 50,
            }
        ),
        db_path="test.db",
    )


def test_parse_params_json_format():
    """Test parsing parameters in JSON format."""
    params_str = '{"fast_window": 20, "slow_window": 60}'
    result = parse_params(params_str)
    
    assert result == {"fast_window": 20, "slow_window": 60}
    assert isinstance(result["fast_window"], int)
    assert isinstance(result["slow_window"], int)


def test_parse_params_json_with_floats():
    """Test parsing JSON parameters with float values."""
    params_str = '{"threshold": 0.05, "window": 100}'
    result = parse_params(params_str)
    
    assert result == {"threshold": 0.05, "window": 100}
    assert isinstance(result["threshold"], float)
    assert isinstance(result["window"], int)


def test_parse_params_keyvalue_comma_separated():
    """Test parsing parameters in key=value format with commas."""
    params_str = 'fast_window=20,slow_window=60'
    result = parse_params(params_str)
    
    assert result == {"fast_window": 20, "slow_window": 60}
    assert isinstance(result["fast_window"], int)
    assert isinstance(result["slow_window"], int)


def test_parse_params_keyvalue_space_separated():
    """Test parsing parameters in key=value format with spaces."""
    params_str = 'fast_window=20 slow_window=60'
    result = parse_params(params_str)
    
    assert result == {"fast_window": 20, "slow_window": 60}


def test_parse_params_keyvalue_mixed():
    """Test parsing parameters with mixed separators."""
    params_str = 'fast_window=20,slow_window=60 threshold=0.5'
    result = parse_params(params_str)
    
    assert result == {"fast_window": 20, "slow_window": 60, "threshold": 0.5}
    assert isinstance(result["fast_window"], int)
    assert isinstance(result["threshold"], float)


def test_parse_params_keyvalue_with_strings():
    """Test parsing parameters with string values."""
    params_str = 'mode=aggressive,window=100'
    result = parse_params(params_str)
    
    assert result == {"mode": "aggressive", "window": 100}
    assert isinstance(result["mode"], str)
    assert isinstance(result["window"], int)


def test_parse_params_invalid_json():
    """Test that invalid JSON raises appropriate error."""
    params_str = '{"fast_window": 20, "slow_window": }'  # Invalid JSON
    
    with pytest.raises(ValueError, match="Invalid JSON format"):
        parse_params(params_str)


def test_parse_params_invalid_keyvalue():
    """Test that invalid key=value format raises error."""
    params_str = 'fast_window 20'  # Missing '='
    
    with pytest.raises(ValueError, match="Invalid parameter format"):
        parse_params(params_str)


def test_parse_params_empty_string():
    """Test parsing empty or whitespace-only strings."""
    # Empty string should return empty dict
    result = parse_params('   ')
    assert result == {}


def test_overlay_params_basic(sample_config):
    """Test basic parameter overlay."""
    overrides = {"fast_window": 20, "slow_window": 60}
    
    new_config = overlay_params(sample_config, overrides)
    
    # Check that parameters were updated
    assert new_config.strategy.params["fast_window"] == 20
    assert new_config.strategy.params["slow_window"] == 60
    
    # Check that original config was not modified
    assert sample_config.strategy.params["fast_window"] == 10
    assert sample_config.strategy.params["slow_window"] == 50
    
    # Check that other config values were preserved
    assert new_config.strategy.name == sample_config.strategy.name
    assert new_config.strategy.symbol == sample_config.strategy.symbol
    assert new_config.exchange.name == sample_config.exchange.name


def test_overlay_params_partial(sample_config):
    """Test partial parameter overlay (only some params changed)."""
    overrides = {"fast_window": 15}  # Only override one parameter
    
    new_config = overlay_params(sample_config, overrides)
    
    assert new_config.strategy.params["fast_window"] == 15
    assert new_config.strategy.params["slow_window"] == 50  # Unchanged


def test_overlay_params_new_param(sample_config):
    """Test adding a new parameter that wasn't in original config."""
    overrides = {"new_param": 100}
    
    new_config = overlay_params(sample_config, overrides)
    
    assert new_config.strategy.params["new_param"] == 100
    assert new_config.strategy.params["fast_window"] == 10  # Unchanged


def test_overlay_params_empty(sample_config):
    """Test that empty overrides returns original config."""
    new_config = overlay_params(sample_config, {})
    
    assert new_config.strategy.params == sample_config.strategy.params


def test_overlay_params_none(sample_config):
    """Test that None overrides returns original config."""
    new_config = overlay_params(sample_config, None)
    
    assert new_config is sample_config  # Should return same object


def test_save_results_structure(sample_config):
    """Test that save_results creates correctly structured JSON."""
    import pandas as pd
    
    # Create mock results
    df = pd.DataFrame({
        'close': [100, 101, 102, 103, 104],
        'equity_curve': [1.0, 1.01, 1.02, 0.99, 1.03],
        'signal': [1, 1, 0, -1, 0],
    })
    
    results = {
        "data": df,
        "total_return": 0.03,
        "sharpe_ratio": 1.5,
        "max_drawdown": -0.03,
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        results_dir = Path(tmpdir)
        
        saved_path = save_results(
            results=results,
            config=sample_config,
            start_date="2024-01-01",
            end_date="2024-06-01",
            results_dir=results_dir,
        )
        
        # Check file was created
        assert saved_path.exists()
        assert saved_path.name.startswith("backtest_sma_cross_")
        assert saved_path.suffix == ".json"
        
        # Check file contents
        with saved_path.open() as f:
            data = json.load(f)
        
        # Check structure
        assert "metadata" in data
        assert "metrics" in data
        assert "params" in data
        assert "config" in data
        assert "equity_curve" in data
        
        # Check metadata
        assert data["metadata"]["start_date"] == "2024-01-01"
        assert data["metadata"]["end_date"] == "2024-06-01"
        assert "timestamp" in data["metadata"]
        
        # Check metrics
        assert data["metrics"]["total_return"] == 0.03
        assert data["metrics"]["sharpe_ratio"] == 1.5
        assert data["metrics"]["max_drawdown"] == -0.03
        
        # Check params
        assert data["params"]["fast_window"] == 10
        assert data["params"]["slow_window"] == 50
        
        # Check equity curve
        assert isinstance(data["equity_curve"], list)
        assert len(data["equity_curve"]) == 5
        assert data["equity_curve"] == [1.0, 1.01, 1.02, 0.99, 1.03]
        
        # Check config
        assert data["config"]["strategy"]["name"] == "sma_cross"
        assert data["config"]["strategy"]["symbol"] == "BTC/USDT"


def test_save_results_creates_directory(sample_config):
    """Test that save_results creates results directory if it doesn't exist."""
    import pandas as pd
    
    df = pd.DataFrame({
        'close': [100],
        'equity_curve': [1.0],
        'signal': [0],
    })
    
    results = {
        "data": df,
        "total_return": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        results_dir = Path(tmpdir) / "new_results_dir"
        
        # Directory should not exist yet
        assert not results_dir.exists()
        
        saved_path = save_results(
            results=results,
            config=sample_config,
            start_date="2024-01-01",
            end_date="2024-06-01",
            results_dir=results_dir,
        )
        
        # Directory should now exist
        assert results_dir.exists()
        assert saved_path.exists()


def test_save_results_unique_filenames(sample_config):
    """Test that multiple saves create unique filenames."""
    import pandas as pd
    import time
    
    df = pd.DataFrame({
        'close': [100],
        'equity_curve': [1.0],
        'signal': [0],
    })
    
    results = {
        "data": df,
        "total_return": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        results_dir = Path(tmpdir)
        
        # Save first result
        path1 = save_results(
            results=results,
            config=sample_config,
            start_date="2024-01-01",
            end_date="2024-06-01",
            results_dir=results_dir,
        )
        
        # Small delay to ensure different timestamp
        time.sleep(1)
        
        # Save second result
        path2 = save_results(
            results=results,
            config=sample_config,
            start_date="2024-01-01",
            end_date="2024-06-01",
            results_dir=results_dir,
        )
        
        # Filenames should be different
        assert path1 != path2
        assert path1.exists()
        assert path2.exists()


def test_integration_parse_and_overlay():
    """Integration test: parse params from string and overlay on config."""
    config = BotConfig(
        exchange=ExchangeConfig(
            name="binance",
            api_key=SecretStr("key"),
            api_secret=SecretStr("secret"),
            sandbox_mode=True,
        ),
        risk=RiskConfig(
            max_position_size_usd=1000,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
        ),
        strategy=StrategyConfig(
            name="sma_cross",
            symbol="BTC/USDT",
            timeframe="1h",
            params={"fast_window": 10, "slow_window": 50}
        ),
        db_path="test.db",
    )
    
    # Parse from JSON string
    params_str = '{"fast_window": 25, "slow_window": 75}'
    parsed = parse_params(params_str)
    
    # Overlay on config
    new_config = overlay_params(config, parsed)
    
    # Verify
    assert new_config.strategy.params["fast_window"] == 25
    assert new_config.strategy.params["slow_window"] == 75
    
    # Parse from key=value string
    params_str2 = 'fast_window=30,slow_window=80'
    parsed2 = parse_params(params_str2)
    
    # Overlay on config
    new_config2 = overlay_params(config, parsed2)
    
    # Verify
    assert new_config2.strategy.params["fast_window"] == 30
    assert new_config2.strategy.params["slow_window"] == 80

