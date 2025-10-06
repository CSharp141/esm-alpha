# ESM Alpha Algo

Algorithmic trading framework for **memecoins** and **low-liquidity cryptocurrencies** — data collection, backtesting, and live deployment.

---

## 🚀 Branch Strategy

We use a **three-tier Git workflow**:

| Branch | Purpose | Notes |
|-------|---------|------|
| `main` | **Production** | Only tested, ready-to-run code for live trading |
| `dev`  | **Development / Backtesting** | New features, research, integration tests |
| `feat/*` | **Feature / Strategy Branches** | Each new strategy/major feature starts here |

### Typical Flow
1. **Create a new branch** from `dev`  
   ```bash
   git checkout dev
   git pull
   git switch -c feat/strat-<name>
   ```
2. Develop and **backtest** locally.
3. Open a **PR → `dev`** with results for review.
4. After integration tests pass, **release PR → `main`**.
5. Tag and deploy from `main`.

> ✅ Only `main` runs on live accounts; `dev` is for experiments/sims.

---

## 🧩 Branch Naming

- `feat/strat-<strategy-name>` – new strategy  
- `fix/<scope>` – bugfix  
- `chore/<task>` – maintenance/tooling

Examples:
```
feat/strat-pepe-v1
fix/slippage-rounding
chore/update-ci
```

---

## 🔁 Promote to Production

```bash
# Merge dev → main when stable
git checkout main
git pull
git merge --no-ff dev
git tag -a vX.Y.Z -m "Release: <summary>"
git push origin main --tags
```

---

## 📊 Strategy PR Requirements (to `dev`)

- Backtest metrics (PnL, Sharpe, max drawdown)
- Risk notes (exposure limits, capital, kill-switch)
- Sample plots/equity curve
- Config used (e.g. `config/strategies/<name>.yaml`)

---

## 🛡️ Rules

- No direct commits to `main` or `dev`
- All changes via PR + review
- Tag each production release (e.g., `v0.5.0`)

---

## ⚙️ Environments

| Mode | Branch | Description |
|------|--------|-------------|
| Backtest | `dev` | Local/paper testing |
| Live     | `main` | Production accounts |

**In short:** develop in `feat/*` → test in `dev` → deploy from `main`.
