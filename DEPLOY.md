# Trading Bot Deployment Guide

Complete guide for deploying and running the trading bot in production using Docker.

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)
- [Security Best Practices](#security-best-practices)

---

## 🔧 Prerequisites

### System Requirements

- **Docker**: 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- **Docker Compose**: 2.0+ ([Install Docker Compose](https://docs.docker.com/compose/install/))
- **Minimum Resources**:
  - CPU: 1 core (2+ recommended)
  - RAM: 512MB (1GB+ recommended)
  - Disk: 1GB free space

### Binance Account Setup

1. **Create Binance Account**: [https://www.binance.com](https://www.binance.com)
2. **Enable 2FA**: Security → Two-Factor Authentication
3. **Generate API Keys**:
   - Go to: Account → API Management
   - Create new API key
   - **Important**: Set the following restrictions:
     - ✅ Enable Reading
     - ✅ Enable Spot & Margin Trading
     - ❌ Disable Withdrawals
     - ✅ Enable IP Whitelist (recommended)

---

## 🚀 Quick Start

### 1. Clone Repository (if not already done)

```bash
git clone <your-repo-url>
cd trading_bot
```

### 2. Create Environment File

Copy the example environment file and fill in your credentials:

```bash
cp env.example .env
```

Edit `.env` with your editor:

```bash
nano .env  # or vim, code, etc.
```

**Required Configuration**:

```bash
# Binance API Credentials
BINANCE_API_KEY=your_actual_api_key_here
BINANCE_SECRET=your_actual_secret_here

# Execution Mode (IMPORTANT!)
EXECUTION_MODE=paper  # Start with paper trading!

# Logging
LOG_LEVEL=INFO
```

### 3. Configure Trading Strategy

Edit `settings/config.json` to configure your strategy parameters:

```json
{
  "exchange": {
    "name": "binance",
    "api_key": "WILL_BE_OVERRIDDEN_BY_ENV",
    "api_secret": "WILL_BE_OVERRIDDEN_BY_ENV",
    "sandbox_mode": false
  },
  "risk": {
    "max_position_size_usd": 100.0,
    "stop_loss_pct": 0.02,
    "take_profit_pct": 0.04
  },
  "strategy": {
    "name": "simple_ma_crossover",
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "params": {
      "fast_window": 10,
      "slow_window": 50
    }
  },
  "db_path": "trading_state.db",
  "execution_mode": "paper"
}
```

### 4. Build and Start the Bot

```bash
# Build the Docker image
docker-compose build

# Start the bot (detached mode)
docker-compose up -d

# View logs
docker-compose logs -f
```

---

## ⚙️ Configuration

### Environment Variables (.env)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BINANCE_API_KEY` | Yes | - | Binance API key |
| `BINANCE_SECRET` | Yes | - | Binance API secret |
| `EXECUTION_MODE` | No | `paper` | Trading mode: `paper` or `live` |
| `LOG_LEVEL` | No | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Strategy Configuration (settings/config.json)

- **risk.max_position_size_usd**: Maximum position size in USD
- **strategy.symbol**: Trading pair (e.g., `BTC/USDT`)
- **strategy.timeframe**: Candlestick interval (e.g., `1h`, `4h`, `1d`)
- **strategy.params**: Strategy-specific parameters

---

## 🐳 Deployment

### Production Deployment

#### Option 1: Docker Compose (Recommended for Single Server)

```bash
# Start in detached mode
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f trading-bot

# Stop the bot
docker-compose down
```

#### Option 2: Docker Run (Advanced)

```bash
# Build image
docker build -t trading-bot:latest .

# Run container
docker run -d \
  --name trading-bot \
  --restart unless-stopped \
  -e BINANCE_API_KEY=$BINANCE_API_KEY \
  -e BINANCE_SECRET=$BINANCE_SECRET \
  -e EXECUTION_MODE=paper \
  -v $(pwd)/settings:/app/settings:ro \
  -v $(pwd)/data_cache:/app/data_cache \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/trading_state.db:/app/trading_state.db \
  trading-bot:latest
```

### Persistent Data Volumes

The bot uses several volumes for persistent data:

| Volume | Purpose | Backup? |
|--------|---------|---------|
| `./settings` | Configuration files | Yes (version controlled) |
| `./data_cache` | Historical price data cache | Optional |
| `./logs` | Application logs | Optional |
| `./trading_state.db` | Trade/signal database | **Critical** |
| `./results` | Backtest results | Optional |

---

## 📊 Monitoring

### View Live Logs

```bash
# Follow all logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Logs since specific time
docker-compose logs --since=30m
```

### Check Bot Status

```bash
# Container status
docker-compose ps

# Health check
docker inspect --format='{{.State.Health.Status}}' trading-bot

# Resource usage
docker stats trading-bot
```

### Database Inspection

Access the SQLite database to inspect trades and signals:

```bash
# Install sqlite3 (if not installed)
# macOS: brew install sqlite
# Ubuntu: apt-get install sqlite3

# Open database
sqlite3 trading_state.db

# Example queries
sqlite> SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;
sqlite> SELECT COUNT(*), side FROM trades GROUP BY side;
sqlite> SELECT * FROM signals ORDER BY timestamp DESC LIMIT 10;
```

---

## 🔍 Troubleshooting

### Bot Won't Start

**Check logs:**
```bash
docker-compose logs trading-bot
```

**Common issues:**
- Missing API credentials in `.env`
- Invalid API keys
- Network connectivity issues
- Invalid configuration in `config.json`

### Database Locked Error

```bash
# Stop the bot
docker-compose down

# Remove database lock (if exists)
rm -f trading_state.db-journal

# Restart
docker-compose up -d
```

### API Rate Limiting

If you see rate limit errors:
- Increase sleep interval in `run_live.py`
- Reduce data fetch frequency
- Use local cache more aggressively

### Container Keeps Restarting

```bash
# Check exit code
docker inspect trading-bot | grep -A 5 State

# View last crash logs
docker-compose logs --tail=50 trading-bot
```

---

## 🔐 Security Best Practices

### 1. API Key Security

✅ **DO:**
- Store API keys in `.env` file (never in code)
- Add `.env` to `.gitignore`
- Use Binance IP whitelist restrictions
- Disable withdrawal permissions
- Rotate API keys regularly

❌ **DON'T:**
- Commit `.env` to version control
- Share API keys in chat/email
- Use API keys with withdrawal permissions
- Use production keys for testing

### 2. Server Security

```bash
# Use firewall
sudo ufw enable
sudo ufw allow 22/tcp  # SSH only

# Keep system updated
sudo apt update && sudo apt upgrade

# Use SSH keys (disable password auth)
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no

# Monitor SSH access
sudo tail -f /var/log/auth.log
```

### 3. Docker Security

```bash
# Run container as non-root user (already configured in Dockerfile)
# Limit container resources (already configured in docker-compose.yml)

# Scan image for vulnerabilities (optional)
docker scan trading-bot:latest
```

### 4. Database Backup

```bash
# Create backup script
cat > backup_db.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
cp trading_state.db backups/trading_state_$DATE.db
find backups/ -name "*.db" -mtime +7 -delete  # Keep 7 days
EOF

chmod +x backup_db.sh

# Run daily via cron
crontab -e
# Add: 0 2 * * * /path/to/backup_db.sh
```

---

## 🚨 Going Live (Real Money)

### Pre-Flight Checklist

Before switching to `EXECUTION_MODE=live`:

- [ ] Successfully run in paper mode for at least 7 days
- [ ] Verified strategy performance in backtests
- [ ] Tested with Binance Testnet (sandbox mode)
- [ ] Set appropriate position sizes (start small!)
- [ ] Configured stop-loss and take-profit levels
- [ ] Set up monitoring and alerts
- [ ] Created database backup system
- [ ] Tested bot restart and recovery
- [ ] Verified API key restrictions
- [ ] Enabled IP whitelist on Binance
- [ ] Have emergency stop plan

### Switching to Live Mode

1. **Update `.env`:**
   ```bash
   EXECUTION_MODE=live
   ```

2. **Restart bot:**
   ```bash
   docker-compose down
   docker-compose up -d
   ```

3. **Monitor closely:**
   ```bash
   docker-compose logs -f
   ```

4. **Watch for warnings:**
   Look for `⚠️` symbols in logs indicating live trades

### Emergency Stop

```bash
# Immediate stop
docker-compose down

# Close all positions manually on Binance if needed
# Go to: Binance → Wallet → Spot → Sell All
```

---

## 📞 Support

- **Issues**: Open GitHub issue
- **Logs**: Always include relevant logs when reporting issues
- **Database**: Backup before requesting support

---

## 📝 License

[Your License Here]

---

**⚠️  DISCLAIMER**: This bot trades with real money when in live mode. Past performance does not guarantee future results. Only risk capital you can afford to lose. The authors are not responsible for any financial losses.

