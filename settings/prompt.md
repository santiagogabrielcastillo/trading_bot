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

#### Step 6: Backtest Runner Refinement
* **File:** `run_backtest.py`
* **Task:** Update the script to use the new "Offline Mode" by default to speed up iteration.

---

### PHASE 3: Live Execution

#### Step 7: Mock Executor (Paper Trading)
* **File:** `app/execution/mock_executor.py`
* **Requirements:**
    - Implement `IExecutor`.
    - Simulate latency (optional).
    - Keep track of "fake" wallet balance.

#### Step 8: Binance Executor (Real Money)
* **File:** `app/execution/binance_executor.py`
* **Requirements:**
    - Use `ccxt` private methods.
    - **Error Handling:** Wrap calls in `try/except` blocks catching `ccxt.NetworkError`, `ccxt.ExchangeError`.
    - **Kill Switch:** If drawdown > X% in a day, stop everything.

---

### PHASE 4: Deployment & QA

#### Step 9: Dependency Locking
* **Task:** Initialize `poetry` or `uv` to lock versions of `pandas`, `numpy`, `ccxt`.

#### Step 10: QA Hooks
* **Task:** Setup `pre-commit` to run `ruff` (linting) and `mypy` (typing) before every commit.