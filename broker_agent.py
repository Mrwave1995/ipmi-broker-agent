"""
IPMI Broker Discovery Agent — v2
=================================
Multi-source intelligent broker discovery across 35 countries.

Sources (in priority order):
  1. EIOPA — EU insurance intermediary register (small Europe)
  2. Government regulator sites — Middle East licensed broker lists
  3. iPMI Global directory — industry-specific IPMI broker listings
  4. LinkedIn via SerpApi — company search by description
  5. Insurer partner pages — Cigna, AXA, Now Health, APRIL broker lists
  6. SerpApi supplementary — LATAM + gaps

Known brokers (116) are automatically excluded from results.
India excluded from government registry search.
"""

import os, csv, time, json, logging, re, requests
from datetime import datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

SERPAPI_KEY_PRIMARY = os.getenv("SERPAPI_KEY_PRIMARY", "")
SERPAPI_KEY_BACKUP  = os.getenv("SERPAPI_KEY_BACKUP", "")
OUTPUT_DIR          = os.getenv("OUTPUT_DIR", "docs/data")
LOG_DIR             = os.getenv("LOG_DIR", "logs")

REQUEST_TIMEOUT  = 15
SCRAPE_DELAY     = 1.5
SERPAPI_DELAY    = 2.0

# ─────────────────────────────────────────────
# KNOWN BROKERS — EXCLUSION LIST (116 brokers)
# ─────────────────────────────────────────────

KNOWN_BROKERS = {b.lower().strip() for b in [
    "MIC Global Risks Insurance Brokers Ltd", "Pacific Prime Insurance Brokers Limited",
    "ASN AG Advisory Services Network AG", "Now Health Direct 001", "Mordehay Bashkin",
    "Global Albatross", "Interbrok SARL", "WinHealth Group SA",
    "AG Services Consulting Co Ltd", "Infinity Financial Solutions Ltd Malaysia",
    "Cogent International Limited", "SIP Switzerland AG", "Infinity General Insurance Plc",
    "Charles Monat Associates Ltd", "IBH Levant and Africa SAL Insurance Broker",
    "Insure and Secure Insurance Brokerage", "Abacare Hong Kong Limited",
    "Arab Assurance Advisors", "Village Holdings Limited", "Nassif Assurances SARL",
    "Synergy Financial SARL", "Fenchurch Faris Ltd", "Tygate Limited",
    "International Citizens Group Inc", "S2 Insurance Brokers SA",
    "Taylor Brunswick Group Limited", "Continental Financial Services LTD",
    "International Risk Management Group",
    "Marsh Sigorta Reasurans Brokerligi Anonim Sirketi", "Clema Risk Solutions",
    "Diot Siaci Asia Pte Ltd", "Insoom Gmbh", "Himark Insurance Group Limited",
    "TAG Wealth International Pty Ltd", "Wecare Insurance Broker Ltd",
    "Bekhazi Insurance Brokers", "Price Forbes and Partners",
    "PT Sompo Insurance Indonesia", "Professional Insurance Consultants sarl",
    "CCW Global Limited", "Melbourne Insurance Brokers Limited",
    "Interactive Insurance Brokers LLC", "Seven Investments Limited",
    "Now Health Direct 051", "Howden Employee Benefits Wellbeing Limited",
    "Sara Insurance Brokers Limited", "Now Health Direct 084", "MyBroker Inc SARL",
    "Calibrated Capital INC", "Hampton Bridge Ltd", "DFHE Advisors",
    "Expatmedicare SAS", "Medibroker", "UK Health Insurance", "New State",
    "Holborn Labuan Limited", "AOC Insurance Broker LF Finance", "PT AsiaLife Invest",
    "Holborn Assets LLC", "Lioner International Consultancy Limited",
    "BIG Insurance Brokers SRL", "Opus Re Ltd", "Swiss Sure Co Ltd",
    "International Planning Group Insurance Brokers Ltd",
    "TFG Global Insurance Solutions Ltd", "United Insurance Brokers Dubai LLC",
    "Clarity Employee Benefits Pty Ltd", "Manchester Insurance Consultants Ltd",
    "CA Robinson Interest LLC", "Ample Financial and Insurance Services Limited",
    "AA Insurance Brokers", "NetBrokrs Insurtech Group",
    "Fidelity Arabia Insurance Brokers", "LA Guard Insurance Brokers",
    "First National Insurance Brokers Limited", "LawtonAsia Insurance Brokers",
    "Guardian Insurance Brokers Pvt Ltd", "MP Insurance Brokers Sdn Bhd",
    "Strategic Insurance Brokers", "Unilight Insurance Brokers Private Limited",
    "Lambert Brothers Insurance Broker Thailand",
    "LENG Somaly Treasurer Provita Insurance Broker", "BSI Insurance Broker Limited",
    "TIS Vietnam Insurance Broker", "Siam Cosmos Services Co Ltd", "Coreharbour",
    "Vienna Insurance Group VIG", "ZBK Balkann Insurance Broker",
    "Ultravinsurance Brokers", "GPA Holding IRAO", "Uniqa Group", "Grawe Group",
    "Liga Insurance", "Malakut Insurance Brokers", "Prioge Insurance Georgia",
    "Moi Insurance Broker", "Central Asia Insurance Brokers CAIB",
    "Houghton Street Consulting Vietnam",
    "Capstone Asia George Steuart Insurance Brokers", "Indochine Insurance Brokers",
    "Ceynergy Insurance Brokers Sri Lanka", "Essajee Carimjee Insurance Brokers",
    "Libra Insurance Brokers", "Blue Pacific Insurance Brokers", "Aexpat Insurance",
    "Integrated Health Insurance", "Lacson and Lacson", "Omni Insurance Brokers",
    "Monopolisigorta", "TT Insurance Broker", "Affinitas", "Responsivebrokers",
    "Elite Insurance Brokers Cambodia PLC", "Lockton IBS Insurance Brokers",
    "Alpha Insurance Brokers", "Global Insurance Brokers",
]}

def is_known(name: str) -> bool:
    """Check if broker is already in our known list."""
    return name.lower().strip() in KNOWN_BROKERS

# ─────────────────────────────────────────────
# COUNTRY CONFIG
# ─────────────────────────────────────────────

COUNTRIES = {
    # Middle East
    "Oman":        {"region": "Middle East", "priority": "high"},
    "Saudi Arabia":{"region": "Middle East", "priority": "high"},
    "Kuwait":      {"region": "Middle East", "priority": "high"},
    "Bahrain":     {"region": "Middle East", "priority": "high"},
    "Qatar":       {"region": "Middle East", "priority": "high"},
    "Jordan":      {"region": "Middle East", "priority": "high"},
    "Lebanon":     {"region": "Middle East", "priority": "high"},
    # South/SE Asia (India excluded from gov registry, low priority)
    "Sri Lanka":   {"region": "South/SE Asia", "priority": "high"},
    "Pakistan":    {"region": "South/SE Asia", "priority": "high"},
    "Bangladesh":  {"region": "South/SE Asia", "priority": "medium"},
    "Nepal":       {"region": "South/SE Asia", "priority": "medium"},
    "Vietnam":     {"region": "South/SE Asia", "priority": "high"},
    "Thailand":    {"region": "South/SE Asia", "priority": "high"},
    "Philippines": {"region": "South/SE Asia", "priority": "high"},
    "Malaysia":    {"region": "South/SE Asia", "priority": "high"},
    "India":       {"region": "South/SE Asia", "priority": "low"},
    # Small Europe
    "Luxembourg":  {"region": "Small Europe",  "priority": "high"},
    "Slovenia":    {"region": "Small Europe",  "priority": "medium"},
    "Croatia":     {"region": "Small Europe",  "priority": "medium"},
    "Estonia":     {"region": "Small Europe",  "priority": "medium"},
    "Latvia":      {"region": "Small Europe",  "priority": "medium"},
    "Lithuania":   {"region": "Small Europe",  "priority": "medium"},
    "Cyprus":      {"region": "Small Europe",  "priority": "high"},
    "Iceland":     {"region": "Small Europe",  "priority": "medium"},
    "Montenegro":  {"region": "Small Europe",  "priority": "medium"},
    "Albania":     {"region": "Small Europe",  "priority": "low"},
    # LATAM
    "Panama":          {"region": "LATAM", "priority": "high"},
    "Costa Rica":      {"region": "LATAM", "priority": "high"},
    "Uruguay":         {"region": "LATAM", "priority": "medium"},
    "Paraguay":        {"region": "LATAM", "priority": "low"},
    "Bolivia":         {"region": "LATAM", "priority": "low"},
    "Ecuador":         {"region": "LATAM", "priority": "medium"},
    "Guatemala":       {"region": "LATAM", "priority": "medium"},
    "Honduras":        {"region": "LATAM", "priority": "low"},
    "El Salvador":     {"region": "LATAM", "priority": "low"},
    "Dominican Republic": {"region": "LATAM", "priority": "medium"},
}

# ─────────────────────────────────────────────
# HTTP HELPERS
# ─────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def fetch(url: str, timeout: int = REQUEST_TIMEOUT) -> BeautifulSoup | None:
    """Fetch a URL and return BeautifulSoup object."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "lxml")
        logging.warning(f"HTTP {r.status_code} for {url}")
    except Exception as e:
        logging.warning(f"Fetch failed {url}: {e}")
    return None

def get_api_key() -> str:
    """Return first valid SerpApi key."""
    for key in [SERPAPI_KEY_PRIMARY, SERPAPI_KEY_BACKUP]:
        if key and len(key) > 10:
            return key
    raise ValueError("No valid SerpApi key found.")

# ─────────────────────────────────────────────
# SOURCE 1 — EIOPA (EU broker register)
# ─────────────────────────────────────────────

EIOPA_COUNTRY_CODES = {
    "Luxembourg": "LU", "Slovenia": "SI", "Croatia": "HR",
    "Estonia": "EE", "Latvia": "LV", "Lithuania": "LT",
    "Cyprus": "CY", "Iceland": "IS",
}

def scrape_eiopa(country: str) -> list[dict]:
    """Scrape EIOPA EU intermediary register for a country."""
    code = EIOPA_COUNTRY_CODES.get(country)
    if not code:
        return []

    results = []
    # EIOPA search URL for insurance intermediaries by home country
    url = f"https://register.eiopa.europa.eu/RACR/eiopa-register/insurance-intermediary?homeCountry={code}&pageSize=50"
    soup = fetch(url)
    if not soup:
        return []

    # Parse table rows
    rows = soup.find_all("tr")
    for row in rows[1:]:  # skip header
        cells = row.find_all("td")
        if len(cells) >= 2:
            name = cells[0].get_text(strip=True)
            if name and not is_known(name):
                results.append({
                    "broker_name": name,
                    "country": country,
                    "source": "EIOPA Register",
                    "website": "",
                    "email": "",
                    "phone": "",
                    "description": f"Licensed insurance intermediary registered with EIOPA — {country}",
                })
    logging.info(f"  EIOPA → {len(results)} new brokers for {country}")
    return results

# ─────────────────────────────────────────────
# SOURCE 2 — Middle East government regulators
# ─────────────────────────────────────────────

REGULATOR_URLS = {
    "Oman":    "https://fsa.gov.om/Home/AuthorizedAndAccredited?companyType=10",
    "Bahrain": "https://www.cbb.gov.bh/insurance-brokers/",
    "Qatar":   "https://www.qfcra.com/public_registers/authorised-insurance-firms/",
}

GAIF_COUNTRY_MAP = {
    "Kuwait":       "State of Kuwait",
    "Saudi Arabia": "Kingdom Of Saudi Arabia",
    "Jordan":       "The Hashemite Kingdom of Jordan",
    "Lebanon":      "Republic of Lebanon",
}

def scrape_regulator(country: str) -> list[dict]:
    """Scrape government regulator site for licensed brokers."""
    results = []

    # Direct regulator URLs
    if country in REGULATOR_URLS:
        soup = fetch(REGULATOR_URLS[country])
        if soup:
            # Look for broker names in tables or lists
            for tag in soup.find_all(["td", "li", "h3", "h4"]):
                text = tag.get_text(strip=True)
                if (len(text) > 5 and len(text) < 100
                        and not text.isdigit()
                        and "insurance" not in text.lower()[:3]):
                    if not is_known(text):
                        results.append({
                            "broker_name": text,
                            "country": country,
                            "source": f"Gov Regulator — {country}",
                            "website": "",
                            "email": "",
                            "phone": "",
                            "description": f"Licensed insurance broker per {country} financial regulator",
                        })
        time.sleep(SCRAPE_DELAY)

    # GAIF directory for remaining Middle East countries
    elif country in GAIF_COUNTRY_MAP:
        gaif_country = GAIF_COUNTRY_MAP[country]
        url = f"https://www.gaif.org/FE/Guide?directoryYear=2024&country={gaif_country.replace(' ', '+')}"
        soup = fetch(url)
        if soup:
            for tag in soup.find_all(["td", "h3", "h4", "strong"]):
                text = tag.get_text(strip=True)
                if (len(text) > 5 and len(text) < 120
                        and not text.isdigit()):
                    if not is_known(text):
                        results.append({
                            "broker_name": text,
                            "country": country,
                            "source": "GAIF Arab Insurance Directory",
                            "website": "",
                            "email": "",
                            "phone": "",
                            "description": f"Listed in GAIF Arab Insurance Directory — {country}",
                        })
        time.sleep(SCRAPE_DELAY)

    logging.info(f"  Regulator → {len(results)} entries for {country}")
    return results

# ─────────────────────────────────────────────
# SOURCE 3 — iPMI Global directory
# ─────────────────────────────────────────────

def scrape_ipmi_global() -> list[dict]:
    """Scrape iPMI Global broker directory."""
    results = []
    urls = [
        "https://ipmiglobal.com/provider-network",
        "https://ipmiglobal.com/provider-network/network-directory",
    ]

    for url in urls:
        soup = fetch(url)
        if not soup:
            continue

        for tag in soup.find_all(["h2", "h3", "h4", "strong", "a"]):
            text = tag.get_text(strip=True)
            link = tag.get("href", "") if tag.name == "a" else ""
            if (len(text) > 5 and len(text) < 120
                    and not text.startswith("http")
                    and not is_known(text)):
                results.append({
                    "broker_name": text,
                    "country": "Global",
                    "source": "iPMI Global Directory",
                    "website": link,
                    "email": "",
                    "phone": "",
                    "description": "Listed in iPMI Global industry directory",
                })
        time.sleep(SCRAPE_DELAY)

    # Deduplicate
    seen = set()
    unique = []
    for r in results:
        if r["broker_name"] not in seen:
            seen.add(r["broker_name"])
            unique.append(r)

    logging.info(f"  iPMI Global → {len(unique)} entries")
    return unique

# ─────────────────────────────────────────────
# SOURCE 4 — LinkedIn via SerpApi
# ─────────────────────────────────────────────

# Countries to skip LinkedIn search (covered well by regulators)
SKIP_LINKEDIN = {"India"}

def search_linkedin(country: str, api_key: str) -> list[dict]:
    """Search LinkedIn company pages for IPMI brokers in a country."""
    if country in SKIP_LINKEDIN:
        return []

    query = (
        f'site:linkedin.com/company '
        f'"insurance broker" "international health" "{country}"'
    )

    params = {
        "q": query,
        "api_key": api_key,
        "num": 10,
        "hl": "en",
        "gl": "us",
    }

    results = []
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=15)
        data = r.json()

        if "error" in data:
            logging.error(f"SerpApi error: {data['error']}")
            return []

        for item in data.get("organic_results", []):
            name = item.get("title", "").replace("| LinkedIn", "").strip()
            url  = item.get("link", "")
            snippet = item.get("snippet", "")

            # Clean up LinkedIn title patterns
            name = re.sub(r'\s*\|.*$', '', name).strip()
            name = re.sub(r'\s*-\s*LinkedIn$', '', name).strip()

            if name and not is_known(name) and "linkedin.com/company" in url:
                results.append({
                    "broker_name": name,
                    "country": country,
                    "source": "LinkedIn Search",
                    "website": url,
                    "email": "",
                    "phone": "",
                    "description": snippet[:200],
                })

    except Exception as e:
        logging.error(f"LinkedIn search failed for {country}: {e}")

    logging.info(f"  LinkedIn → {len(results)} results for {country}")
    return results

# ─────────────────────────────────────────────
# SOURCE 5 — Insurer partner/broker pages
# ─────────────────────────────────────────────

INSURER_PAGES = [
    {
        "name": "Now Health Broker Page",
        "url": "https://www.nowhealth.com/en/broker",
    },
    {
        "name": "APRIL International Broker",
        "url": "https://www.april-international.com/en/brokers",
    },
    {
        "name": "AXA Global Healthcare Broker",
        "url": "https://www.axaglobalhealthcare.com/en/intermediaries/",
    },
    {
        "name": "Allianz Care Broker",
        "url": "https://www.allianzcare.com/en/partners/brokers.html",
    },
]

def scrape_insurer_pages() -> list[dict]:
    """Scrape insurer broker partner pages for named broker lists."""
    results = []

    for insurer in INSURER_PAGES:
        soup = fetch(insurer["url"])
        if not soup:
            continue

        # Look for broker names — usually in lists, tables, or cards
        for tag in soup.find_all(["h2", "h3", "h4", "li", "strong", "td"]):
            text = tag.get_text(strip=True)
            if (len(text) > 5 and len(text) < 100
                    and not is_known(text)
                    and not any(skip in text.lower() for skip in [
                        "read more", "contact", "click", "learn", "find",
                        "search", "home", "about", "news"
                    ])):
                results.append({
                    "broker_name": text,
                    "country": "Global",
                    "source": insurer["name"],
                    "website": "",
                    "email": "",
                    "phone": "",
                    "description": f"Listed on {insurer['name']} broker partner page",
                })

        logging.info(f"  {insurer['name']} → scraped")
        time.sleep(SCRAPE_DELAY)

    # Deduplicate
    seen = set()
    unique = []
    for r in results:
        if r["broker_name"] not in seen:
            seen.add(r["broker_name"])
            unique.append(r)

    return unique

# ─────────────────────────────────────────────
# SOURCE 6 — SerpApi supplementary (LATAM + gaps)
# ─────────────────────────────────────────────

LATAM_COUNTRIES = {
    "Panama", "Costa Rica", "Uruguay", "Paraguay",
    "Bolivia", "Ecuador", "Guatemala", "Honduras",
    "El Salvador", "Dominican Republic",
}

def search_supplementary(country: str, api_key: str) -> list[dict]:
    """Supplementary SerpApi search for LATAM and ungapped countries."""
    if country not in LATAM_COUNTRIES:
        return []

    # Spanish + English queries for LATAM
    queries = [
        f'"seguro de salud internacional" broker "{country}"',
        f'"international health insurance" broker "{country}" expat',
    ]

    results = []
    for query in queries:
        params = {
            "q": query,
            "api_key": api_key,
            "num": 10,
            "hl": "es" if "seguro" in query else "en",
            "gl": "us",
        }
        try:
            r = requests.get("https://serpapi.com/search", params=params, timeout=15)
            data = r.json()

            for item in data.get("organic_results", []):
                name    = item.get("title", "").strip()
                url     = item.get("link", "")
                snippet = item.get("snippet", "")

                if name and not is_known(name):
                    results.append({
                        "broker_name": name,
                        "country": country,
                        "source": "SerpApi Supplementary",
                        "website": url,
                        "email": "",
                        "phone": "",
                        "description": snippet[:200],
                    })
            time.sleep(SERPAPI_DELAY)

        except Exception as e:
            logging.error(f"Supplementary search failed {country}: {e}")

    logging.info(f"  Supplementary → {len(results)} results for {country}")
    return results

# ─────────────────────────────────────────────
# WEBSITE ENRICHMENT
# ─────────────────────────────────────────────

def enrich_website(lead: dict) -> dict:
    """Try to find website and contact details for a broker."""
    # If we already have a LinkedIn URL, use it as website
    if lead.get("website") and "linkedin.com" in lead["website"]:
        return lead  # LinkedIn is useful as-is

    # If no website yet, try a quick Google search for the broker name
    if not lead.get("website") and lead.get("broker_name"):
        # We don't use SerpApi here to save calls — just flag for manual lookup
        lead["website"] = ""

    return lead

# ─────────────────────────────────────────────
# IPMI RELEVANCE SCORING
# ─────────────────────────────────────────────

STRONG_SIGNALS = [
    "international health insurance", "international medical insurance",
    "ipmi", "expat health", "global health insurance", "worldwide health",
    "international private medical", "cigna global", "aetna international",
    "allianz care", "axa global healthcare", "bupa global", "now health",
    "april international", "expatriate insurance", "globally mobile",
    "expat insurance", "international medical", "international coverage",
    "employee benefits international", "global medical",
]

def score_lead(lead: dict) -> tuple[int, str]:
    """Score a lead for IPMI relevance based on source and description."""
    text = " ".join([
        lead.get("description", ""),
        lead.get("broker_name", ""),
        lead.get("source", ""),
    ]).lower()

    score = 0
    matched = []

    # Source-based base scores — these are already pre-filtered
    source = lead.get("source", "")
    if "EIOPA" in source:          score += 40  # Licensed EU intermediary
    if "Gov Regulator" in source:  score += 40  # Licensed in country
    if "GAIF" in source:           score += 35  # Arab insurance directory
    if "iPMI Global" in source:    score += 60  # IPMI-specific directory
    if "Insurer" in source or "Now Health" in source or "APRIL" in source or "AXA" in source:
        score += 70  # Listed by IPMI insurer directly
    if "LinkedIn" in source:       score += 20  # Needs text confirmation
    if "Supplementary" in source:  score += 10  # Generic search — lowest trust

    # Content signals (boost)
    for signal in STRONG_SIGNALS:
        if signal in text:
            score += 15
            matched.append(signal)
            if score >= 90:
                break

    score = min(100, score)

    if score >= 60:   label = "🟢 Strong IPMI match"
    elif score >= 35: label = "🟡 Possible IPMI broker"
    elif score >= 15: label = "🟠 Weak signal"
    else:             label = "🔴 Unlikely IPMI"

    reason = f"{label} — source: {source}"
    if matched:
        reason += f" | signals: {', '.join(matched[:2])}"

    return score, reason

# ─────────────────────────────────────────────
# DEDUPLICATION
# ─────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Normalize broker name for deduplication."""
    name = name.lower().strip()
    for suffix in [" ltd", " limited", " llc", " sarl", " sa", " plc",
                   " inc", " gmbh", " srl", " ag", " bv", " pte"]:
        name = name.replace(suffix, "")
    name = re.sub(r'\s+', ' ', name)
    return name.strip()

# ─────────────────────────────────────────────
# MAIN AGENT
# ─────────────────────────────────────────────

def run_agent():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    log_file = os.path.join(
        LOG_DIR, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ]
    )

    logging.info("=" * 60)
    logging.info("IPMI BROKER AGENT v2 — Starting run")
    logging.info(f"Countries: {len(COUNTRIES)} | Known exclusions: {len(KNOWN_BROKERS)}")
    logging.info("=" * 60)

    # Get SerpApi key
    try:
        api_key = get_api_key()
        logging.info("SerpApi key loaded ✓")
    except ValueError as e:
        logging.error(str(e))
        return

    all_leads     = []
    seen_names    = set()
    serpapi_calls = 0

    # ── Source 3: iPMI Global (run once, global) ──
    logging.info("\n[SOURCE] iPMI Global Directory")
    ipmi_leads = scrape_ipmi_global()
    for lead in ipmi_leads:
        norm = normalize_name(lead["broker_name"])
        if norm not in seen_names:
            seen_names.add(norm)
            all_leads.append(lead)

    # ── Source 5: Insurer partner pages (run once, global) ──
    logging.info("\n[SOURCE] Insurer Partner Pages")
    insurer_leads = scrape_insurer_pages()
    for lead in insurer_leads:
        norm = normalize_name(lead["broker_name"])
        if norm not in seen_names:
            seen_names.add(norm)
            all_leads.append(lead)

    # ── Per-country sources ──
    for country, config in COUNTRIES.items():
        region   = config["region"]
        priority = config["priority"]
        logging.info(f"\n── {country} ({region}, {priority}) ──")

        country_leads = []

        # Source 1: EIOPA (small Europe)
        if region == "Small Europe" and country in EIOPA_COUNTRY_CODES:
            country_leads += scrape_eiopa(country)
            time.sleep(SCRAPE_DELAY)

        # Source 2: Government regulators (Middle East, skip India)
        if region == "Middle East":
            country_leads += scrape_regulator(country)

        # Source 4: LinkedIn via SerpApi
        if priority in ["high", "medium"] and country != "India":
            country_leads += search_linkedin(country, api_key)
            serpapi_calls += 1
            time.sleep(SERPAPI_DELAY)

        # Source 6: Supplementary SerpApi (LATAM)
        if region == "LATAM":
            country_leads += search_supplementary(country, api_key)
            serpapi_calls += 2
            time.sleep(SERPAPI_DELAY)

        # Deduplicate and add
        for lead in country_leads:
            norm = normalize_name(lead["broker_name"])
            if norm and norm not in seen_names and not is_known(lead["broker_name"]):
                seen_names.add(norm)
                lead = enrich_website(lead)
                all_leads.append(lead)

    # ── Score all leads ──
    logging.info("\n[SCORING] Scoring all leads...")
    for lead in all_leads:
        score, verdict = score_lead(lead)
        lead["ipmi_score"]   = score
        lead["ipmi_verdict"] = verdict
        lead["run_date"]     = datetime.now().strftime("%Y-%m-%d")
        # Ensure country/region fields
        if "region" not in lead:
            lead["region"] = COUNTRIES.get(lead.get("country", ""), {}).get("region", "Global")
        if "priority" not in lead:
            lead["priority"] = COUNTRIES.get(lead.get("country", ""), {}).get("priority", "medium")

    # ── Save CSV ──
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = os.path.join(OUTPUT_DIR, f"ipmi_brokers_{timestamp}.csv")

    fieldnames = [
        "country", "region", "priority", "broker_name",
        "website", "email", "phone", "description",
        "ipmi_score", "ipmi_verdict", "source", "run_date",
    ]

    sorted_leads = sorted(all_leads, key=lambda x: x.get("ipmi_score", 0), reverse=True)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted_leads)

    # ── Save JSON for dashboard ──
    json_path = os.path.join(OUTPUT_DIR, "latest.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(sorted_leads, f, ensure_ascii=False, indent=2)

    # ── Summary ──
    strong   = [r for r in all_leads if r.get("ipmi_score", 0) >= 60]
    possible = [r for r in all_leads if 35 <= r.get("ipmi_score", 0) < 60]
    weak     = [r for r in all_leads if r.get("ipmi_score", 0) < 35]

    logging.info("\n" + "=" * 60)
    logging.info("RUN COMPLETE")
    logging.info(f"Total new leads      : {len(all_leads)}")
    logging.info(f"🟢 Strong IPMI       : {len(strong)}")
    logging.info(f"🟡 Possible          : {len(possible)}")
    logging.info(f"🔴 Weak/other        : {len(weak)}")
    logging.info(f"SerpApi calls used   : {serpapi_calls}")
    logging.info(f"CSV saved            : {csv_path}")
    logging.info(f"Dashboard JSON       : {json_path}")
    logging.info("=" * 60)

    # Save summary for GitHub Actions
    summary = {
        "run_date":      datetime.now().isoformat(),
        "total_leads":   len(all_leads),
        "strong":        len(strong),
        "possible":      len(possible),
        "weak":          len(weak),
        "serpapi_calls": serpapi_calls,
        "csv_file":      csv_path,
    }
    with open(os.path.join(OUTPUT_DIR, "latest_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n✅ Done! {len(all_leads)} new leads | {len(strong)} strong | {serpapi_calls} API calls")

if __name__ == "__main__":
    run_agent()
