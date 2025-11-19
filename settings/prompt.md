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

## 2. Current Project State
We have completed **Phase 1 (Core & Config)** and verified the Strategy vectorization.
* **Interfaces:** `app/core/interfaces.py` (Clean).
* **Data:** `app/data/handler.py` (Needs hardening).
* **Strategy:** `app/strategies/sma_cross.py` (Vectorized).

**We are currently entering Phase 2 (Simulation Engine).**

---

## 🚨 MANDATORY PROTOCOL: AUTO-LOGGING 🚨
**CRITICAL INSTRUCTION:**
After you successfully complete ANY step or task defined below, you **MUST** automatically update the file `DEVLOG.md` located in the root directory.
**Do not ask for permission.** Treat the log update as part of the code generation process.

---

## 3. Execution Roadmap

### PHASE 1: Core Architecture (Completed)
*Status: Done. Pending Refinement.*

---

### 🛑 PHASE 1 REFINEMENT CHECKPOINT (We are here) 🛑
* **Objective:** Harden the core before building the backtester.
* **Task 1 (Data Integrity):** Update `CryptoDataHandler` in `app/data/handler.py`.
    - Add `validate_integrity(df)` method.
    - Check for missing timestamps (gaps) using `pd.date_range` and warn/fill them.
* **Task 2 (Structured Logging):**
    - Create `app/utils/logger.py` using `loguru`.
    - Replace `print` statements in `handler.py` and `test_data.py` with proper logs.

---

### PHASE 2: Simulation Engine (Backtesting)

#### Step 4: Vectorized Backtester
* **Objective:** Build the engine that calculates PnL without loops.
* **File:** `app/backtesting/engine.py`
* **Requirements:**
    1.  Class `Backtester` initialized with a `BaseStrategy` instance.
    2.  Method `run(start_date, end_date)`:
        - Fetches data using `DataHandler`.
        - Runs `strategy.generate_signals(df)`.
        - **Vectorized PnL:** Calculate daily returns using `df['signal'].shift(1) * df['pct_change']`.
        - **Metrics:** Compute Total Return, Sharpe Ratio, and Max Drawdown using pandas operations (No loops!).
    3.  **Output:** Return a Dictionary with metrics and the full DataFrame.

#### Step 5: Backtest Runner Script
* **File:** `run_backtest.py` (Root directory).
* **Requirements:**
    - Load config.
    - Instantiate components.
    - Run `Backtester` and log results using `loguru`.

#### 🛑 PHASE 2 REFINEMENT CHECKPOINT 🛑
* **Objective:** Audit the Math & Performance.
* **Task:** Create a unit test `tests/test_backtest_logic.py`.
    - Create a small DataFrame with *known* prices (manual calculation).
    - Run the backtester on it.
    - Assert that the PnL matches the manual calculation exactly.
    - **Why:** To prove our vectorization logic isn't hallucinating returns.

---

### PHASE 3: Live Execution

#### Step 6: Mock Executor (Paper Trading)
* **File:** `app/execution/mock_executor.py`
* **Requirements:**
    - Implement `IExecutor`.
    - Simulate latency (optional).
    - Keep track of "fake" wallet balance.

#### Step 7: Binance Executor (Real Money)
* **File:** `app/execution/binance_executor.py`
* **Requirements:**
    - Use `ccxt` private methods.
    - **Error Handling:** Wrap calls in `try/except` blocks catching `ccxt.NetworkError`, `ccxt.ExchangeError`.

#### 🛑 PHASE 3 REFINEMENT CHECKPOINT 🛑
* **Objective:** Safety First.
* **Task:** Implement a "Kill Switch" in `BinanceExecutor`.
    - If drawdown in a single day > X%, stop all trading.
    - If API errors > 5 in 1 minute, stop all trading.

---

### PHASE 4: Deployment & QA

#### Step 8: Dependency Locking
* **Task:** Initialize `poetry` or `uv` to lock versions of `pandas`, `numpy`, `ccxt`.

#### Step 9: Dockerization
* **Files:** `Dockerfile`, `docker-compose.yml`.

#### Step 10: QA Hooks
* **Task:** Setup `pre-commit` to run `ruff` (linting) and `mypy` (typing) before every commit.