# IPMI Broker Discovery Agent

Automatically discovers international health insurance (IPMI) brokers across 36 underserved countries. Runs weekly on GitHub Actions — no server needed.

---

## What it does

- Searches Google via SerpApi for IPMI brokers in each target country
- Scrapes each broker website to extract contact details
- Scores each result for IPMI relevance (0–100)
- Exports a ranked CSV of leads every week
- Runs automatically every Monday at 7:00 AM UAE time

---

## Target countries (36 total)

| Region | Countries |
|---|---|
| Middle East | Oman, Saudi Arabia, Kuwait, Bahrain, Qatar, Jordan, Lebanon |
| South/SE Asia | Sri Lanka, Pakistan, Bangladesh, Nepal, Vietnam, Thailand, Philippines, Malaysia, India (low priority) |
| Small Europe | Luxembourg, Slovenia, Croatia, Estonia, Latvia, Lithuania, Cyprus, Iceland, Montenegro, Albania |
| LATAM | Panama, Costa Rica, Uruguay, Paraguay, Bolivia, Ecuador, Guatemala, Honduras, El Salvador, Dominican Republic |

---

## Setup (15 minutes)

### Step 1 — Create GitHub repository

1. Go to [github.com/new](https://github.com/new)
2. Name it `ipmi-broker-agent`
3. Set to **Private**
4. Click **Create repository**

### Step 2 — Upload files

Upload these files to the repo root:
```
ipmi-broker-agent/
├── broker_agent.py
├── requirements.txt
├── README.md
└── .github/
    └── workflows/
        └── broker_agent.yml
```

Easiest way — drag and drop files directly on GitHub, or use:
```bash
git clone https://github.com/Mrwave1995/ipmi-broker-agent.git
cd ipmi-broker-agent
# copy files in
git add .
git commit -m "Initial setup"
git push
```

### Step 3 — Add API keys as GitHub Secrets

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add these secrets:

| Secret name | Value |
|---|---|
| `SERPAPI_KEY_PRIMARY` | Your main SerpApi key |
| `SERPAPI_KEY_BACKUP` | Your second SerpApi key (optional) |

> Your keys are never exposed in logs or code — GitHub encrypts them.

### Step 4 — Enable GitHub Actions

1. Go to your repo → **Actions** tab
2. Click **Enable Actions** if prompted
3. You'll see the `IPMI Broker Discovery Agent` workflow listed

### Step 5 — Run it manually to test

1. Go to **Actions** → **IPMI Broker Discovery Agent**
2. Click **Run workflow** → **Run workflow**
3. Watch the logs in real time
4. When complete, click the run → **Artifacts** → download the CSV

---

## Downloading your leads

After each run:

1. Go to **Actions** tab in your repo
2. Click the latest run
3. Scroll down to **Artifacts**
4. Download `ipmi-broker-leads-[run number]`
5. Extract the ZIP — your CSV is inside

The CSV is sorted by IPMI score (highest first).

---

## CSV columns

| Column | Description |
|---|---|
| `country` | Target country |
| `region` | Region group |
| `priority` | high / medium / low |
| `broker_name` | Broker or company name |
| `website` | Website URL |
| `email` | Contact email (if found) |
| `phone` | Phone number (if found) |
| `description` | Short description from website |
| `ipmi_score` | Relevance score 0–100 |
| `ipmi_verdict` | 🟢 Strong / 🟡 Possible / 🟠 Weak / 🔴 Not IPMI |
| `scraped` | Whether website was successfully read |
| `run_date` | Date of this run |

---

## IPMI scoring explained

| Score | Label | Meaning |
|---|---|---|
| 60–100 | 🟢 Strong IPMI match | Mentions IPMI carriers, international health terms |
| 30–59 | 🟡 Possible IPMI broker | Health/expat signals but not confirmed |
| 10–29 | 🟠 Weak signal | Generic insurance broker |
| 0–9 | 🔴 Likely not IPMI | Domestic, motor, or property only |

Focus your outreach on 🟢 and 🟡 results first.

---

## Schedule

Runs every **Monday at 7:00 AM UAE time (03:00 UTC)**.

To change the schedule, edit `.github/workflows/broker_agent.yml`:
```yaml
- cron: "0 3 * * 1"   # Monday 03:00 UTC = 07:00 UAE
```

Cron format: `minute hour day month weekday`

---

## API call usage per run

| Region | Countries | Searches | Calls |
|---|---|---|---|
| Middle East | 7 | 2 each | 14 |
| South/SE Asia (ex-India) | 8 | 2 each | 16 |
| India | 1 | 1 | 1 |
| Small Europe | 10 | 2 each | 20 |
| LATAM | 10 | 2 each | 20 |
| **Total** | **36** | | **~71 calls** |

With 250 calls/month you get **3 full runs per month** comfortably.

---

## Upgrading to AI filtering (Phase 2)

When you get a Claude API key, the scoring can be upgraded from keyword-matching to actual AI reasoning — Claude reads each broker website and decides if they sell IPMI. This dramatically improves accuracy.

Add to GitHub Secrets:
```
ANTHROPIC_API_KEY = sk-ant-...
```

Then ask Claude to upgrade `broker_agent.py` with the AI filtering layer.

---

## Troubleshooting

**"No valid SerpApi key found"**
→ Check your GitHub Secrets are named exactly `SERPAPI_KEY_PRIMARY`

**"SerpApi error: Your account has run out of searches"**
→ Upgrade plan or wait for monthly renewal

**Low number of results for a country**
→ That country genuinely has fewer English-language broker websites — expected for LATAM and small Europe

**Website scraping fails for some leads**
→ Normal — some sites block scrapers. The snippet from Google search is still used for scoring.

---

## Support

Built by Claude (Anthropic) for Mrwave1995 — Now Health, Dubai.
For upgrades or modifications, paste this README into a new Claude conversation.
