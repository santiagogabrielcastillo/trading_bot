# DevLog: Python Trading Bot (BTC)

## Project Status
- **Current Phase:** 2 - Simulation Engine (Backtesting).
- **Last Update:** 2025-11-19.
- **Health:** Green (Architecture corrected for vectorization).

## Progress Log

### Phase 1: Core Architecture & Foundations
- [x] **Architecture Design:** Defined modular structure (Data, Strategy, Execution).
- [x] **Interfaces:** Created `IDataHandler`, `IExecutor`, `BaseStrategy` in `app/core/interfaces.py`.
- [x] **Data Layer:** Implemented `CryptoDataHandler` using `ccxt`.
- [x] **Configuration:** Implemented strict Pydantic models in `app/config/models.py`.
- [x] **Refactor (Critical):** Replaced iterative `check_signal` with vectorized `generate_signals` in `BaseStrategy`.
- [x] **Strategy:** Implemented `SmaCrossStrategy` using pure `numpy` vectorization in `app/strategies/sma_cross.py`.

### Phase 2: Simulation Engine (Current Focus)
- [x] Implement `Backtester` class (Vectorized PnL calculation).
- [x] Create `run_backtest.py` entry script.
- [ ] Validate Strategy Metrics (Sharpe, Drawdown).

### Phase 3: Execution & Production
- [ ] Implement `MockExecutor` (Paper Trading).
- [ ] Implement `BinanceExecutor` (Real Execution).
- [ ] Create `main.py` CLI.
- [ ] Dockerize application (`Dockerfile`, `docker-compose`).

## Technical Decisions Record
- **2025-11-19 (Vectorization):** Shifted from Event-Driven Loops to Vectorized Backtesting.
    - *Reason:* Loops over Pandas rows are too slow for optimizing parameters over long historical periods.
    - *Impact:* `BaseStrategy` now enforces `generate_signals(df)` returning a full DataFrame column.
- **2025-11-19 (Configuration):** Adopted `Pydantic`.
    - *Reason:* To prevent runtime errors due to missing keys or wrong types in configuration files (e.g., API Keys).
- **2025-11-19 (Testing):** Decided to use `MockExecutor` for initial live-loop testing before connecting to real Binance APIs to prevent accidental capital loss.
- **2025-11-19 (Backtester Metrics):** Standardized on daily-frequency Sharpe (252 periods) with equity-curve drawdown tracking in `app/backtesting/engine.py`.
    - *Reason:* Keeps reporting consistent across timeframes while satisfying roadmap requirement for daily metrics.
    - *Impact:* Any strategy evaluation plugs directly into uniform KPI outputs.
- **2025-11-19 (Configuration File):** Added `settings/config.json` as the canonical source for bot settings consumed by `run_backtest.py`.
    - *Reason:* Enables scripted backtests without hardcoding credentials/params.
    - *Impact:* Future runners (live or batch) can reuse the same config contract.

## Known Issues / Backlog
- **Pending:** Need to decide on a logging library (standard `logging` vs `loguru`). Standard `logging` is assumed for now.
- **Pending:** Database selection for state persistence (SQLite vs Redis) is deferred until Phase 3.