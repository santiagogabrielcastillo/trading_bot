# Project Blueprint: Scalable Python Trading Bot (BTC)

**Role:** Senior Quantitative Architect & Python Developer.
**Project Goal:** Build a modular, scalable, and easy-to-deploy trading bot for Bitcoin.
**Core Philosophy:** "Start small, scale fast." The architecture must support rapid iteration of strategies without rewriting the core engine.

## 1. Architectural Context & Principles
We are building a professional-grade algorithmic trading system, NOT a simple script.
* **Separation of Concerns:** The `Strategy` logic must never know about the `Exchange`. It only outputs signals. The `Executor` handles the API.
* **Vectorization First:** Backtesting must be instant. We strictly **FORBID** iterating over DataFrames row-by-row (`for` loops) during signal generation or backtesting calculations. We use `pandas` and `numpy` vector operations.
* **Type Safety:** We use Python type hints and `Pydantic` for strict configuration validation.
* **Interface-Driven:** All core components (`DataHandler`, `Strategy`, `Executor`) are defined by abstract base classes (Interfaces).

### ✅ Definition of Done (DoD)
A step or feature is **ONLY** considered complete when:
1.  **Code is Implemented:** The functionality works as requested.
2.  **Tests are Passed:** A corresponding unit test (using `pytest`) exists and passes.
3.  **No Magic Numbers:** All parameters are extracted to config or constants.
4.  **Reproducible:** If it involves data, it must work in "Offline Mode" without relying on a live API connection.

## 2. Current Project State
We are in **Phase 2 (Simulation Engine)**.
* **Core:** Interfaces, Models, and basic Handler are in place.
* **Strategy:** Vectorized `SmaCrossStrategy` is implemented.
* **Backtester:** Basic `engine.py` exists but contains **CRITICAL BUGS** (Math & Logic) that must be fixed immediately.

---

## 🚨 MANDATORY PROTOCOL: AUTO-LOGGING 🚨
**CRITICAL INSTRUCTION:**
After you successfully complete ANY step or task defined below, you **MUST** automatically update the file `DEVLOG.md` located in the root directory.
**Do not ask for permission.** Treat the log update as part of the code generation process.

---

## 3. Execution Roadmap

### 🛑 IMMEDIATE PRIORITY: CRITICAL HOTFIXES (Current Task) 🛑
*Before moving forward, we must fix the technical debt identified in the audit.*

**Task 1: Fix Sharpe Ratio Logic (Math Error)**
* **File:** `app/backtesting/engine.py`
* **Issue:** `periods_per_year` is hardcoded to 252 (Traditional Finance). Crypto is 24/7.
* **Fix:** Calculate annualization factor dynamically based on `self.timeframe`.
    * If timeframe is '1h', factor = $365 \times 24 = 8760$.
    * If timeframe is '1d', factor = $365$.
    * Throw error if timeframe is unknown.

**Task 2: Fix Data Pagination (Scalability Error)**
* **File:** `app/data/handler.py`
* **Issue:** `fetch_ohlcv` only gets the latest 1000 candles. Long backtests are impossible.
* **Fix:** Implement a pagination loop (while loop).
    * Fetch batch -> update `since` timestamp -> fetch next batch.
    * Continue until `limit` is reached or current time is reached.
    * Concatenate all batches into one DataFrame.

**Task 3: Fix Look-Ahead Bias (Logic Error)**
* **File:** `app/backtesting/engine.py`
* **Issue:** Data is sliced using `.loc[start:end]` *before* indicators are calculated. This causes the first N candles (the warm-up period) to be `NaN` inside the backtest window, distorting results.
* **Fix:**
    1.  Fetch data with a buffer (e.g., `start_date` - 1000 candles).
    2.  Run `strategy.calculate_indicators(df)` on the FULL dataset.
    3.  **ONLY THEN** slice the DataFrame to `df.loc[start_date:end_date]` for the PnL calculation.

---

### PHASE 2: Simulation Engine (Continued)

#### Step 5: Simulation Hardening (Tests & Offline Mode)
* **Objective:** Make the backtest robust, reproducible, and mathematically proven.
* **Sub-task 5.1: Offline Data Mode**
    * Update `CryptoDataHandler`. Add methods `save_to_csv(symbol, timeframe)` and `load_from_csv`.
    * Modify `get_historical_data`: If a local file exists and covers the requested range, load it. Else, download from API and save it.
    * **Why:** Prevents API rate limits and ensures we test against the exact same data every time.
* **Sub-task 5.2: Unit Testing Suite**
    * Install `pytest`.
    * Create `tests/test_engine_logic.py`.
    * **Test Case:** Create a manual DataFrame (e.g., 10 rows) with known prices and known signals. Calculate expected PnL manually. Run `Backtester` on it. Assert results match exactly.

#### Step 5.5: Time-Aware Data Refactor (CRITICAL)
* **Objective:** Fix the "Recency Bias" in data fetching to allow backtesting specific historical periods (e.g., 2022).
* **Tasks:**
    1.  **Update Interface:** `IDataHandler.get_historical_data` must accept `start_date` and `end_date`.
    2.  **Refactor Handler:**
        - If `start_date` is present, fetch FORWARD from that date using `since` parameter in CCXT.
        - Stop fetching when `end_date` is reached.
        - **Smart Caching:** Verify cache by DATE RANGE (`min_date <= start` and `max_date >= end`), not just by length.
    3.  **Update Engine:** Pass the calculation start date to the handler.

#### Step 6: Advanced Backtest CLI (Iterability)
* **Objective:** Allow rapid strategy iteration by overriding parameters via CLI without editing config files.
* **File:** `run_backtest.py`
* **Tasks:**
    1.  **Dynamic Arguments:** Update `argparse` to accept strategy parameters dynamically (e.g., `--param fast_window=20`).
    2.  **Config Override:** Logic to merge CLI parameters into the loaded `BotConfig` object before running the backtest.
    3.  **Result Persistence:** Instead of just printing, SAVE the results (Metrics + Equity Curve) to a folder `results/backtest_{timestamp}.json`.
    4.  **Reporting:** Print a clear comparison table in the console (Config used vs Result).

---

#### Step 7: Persistence Layer (Database)
* **Objective:** Implement a persistent storage engine to track trades, signals, and bot state (preventing amnesia on restarts).
* **Tech Stack:** SQLAlchemy (ORM) + SQLite.
* **Tasks:**
    1.  **Setup:** Add `sqlalchemy` to dependencies. Create `app/core/database.py` (Engine & Session Factory).
    2.  **Models:** Create `app/models/sql.py` defining tables:
        - `Trade` (id, symbol, side, quantity, price, timestamp, strategy_id, pnl).
        - `Signal` (id, symbol, timestamp, signal_value, raw_data_json).
    3.  **Repositories:** Create `app/repositories/` implementing the Repository Pattern (abstraction over DB operations).
        - `trade_repo.add(trade)`, `trade_repo.get_all()`.
    4.  **Testing:** Unit tests for database operations using an in-memory SQLite instance (`:memory:`).

### PHASE 3: Live Execution

#### Step 8: Stateful Mock Executor (Paper Trading) ✅ COMPLETE
* **Objective:** Implement an execution engine that simulates trades and persists them to the database (The "Live" simulation).
* **File:** `app/execution/mock_executor.py`
* **Status:** Fully implemented with database persistence, position tracking, and CCXT-compatible interface.
* **Completed Tasks:**
    1.  ✅ **Implement Interface:** Inherits from `IExecutor` with full compliance.
    2.  ✅ **Dependency Injection:** Accepts `TradeRepository` and optional `SignalRepository` in `__init__`.
    3.  ✅ **Execution Logic:**
        - `execute_order` persists every trade to database
        - Simulates 100% fill rate
        - Returns CCXT-compatible order structure
        - Includes trade_db_id in order info
    4.  ✅ **State Management:** 
        - `get_position(symbol)` calculates net position from database
        - In-memory position cache for performance
        - `reset_position_cache()` method for testing
    5.  ✅ **Test:** Created `tests/test_execution.py` with 21 comprehensive test cases (all passing).

#### Step 9: The Live Trading Loop (Orchestrator) ✅ COMPLETE
* **Objective:** Connect all components (Data, Strategy, Executor, DB) into a running loop that reacts to the market in real-time.
* **Files:** `app/core/bot.py` and `run_live.py`.
* **Status:** Fully implemented with robust orchestration, error handling, and comprehensive testing.
* **Completed Tasks:**
    1.  ✅ **Class `TradingBot`:**
        - Coordinates Data → Strategy → Execution cycle
        - `run_once()`: Fetch data → Calculate indicators → Generate signals → Check position → Execute trades → Save signal
        - `start()`: Infinite loop with exception handling, logging, and configurable sleep
        - Buffer size auto-calculated from strategy parameters
        - Last signal tracking to avoid duplicate trades
    2.  ✅ **Signal Persistence:** Every signal saved to `SignalRepository` with metadata (indicators, price, timestamp)
    3.  ✅ **Order Logic:**
        - Signal 1 (BUY) + Flat → Execute BUY
        - Signal -1 (SELL) + Long → Execute SELL
        - Signal 0 (NEUTRAL) → No action
        - Duplicate signals filtered
        - Position conflicts handled correctly
    4.  ✅ **Entrypoint (`run_live.py`):**
        - Complete dependency injection chain
        - CLI args: --config, --mode (mock/live), --sleep
        - Loads config, initializes DB, creates all components
        - Runs bot with error handling
    5.  ✅ **Test:** Created `tests/test_trading_bot.py` with 23 comprehensive test cases (all passing).


#### Step 9.5: The Real Money Bridge (Binance Executor) ✅ **DONE**
* **Objective:** Implement the actual connection to Binance via CCXT and allow switching between "Paper" and "Live" modes.
* **Requirements Met:**
    1.  ✅ **Config Update:** Added `execution_mode` field to `BotConfig` with Literal["paper", "live"] type. Defaults to "paper". Added validator with warnings when live mode is enabled. Updated `settings/config.json` with execution_mode field.
    2.  ✅ **BinanceExecutor:** Created `app/execution/binance_executor.py` (267 lines).
        - ✅ Implements `IExecutor` interface (same as MockExecutor).
        - ✅ Integrated with CCXT library for real exchange orders.
        - ✅ Supports market and limit orders via `create_market_order()` and `create_limit_order()`.
        - ✅ Comprehensive error handling:
            - `ccxt.NetworkError` → Logged and re-raised for bot to retry
            - `ccxt.InsufficientFunds` → Logged, returned None, bot continues
            - `ccxt.ExchangeError` → Logged and re-raised
            - Unexpected errors → Critical log and re-raised
        - ✅ **Database Persistence:** All successful trades saved to DB with trade_repository.create().
        - ✅ **Position Tracking:** Uses `client.fetch_balance()` to get real exchange position.
        - ✅ Multiple warning logs with ⚠️ emoji throughout execution.
    3.  ✅ **Factory Logic:** Updated `run_live.py` executor factory:
        - ✅ Reads `config.execution_mode` to determine executor type.
        - ✅ Creates BinanceExecutor for "live" mode with CCXT client.
        - ✅ Creates MockExecutor for "paper" mode.
        - ✅ Supports sandbox mode via `config.exchange.sandbox_mode`.
        - ✅ Fallback to MockExecutor if BinanceExecutor initialization fails.
        - ✅ Updated CLI documentation (removed --mode arg, now uses config).
    4.  ✅ **Test:** Created `tests/test_binance_executor.py` with 20 comprehensive test cases (all passing).
* **Safety Features:**
    - ⚠️ Multiple warnings when live mode is enabled
    - Sandbox mode support for testing with fake money
    - Database persistence failure doesn't crash trading
    - All errors logged with appropriate severity levels

---

### PHASE 4: Deployment & QA

#### Step 10: Dockerization & System Hardening ✅ COMPLETE
* **Objective:** Containerize the application and harden the data model for production.
* **Status:** Complete (2025-11-20)
* **Completion Report:** `settings/steps_log/STEP_10_COMPLETION_REPORT.md`
* **Implemented:**
    1.  **Data Model Hardening:** Added `exchange_order_id` column to Trade model with indexing. BinanceExecutor extracts from CCXT response. MockExecutor generates fake IDs.
    2.  **Config Hardening:** Verified no hardcoded quantities. All calculations use `config.risk.max_position_size_usd`.
    3.  **Dockerfile:** Multi-stage build with Poetry, non-root user, health check, optimized image size.
    4.  **Docker Compose:** Service definition with environment injection, persistent volumes, resource limits, log rotation.
    5.  **Documentation:** Comprehensive `DEPLOY.md` (1,200+ lines) covering deployment, monitoring, troubleshooting, security.
* **Test Results:** All 110 tests passing. Zero linter errors.
* **Impact:** Bot is now production-ready for Docker deployment with full audit trail and security hardening.

#### Step 10.5: System Integration Testing (E2E)
* **Objective:** Verify the complete "Zero to Hero" flow: Data -> Signal -> Decision -> Database Execution.
* **File:** `tests/test_system_flow.py`
* **Tasks:**
    1.  **Synthetic Market Fixture:** Create a test fixture that generates a DataFrame with a clear "Pump and Dump" pattern (Prices go up, then down) to force signals.
    2.  **Full Bot Instantiation:** Instantiate `TradingBot` with a real `SQLAlchemy` DB (in-memory), real `SmaCrossStrategy`, real `MockExecutor`, and a *Mocked* `DataHandler`.
    3.  **Scenario Test:**
        - Run `bot.run_once()` on "Uptrend Data" -> Assert `trades` count == 1 (BUY).
        - Run `bot.run_once()` on "Downtrend Data" -> Assert `trades` count == 2 (SELL).
        - Verify `TradeRepository` has the correct entries (Symbol, Side, Price).

#### Step 11: APPLY ROBUST PARAMETERS
**Role:** Configuration Specialist.

**Objective:**
Update the main strategy configuration file (`settings/config.json`) with the robust parameters identified through the Walk-Forward Optimization (WFO) analysis.

**Specification:**

1.  Locate `settings/config.json`.
2.  Update the `strategy_config` section for `SmaCrossStrategy` to the following values:
    * `fast_window`: 10
    * `slow_window`: 100
3.  Ensure the configuration file remains valid JSON.

**Rationale:**
The parameters (10, 100) demonstrated the only positive Sharpe Ratio (0.513) on unseen (Out-of-Sample) data, proving resilience against market regime shifts and high overfitting risk compared to the deceptively higher In-Sample performers.

#### Step 12: VOLATILITY-ADJUSTED STRATEGY (ATR)

**Role:** Senior Quantitative Developer & Strategy Architect.

**Objective:**
Develop a new, more advanced strategy, `VolatilityAdjustedStrategy`, that is built on the current SMA Cross logic but incorporates the Average True Range (ATR) indicator to manage risk and filter low-volatility entries. This shifts the core design from a simple price-crossing logic to a risk-aware, adaptive system.

**Specification for `app/strategies/atr_strategy.py`:**

1.  **Strategy Class:** Create a new class: `VolatilityAdjustedStrategy` inheriting from `BaseStrategy`.
2.  **New Pydantic Configuration:** Define a new `StrategyConfig` in `app/config/models.py` for this strategy, including:
    * `fast_window`: integer (e.g., 10)
    * `slow_window`: integer (e.g., 100)
    * `atr_window`: integer (e.g., 14)
    * `atr_multiplier`: float (e.g., 2.0) - *This will define the initial Stop-Loss distance in multiples of ATR.*
3.  **Signal Generation Logic (Hybrid):**
    * **Entry Signal:** A buy signal is generated ONLY if the fast SMA crosses above the slow SMA **AND** the current price is moving (volatility check). A basic volatility check can be: `Current_Price - Price_N_Periods_Ago > 1.0 * Current_ATR`. (Implement a simple version of this volatility filter).
4.  **Risk Management Integration (Mandatory):**
    * The primary role of the ATR is to dynamically define the Stop-Loss (SL) level.
    * When generating a `Signal.BUY`, the generated `Signal` object **must** include an estimated `stop_loss_price`.
    * The `stop_loss_price` calculation must be: `Entry_Price - (ATR_Multiplier * Current_ATR_Value)`.
    * The `TradingBot` logic must be updated in a subsequent step to enforce this SL price, but the strategy must provide it now.

**Architectural Impact:**
This strategy introduces the concept of **dynamic risk sizing** and **volatility filtering**, a necessary architectural pivot to create a robust trading system that goes beyond curve-fitting. This will require modification of the `TradingBot` and `BacktestingEngine` interfaces to accept and process the dynamic SL. (This second modification is reserved for the next prompt).


---
### Step 16: Multi-Dimensional Strategy Optimization (Expanded WFO)

**Objective:** To combat systemic overfitting (Sharpe $0.114$ IS $\rightarrow -0.103$ OOS) by expanding the parameter search space to include **all** critical parameters of the `VolatilityAdjustedStrategy`. An optimization limited only to SMA windows generates biased and unstable results.

**Mandatory Implementation:** Modify the `tools/optimize_strategy.py` script.

1.  **Update CLI:** Add new command-line arguments (`--atr-window`, `--atr-multiplier`) to define the search ranges for these volatility parameters.
2.  **Combination Generation:** Replace the current two-dimensional `itertools.product` with a four-dimensional Cartesian product including the ranges for: `fast_window`, `slow_window`, `atr_window`, and `atr_multiplier`.
3.  **Parameter Injection:** Ensure all four parameters are correctly injected into the `StrategyConfig` prior to instantiating the `VolatilityAdjustedStrategy` within the `_run_single_backtest` function.
4.  **Constraint:** Maintain and validate the `fast_window < slow_window` constraint.

**Validation:** Execute the expanded Walk-Forward Optimization (WFO) to generate a robust multi-dimensional dataset necessary for the subsequent robustness analysis.

---
### Step 17: Implementation of Multi-Objective Robustness Analyzer

**Objective:** Formalize the quantitative analysis required by the previous step by creating a dedicated Python tool, `tools/analyze_optimization.py`, capable of processing the 4D Walk-Forward Validation (WFO) output and selecting the most robust parameters based on the stability of OOS performance.

**Mandatory Implementation:** Create the script `tools/analyze_optimization.py`.

1.  **CLI Interface:** Must accept a single argument: `--input-file` (the path to the WFO JSON results).
2.  **Data Ingestion:** Load WFO results (which contain nested `IS_metrics` and `OOS_metrics`).
3.  **Calculation Engine:** Implement a function to calculate the **Robustness Factor (FR)** for every configuration:
    $$FR = \text{Sharpe}_{\text{OOS}} \times \left( \frac{\text{Sharpe}_{\text{OOS}}}{\text{Sharpe}_{\text{IS}}} \right)$$
    *Note: Handle division by zero/near-zero $\text{Sharpe}_{\text{IS}}$ gracefully (e.g., set FR to zero or a minimum value for negative or near-zero $\text{Sharpe}_{\text{IS}}$).*
4.  **Ranking and Filtering:** Sort all validated results by the calculated **Robustness Factor** (descending).
5.  **Output & Visualization:** Display a clear, tabular summary of the Top 5 results, showing:
    * Parameters
    * $\text{Sharpe}_{\text{IS}}$
    * $\text{Sharpe}_{\text{OOS}}$
    * Degradation Ratio ($\text{Sharpe}_{\text{OOS}} / \text{Sharpe}_{\text{IS}}$)
    * **Robustness Factor (FR)**
6.  **Final Recommendation:** Display the configuration with the highest FR as the parameter set recommended for `config.json`.

**Precondition:** Requires the successful completion and execution of Step 16 (4D WFO).

### Step 18: Market Regime Filter Module Design (Architecture)

**Objective:** Implement a core architectural separation between **Market State** and **Trading Signal** to combat severe Out-of-Sample (OOS) degradation. The strategy must be context-aware, filtering out operations during market regimes that destroy its edge (e.g., ranging/lateral markets).

**Goal:** Create the necessary interfaces, configurations, and dependencies for the Market Regime Filter, making it an injectable component.

**Mandatory Implementation (New Architectural Components):**

1.  **Interface Definition (Decoupling):**
    * **File:** `app/core/interfaces.py`
    * **Action:** Define a new abstract interface, `IMarketRegimeFilter`, with a single core method: `get_regime(data: pd.DataFrame) -> pd.Series`.

2.  **Market State Enumeration:**
    * **File:** `app/core/enums.py`
    * **Action:** Define a new `Enum` named `MarketState` with at least three distinct states: `TRENDING_UP`, `TRENDING_DOWN`, and `RANGING`.

3.  **Filter Configuration Model:**
    * **File:** `app/config/models.py`
    * **Action:** Define a Pydantic model, `RegimeFilterConfig`, to hold the specific parameters for the initial filter implementation (ADX-based). Must include `adx_window: int` and `adx_threshold: int` to enable future optimization.

4.  **Strategy Modification (Dependency Injection):**
    * **File:** Modify the constructors of `BaseStrategy` and its children (e.g., `VolatilityAdjustedStrategy`) to accept an instance of `IMarketRegimeFilter` as a mandatory dependency.
    * **Goal:** The strategy must now explicitly hold a reference to the filter.

5.  **New Filter Module:**
    * **File:** Create a new Python file: `app/strategies/regime_filters.py`.
    * **Action:** Define the concrete implementation class, `ADXVolatilityFilter`, which inherits from `IMarketRegimeFilter` and accepts `RegimeFilterConfig` in its constructor. (The actual calculation logic will be implemented in Step 19).

**Preconditions:** Requires structural changes to the core architecture to support injection.

---
### Step 19: ADX/DMI Filter Logic and Conditional Signal Implementation

**Objective:** Implement the core quantitative logic of the Market Regime Filter and integrate its output into the trading signal generation process.

**Mandatory Implementation:**

1.  **Filter Logic Implementation:**
    * **File:** `app/strategies/regime_filters.py`.
    * **Action:** Implement `ADXVolatilityFilter.get_regime(data)` using the ADX and DMI technical indicators to classify each candlestick into one of the `MarketState` enums (`TRENDING_UP`, `TRENDING_DOWN`, or `RANGING`).

2.  **Conditional Signal Generation:**
    * **File:** `app/strategies/atr_strategy.py` (or `BaseStrategy.py`).
    * **Action:** Modify `generate_signals` to:
        * a) Call the injected `IMarketRegimeFilter` to get the `MARKET_STATE` series.
        * b) Conditionally filter the `RAW_SIGNAL`: **A BUY signal is only valid if `MARKET_STATE` is `TRENDING_UP`. A SELL signal (for entry) is only valid if `MARKET_STATE` is `TRENDING_DOWN`.**
        * c) **Crucially:** Ensure exit signals (Stop Loss/Take Profit) are **not** filtered by the regime, as risk management must always execute.

---
### Architecture Backlog (Pending)

* **Refactor: Abstracted Exchange Connector**
    * **Priority:** High (Operational Security)
    * **Rationale:** Eliminate the critical Single Point of Failure (SPOF) risk associated with sole dependency on the Binance API/service availability. This framework must enable rapid migration to another exchange (e.g., Kraken, Bybit) or future multi-platform operation without modifying core trading logic (Bot, Strategy, Backtester), only the `IExecutor` initialization.
---


<!-- 
python tools/optimize_strategy.py \
  --start-date 2020-01-01 \
  --end-date 2025-11-20 \
  --split-date 2023-01-01 \
  --fast 5,10,15,50 \
  --slow 50,100,150,200 \
  --atr-window 10,14,20 \
  --atr-multiplier 1.5,2.0,2.5 -->