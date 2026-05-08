# QuantForge v1.3 Development Plan

Final polish. Intraday + DL/RL + dashboard + LLM. 3 batches M/N/O.

## Batch M — Intraday + data (5 agents)

### M.1 Minute-bar backtest engine
File: `quantforge/core/engine_intraday.py`
- Engine for minute/hourly bars
- Calendar-aware (RTH only / 24h crypto)
- Position carry-over across days

### M.2 Tick/volume/dollar bars
File: `quantforge/core/bars.py`
- Convert tick data to volume-clock bars, dollar bars
- Per Lopez de Prado AFML Ch.2

### M.3 Multi-frequency cost model
File: `quantforge/core/costs_intraday.py`
- Intraday slippage scales with bid-ask
- Time-of-day participation rate adjustment

### M.4 Real-time ingestion adapter
File: `quantforge/core/realtime.py`
- Wrap yfinance live API + websocket-style polling
- Buffer bars, replay through engine

### M.5 Microstructure features
File: `quantforge/ml/microstructure.py`
- Spread proxy, signed volume, order flow imbalance
- VPIN, Kyle's lambda

## Batch N — Deep learning + RL (5 agents)

### N.1 LSTM forecaster
File: `quantforge/ml/lstm.py`
- PyTorch LSTM for return prediction
- Walk-forward training

### N.2 Transformer-based predictor
File: `quantforge/ml/transformer.py`
- Time-series transformer (attention over sequence)
- Multi-horizon forecast

### N.3 RL trading agent
File: `quantforge/ml/rl_agent.py`
- Gym-style trading env
- DQN / PPO via stable-baselines3

### N.4 Sequence model strategy wrapper
File: `quantforge/strategies/library/seq_model.py`
- Wraps any sequence model (LSTM/Transformer/RL)
- Implements Strategy interface

### N.5 Feature engineering pipeline
File: `quantforge/ml/features_pipeline.py`
- Standard feature set: rolling stats + lags + technical indicators
- Reusable across DL/ML strategies

## Batch O — Dashboard + brokers + LLM (5 agents)

### O.1 Streamlit live dashboard
File: `quantforge/monitoring/dashboard.py`
- Real-time PnL, positions, alerts
- Per-strategy panels

### O.2 Email/webhook alerts
File: `quantforge/monitoring/alerts.py`
- SMTP email
- Slack/Discord webhooks
- Drift, MDD, daily-loss-limit triggers

### O.3 Multi-broker abstraction
File: `quantforge/deployment/brokers.py`
- Adapter pattern: IB, Alpaca, Coinbase, Kraken
- Order routing + position sync

### O.4 LLM research assistant
File: `quantforge/research/llm_assistant.py`
- Anthropic API integration
- Reads RESEARCH_LOG, proposes ideas
- Drafts new strategies

### O.5 Drift detection + auto-retrain
File: `quantforge/monitoring/drift.py`
- Page-Hinkley, ADWIN drift detectors
- Trigger retrain when distribution shifts
