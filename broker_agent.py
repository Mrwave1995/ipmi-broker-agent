"""
IPMI Broker Discovery Agent
===========================
Searches for international health insurance brokers across 36 target countries.
Uses SerpApi for Google search + keyword scoring for IPMI relevance.
Exports results to CSV with weekly scheduling via GitHub Actions.

Author: Built for Mrwave1995
"""

import os
import csv
import time
import json
import logging
import requests
from datetime import datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

# API Keys — set as GitHub Secrets or environment variables
SERPAPI_KEY_PRIMARY   = os.getenv("SERPAPI_KEY_PRIMARY", "YOUR_PRIMARY_SERPAPI_KEY")
SERPAPI_KEY_BACKUP    = os.getenv("SERPAPI_KEY_BACKUP", "YOUR_BACKUP_SERPAPI_KEY")

OUTPUT_DIR  = os.getenv("OUTPUT_DIR", "output")
LOG_DIR     = os.getenv("LOG_DIR", "logs")

# Search settings
RESULTS_PER_SEARCH  = 10   # Google results per query
DELAY_BETWEEN_CALLS = 2    # Seconds between SerpApi calls (be polite)
REQUEST_TIMEOUT     = 10   # Seconds for website scraping

# ─────────────────────────────────────────────
# TARGET COUNTRIES
# ─────────────────────────────────────────────

COUNTRIES = {

    # ── Middle East ──────────────────────────
    "Oman":     {"region": "Middle East",       "priority": "high",   "searches": 2, "lang": "en"},
    "Saudi Arabia": {"region": "Middle East",   "priority": "high",   "searches": 2, "lang": "en"},
    "Kuwait":   {"region": "Middle East",       "priority": "high",   "searches": 2, "lang": "en"},
    "Bahrain":  {"region": "Middle East",       "priority": "high",   "searches": 2, "lang": "en"},
    "Qatar":    {"region": "Middle East",       "priority": "high",   "searches": 2, "lang": "en"},
    "Jordan":   {"region": "Middle East",       "priority": "high",   "searches": 2, "lang": "en"},
    "Lebanon":  {"region": "Middle East",       "priority": "high",   "searches": 2, "lang": "en"},

    # ── South & Southeast Asia ───────────────
    "Sri Lanka":    {"region": "South/SE Asia", "priority": "high",   "searches": 2, "lang": "en"},
    "Pakistan":     {"region": "South/SE Asia", "priority": "high",   "searches": 2, "lang": "en"},
    "Bangladesh":   {"region": "South/SE Asia", "priority": "medium", "searches": 2, "lang": "en"},
    "Nepal":        {"region": "South/SE Asia", "priority": "medium", "searches": 2, "lang": "en"},
    "Vietnam":      {"region": "South/SE Asia", "priority": "high",   "searches": 2, "lang": "en"},
    "Thailand":     {"region": "South/SE Asia", "priority": "high",   "searches": 2, "lang": "en"},
    "Philippines":  {"region": "South/SE Asia", "priority": "high",   "searches": 2, "lang": "en"},
    "Malaysia":     {"region": "South/SE Asia", "priority": "high",   "searches": 2, "lang": "en"},
    "India":        {"region": "South/SE Asia", "priority": "low",    "searches": 1, "lang": "en"},  # Limited IPMI market

    # ── Small Europe ─────────────────────────
    "Luxembourg":   {"region": "Small Europe",  "priority": "high",   "searches": 2, "lang": "en"},
    "Slovenia":     {"region": "Small Europe",  "priority": "medium", "searches": 2, "lang": "en"},
    "Croatia":      {"region": "Small Europe",  "priority": "medium", "searches": 2, "lang": "en"},
    "Estonia":      {"region": "Small Europe",  "priority": "medium", "searches": 2, "lang": "en"},
    "Latvia":       {"region": "Small Europe",  "priority": "medium", "searches": 2, "lang": "en"},
    "Lithuania":    {"region": "Small Europe",  "priority": "medium", "searches": 2, "lang": "en"},
    "Cyprus":       {"region": "Small Europe",  "priority": "high",   "searches": 2, "lang": "en"},
    "Iceland":      {"region": "Small Europe",  "priority": "medium", "searches": 2, "lang": "en"},
    "Montenegro":   {"region": "Small Europe",  "priority": "medium", "searches": 2, "lang": "en"},
    "Albania":      {"region": "Small Europe",  "priority": "low",    "searches": 2, "lang": "en"},

    # ── LATAM (underserved) ──────────────────
    "Panama":           {"region": "LATAM",     "priority": "high",   "searches": 2, "lang": "en"},
    "Costa Rica":       {"region": "LATAM",     "priority": "high",   "searches": 2, "lang": "en"},
    "Uruguay":          {"region": "LATAM",     "priority": "medium", "searches": 2, "lang": "en"},
    "Paraguay":         {"region": "LATAM",     "priority": "low",    "searches": 2, "lang": "en"},
    "Bolivia":          {"region": "LATAM",     "priority": "low",    "searches": 2, "lang": "en"},
    "Ecuador":          {"region": "LATAM",     "priority": "medium", "searches": 2, "lang": "en"},
    "Guatemala":        {"region": "LATAM",     "priority": "medium", "searches": 2, "lang": "en"},
    "Honduras":         {"region": "LATAM",     "priority": "low",    "searches": 2, "lang": "en"},
    "El Salvador":      {"region": "LATAM",     "priority": "low",    "searches": 2, "lang": "en"},
    "Dominican Republic": {"region": "LATAM",   "priority": "medium", "searches": 2, "lang": "en"},
}

# ─────────────────────────────────────────────
# SEARCH QUERIES PER COUNTRY
# ─────────────────────────────────────────────

def build_queries(country: str, num_searches: int) -> list[str]:
    """Build targeted search queries for a country."""
    all_queries = [
        f'international health insurance broker "{country}"',
        f'expat health insurance broker "{country}" IPMI',
        f'global health insurance intermediary "{country}"',
        f'"{country}" insurance broker "Cigna" OR "Aetna" OR "Allianz" OR "AXA" OR "Bupa" international',
        f'"{country}" health insurance broker expat relocate',
    ]
    return all_queries[:num_searches]

# ─────────────────────────────────────────────
# IPMI RELEVANCE SCORING (keyword-based)
# ─────────────────────────────────────────────

STRONG_IPMI_SIGNALS = [
    "international health insurance", "international medical insurance",
    "ipmi", "expat health", "expat insurance", "global health insurance",
    "worldwide health", "international private medical",
    "cigna global", "aetna international", "allianz care",
    "axa global healthcare", "bupa global", "now health", "april international",
    "expatriate insurance", "global medical insurance",
]

WEAK_SIGNALS = [
    "health insurance", "medical insurance", "insurance broker",
    "employee benefits", "group health", "travel insurance",
    "life insurance", "relocation", "expatriate",
]

NEGATIVE_SIGNALS = [
    "domestic only", "local insurance", "national health",
    "car insurance only", "motor insurance only", "home insurance only",
    "auto insurance", "property insurance only",
]

def score_relevance(text: str) -> tuple[int, str]:
    """
    Score a broker's website text for IPMI relevance.
    Returns (score 0-100, reason string)
    """
    text_lower = text.lower()
    score = 0
    reasons = []

    # Strong signals: +20 each, max 60
    for signal in STRONG_IPMI_SIGNALS:
        if signal in text_lower:
            score += 20
            reasons.append(f"✓ '{signal}'")
            if score >= 60:
                break

    # Weak signals: +5 each, max 20
    weak_score = 0
    for signal in WEAK_SIGNALS:
        if signal in text_lower:
            weak_score += 5
            if weak_score >= 20:
                break
    score += weak_score

    # Negative signals: -15 each
    for signal in NEGATIVE_SIGNALS:
        if signal in text_lower:
            score -= 15
            reasons.append(f"✗ '{signal}'")

    score = max(0, min(100, score))

    if score >= 60:
        label = "🟢 Strong IPMI match"
    elif score >= 30:
        label = "🟡 Possible IPMI broker"
    elif score >= 10:
        label = "🟠 Weak signal"
    else:
        label = "🔴 Likely not IPMI"

    reason_str = " | ".join(reasons[:3]) if reasons else "No strong signals found"
    return score, f"{label} — {reason_str}"

# ─────────────────────────────────────────────
# WEBSITE SCRAPER
# ─────────────────────────────────────────────

def scrape_website(url: str) -> dict:
    """Scrape basic info from a broker website."""
    result = {
        "title": "",
        "description": "",
        "email": "",
        "phone": "",
        "body_text": "",
        "scraped": False,
    }

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return result

        soup = BeautifulSoup(resp.text, "html.parser")

        # Title
        result["title"] = soup.title.string.strip() if soup.title else ""

        # Meta description
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            result["description"] = meta.get("content", "")[:300]

        # Email (simple regex-free approach — look for mailto links)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("mailto:"):
                email = href.replace("mailto:", "").split("?")[0].strip()
                if email and "@" in email:
                    result["email"] = email
                    break

        # Phone (look for tel: links)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("tel:"):
                result["phone"] = href.replace("tel:", "").strip()
                break

        # Body text (first 1000 chars for scoring)
        body = soup.find("body")
        if body:
            text = body.get_text(separator=" ", strip=True)
            result["body_text"] = text[:1500]

        result["scraped"] = True

    except Exception as e:
        logging.warning(f"Could not scrape {url}: {e}")

    return result

# ─────────────────────────────────────────────
# SERPAPI SEARCH
# ─────────────────────────────────────────────

def get_active_key(primary: str, backup: str) -> tuple[str, str]:
    """Return the first valid API key."""
    for key, label in [(primary, "primary"), (backup, "backup")]:
        if key and key != "YOUR_PRIMARY_SERPAPI_KEY" and key != "YOUR_BACKUP_SERPAPI_KEY":
            return key, label
    raise ValueError("No valid SerpApi key found. Set SERPAPI_KEY_PRIMARY or SERPAPI_KEY_BACKUP.")

def search_brokers(query: str, api_key: str, country: str) -> list[dict]:
    """Run a single SerpApi search and return organic results."""
    params = {
        "q": query,
        "api_key": api_key,
        "num": RESULTS_PER_SEARCH,
        "hl": "en",
        "gl": "us",  # Use US results for English consistency
    }

    try:
        resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
        data = resp.json()

        if "error" in data:
            logging.error(f"SerpApi error: {data['error']}")
            return []

        results = []
        for r in data.get("organic_results", []):
            results.append({
                "name":    r.get("title", ""),
                "url":     r.get("link", ""),
                "snippet": r.get("snippet", ""),
            })
        return results

    except Exception as e:
        logging.error(f"Search failed for '{query}': {e}")
        return []

# ─────────────────────────────────────────────
# DEDUPLICATION
# ─────────────────────────────────────────────

def normalize_domain(url: str) -> str:
    """Extract root domain for deduplication."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        domain = domain.replace("www.", "")
        return domain
    except Exception:
        return url

# ─────────────────────────────────────────────
# MAIN AGENT LOOP
# ─────────────────────────────────────────────

def run_agent():
    """Main entry point — runs the full broker discovery pipeline."""

    # Setup logging
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    log_file = os.path.join(LOG_DIR, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ]
    )

    logging.info("=" * 60)
    logging.info("IPMI BROKER DISCOVERY AGENT — Starting run")
    logging.info(f"Target countries: {len(COUNTRIES)}")
    logging.info("=" * 60)

    # Get API key
    try:
        api_key, key_label = get_active_key(SERPAPI_KEY_PRIMARY, SERPAPI_KEY_BACKUP)
        logging.info(f"Using {key_label} SerpApi key")
    except ValueError as e:
        logging.error(str(e))
        return

    # Track seen domains to avoid duplicates
    seen_domains = set()
    all_leads = []
    total_searches = 0

    for country, config in COUNTRIES.items():
        region   = config["region"]
        priority = config["priority"]
        n_searches = config["searches"]

        logging.info(f"\n── {country} ({region}, priority: {priority}) ──")

        queries = build_queries(country, n_searches)
        country_results = []

        for query in queries:
            logging.info(f"  Searching: {query}")
            results = search_brokers(query, api_key, country)
            total_searches += 1

            for r in results:
                domain = normalize_domain(r["url"])
                if domain and domain not in seen_domains:
                    seen_domains.add(domain)
                    country_results.append(r)

            time.sleep(DELAY_BETWEEN_CALLS)

        logging.info(f"  Found {len(country_results)} unique leads — scraping websites...")

        for lead in country_results:
            site_data = scrape_website(lead["url"])

            # Combine snippet + scraped text for scoring
            combined_text = " ".join([
                lead.get("snippet", ""),
                site_data.get("description", ""),
                site_data.get("body_text", ""),
            ])

            score, reason = score_relevance(combined_text)

            row = {
                "country":      country,
                "region":       region,
                "priority":     priority,
                "broker_name":  site_data["title"] or lead["name"],
                "website":      lead["url"],
                "email":        site_data["email"],
                "phone":        site_data["phone"],
                "description":  site_data["description"] or lead["snippet"],
                "ipmi_score":   score,
                "ipmi_verdict": reason,
                "scraped":      site_data["scraped"],
                "run_date":     datetime.now().strftime("%Y-%m-%d"),
            }

            all_leads.append(row)
            logging.info(f"    [{score:>3}] {row['broker_name'][:50]} — {lead['url']}")

            time.sleep(0.5)  # Polite scraping delay

    # ── Save CSV ──────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = os.path.join(OUTPUT_DIR, f"ipmi_brokers_{timestamp}.csv")

    fieldnames = [
        "country", "region", "priority",
        "broker_name", "website", "email", "phone",
        "description", "ipmi_score", "ipmi_verdict",
        "scraped", "run_date",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        # Sort by score descending
        for row in sorted(all_leads, key=lambda x: x["ipmi_score"], reverse=True):
            writer.writerow(row)

    # ── Summary ───────────────────────────────
    strong   = [r for r in all_leads if r["ipmi_score"] >= 60]
    possible = [r for r in all_leads if 30 <= r["ipmi_score"] < 60]
    weak     = [r for r in all_leads if r["ipmi_score"] < 30]

    logging.info("\n" + "=" * 60)
    logging.info("RUN COMPLETE")
    logging.info(f"Total SerpApi calls used : {total_searches}")
    logging.info(f"Total leads found        : {len(all_leads)}")
    logging.info(f"🟢 Strong IPMI matches   : {len(strong)}")
    logging.info(f"🟡 Possible IPMI brokers : {len(possible)}")
    logging.info(f"🔴 Weak / not IPMI       : {len(weak)}")
    logging.info(f"CSV saved to             : {csv_path}")
    logging.info("=" * 60)

    # Save summary JSON for GitHub Actions badge/notification
    summary = {
        "run_date":      datetime.now().isoformat(),
        "total_leads":   len(all_leads),
        "strong_matches": len(strong),
        "possible":      len(possible),
        "weak":          len(weak),
        "searches_used": total_searches,
        "csv_file":      csv_path,
    }
    with open(os.path.join(OUTPUT_DIR, "latest_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n✅ Done! CSV saved: {csv_path}")
    print(f"   {len(strong)} strong IPMI leads | {len(possible)} possible | {total_searches} API calls used")

if __name__ == "__main__":
    run_agent()
