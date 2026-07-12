"""
IPMI Broker Discovery Agent — v3
=================================
Multi-source broker discovery with Claude AI filtering layer.

Sources:
  1. EIOPA — EU licensed intermediary register (small Europe)
  2. Government regulator sites — Middle East licensed broker lists
  3. iPMI Global directory — IPMI-specific listings
  4. LinkedIn via SerpApi — company search by description
  5. Insurer partner pages — Cigna, AXA, Now Health, APRIL
  6. SerpApi supplementary — LATAM

Claude AI filters every lead: reads description and judges
whether this is genuinely an IPMI broker. Eliminates noise.

Known brokers (116) auto-excluded from results.
India excluded from government registry search.
"""

import os, csv, time, json, logging, re, requests
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

SERPAPI_KEY_PRIMARY = os.getenv("SERPAPI_KEY_PRIMARY", "")
SERPAPI_KEY_BACKUP  = os.getenv("SERPAPI_KEY_BACKUP", "")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
OUTPUT_DIR          = os.getenv("OUTPUT_DIR", "docs/data")
LOG_DIR             = os.getenv("LOG_DIR", "logs")

REQUEST_TIMEOUT = 15
SCRAPE_DELAY    = 1.5
SERPAPI_DELAY   = 2.0
CLAUDE_DELAY    = 0.5
CLAUDE_MODEL    = "claude-haiku-4-5-20251001"

# ─────────────────────────────────────────────
# KNOWN BROKERS — EXCLUSION LIST
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
    return name.lower().strip() in KNOWN_BROKERS

# ─────────────────────────────────────────────
# COUNTRY CONFIG
# ─────────────────────────────────────────────

COUNTRIES = {
    "Oman":        {"region": "Middle East", "priority": "high"},
    "Saudi Arabia":{"region": "Middle East", "priority": "high"},
    "Kuwait":      {"region": "Middle East", "priority": "high"},
    "Bahrain":     {"region": "Middle East", "priority": "high"},
    "Qatar":       {"region": "Middle East", "priority": "high"},
    "Jordan":      {"region": "Middle East", "priority": "high"},
    "Lebanon":     {"region": "Middle East", "priority": "high"},
    "Sri Lanka":   {"region": "South/SE Asia", "priority": "high"},
    "Pakistan":    {"region": "South/SE Asia", "priority": "high"},
    "Bangladesh":  {"region": "South/SE Asia", "priority": "medium"},
    "Nepal":       {"region": "South/SE Asia", "priority": "medium"},
    "Vietnam":     {"region": "South/SE Asia", "priority": "high"},
    "Thailand":    {"region": "South/SE Asia", "priority": "high"},
    "Philippines": {"region": "South/SE Asia", "priority": "high"},
    "Malaysia":    {"region": "South/SE Asia", "priority": "high"},
    "India":       {"region": "South/SE Asia", "priority": "low"},
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

def fetch(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "lxml")
        logging.warning(f"HTTP {r.status_code} — {url}")
    except Exception as e:
        logging.warning(f"Fetch failed {url}: {e}")
    return None

def get_serpapi_key() -> str:
    for key in [SERPAPI_KEY_PRIMARY, SERPAPI_KEY_BACKUP]:
        if key and len(key) > 10:
            return key
    raise ValueError("No valid SerpApi key found.")

# ─────────────────────────────────────────────
# CLAUDE AI FILTERING LAYER
# ─────────────────────────────────────────────

def claude_filter(lead: dict) -> tuple[bool, int, str]:
    """
    Ask Claude: is this a genuine IPMI broker?
    Returns (keep: bool, score: int, reason: str)
    Falls back to keyword scoring if API key not set.
    """
    if not ANTHROPIC_API_KEY:
        return keyword_score(lead)

    name        = lead.get("broker_name", "")
    country     = lead.get("country", "")
    description = lead.get("description", "")[:400]
    source      = lead.get("source", "")
    website     = lead.get("website", "")

    prompt = f"""You are an expert in International Private Medical Insurance (IPMI).

Analyze this entry and determine if it is a genuine IPMI broker — a company that sells or distributes international health insurance to expatriates, globally mobile individuals, or multinational employees.

Entry details:
- Name: {name}
- Country: {country}
- Source: {source}
- Website: {website}
- Description: {description}

Answer in this exact JSON format only, no other text:
{{
  "is_ipmi_broker": true or false,
  "confidence": 0-100,
  "reason": "one sentence explanation"
}}

Rules:
- true = actively sells IPMI / international health / expat health insurance
- false = domestic insurer only, motor/property broker, article/journal, comparison site, regulator, hospital, or unrelated entity
- Be strict — when unsure, say false"""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 150,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )

        data = response.json()
        text = data["content"][0]["text"].strip()

        # Parse JSON response
        text = re.sub(r"```json|```", "", text).strip()
        result = json.loads(text)

        is_broker  = result.get("is_ipmi_broker", False)
        confidence = result.get("confidence", 0)
        reason     = result.get("reason", "")

        if is_broker:
            label = "🟢 Strong IPMI match" if confidence >= 70 else "🟡 Possible IPMI broker"
            verdict = f"{label} — {reason}"
            return True, confidence, verdict
        else:
            return False, confidence, f"🔴 Filtered out — {reason}"

    except Exception as e:
        logging.warning(f"Claude API error for {name}: {e} — falling back to keywords")
        return keyword_score(lead)

    finally:
        time.sleep(CLAUDE_DELAY)

def keyword_score(lead: dict) -> tuple[bool, int, str]:
    """Fallback keyword scoring if Claude API unavailable."""
    text = " ".join([
        lead.get("description", ""),
        lead.get("broker_name", ""),
        lead.get("source", ""),
    ]).lower()

    score = 0
    source = lead.get("source", "")

    if "iPMI Global" in source:   score += 70
    if "Insurer" in source:       score += 70
    if "Gov Regulator" in source: score += 40
    if "EIOPA" in source:         score += 40
    if "GAIF" in source:          score += 35
    if "LinkedIn" in source:      score += 20
    if "Supplementary" in source: score += 10

    signals = [
        "international health insurance", "ipmi", "expat health",
        "global health", "international medical", "expat insurance",
        "cigna", "aetna", "allianz care", "bupa global", "now health",
        "april international", "globally mobile", "expatriate",
    ]
    for s in signals:
        if s in text:
            score += 10

    score = min(100, score)
    keep  = score >= 35

    if score >= 60:   label = "🟢 Strong IPMI match"
    elif score >= 35: label = "🟡 Possible IPMI broker"
    else:             label = "🔴 Unlikely IPMI"

    return keep, score, f"{label} — keyword scoring (no Claude API)"

# ─────────────────────────────────────────────
# SOURCE 1 — EIOPA
# ─────────────────────────────────────────────

EIOPA_COUNTRY_CODES = {
    "Luxembourg": "LU", "Slovenia": "SI", "Croatia": "HR",
    "Estonia": "EE", "Latvia": "LV", "Lithuania": "LT",
    "Cyprus": "CY", "Iceland": "IS",
}

def scrape_eiopa(country: str) -> list[dict]:
    code = EIOPA_COUNTRY_CODES.get(country)
    if not code:
        return []
    results = []
    url = f"https://register.eiopa.europa.eu/RACR/eiopa-register/insurance-intermediary?homeCountry={code}&pageSize=50"
    soup = fetch(url)
    if not soup:
        return []
    for row in soup.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) >= 2:
            name = cells[0].get_text(strip=True)
            if name and not is_known(name):
                results.append({
                    "broker_name": name,
                    "country": country,
                    "source": "EIOPA Register",
                    "website": "", "email": "", "phone": "",
                    "description": f"Licensed insurance intermediary — {country} (EIOPA)",
                })
    logging.info(f"  EIOPA → {len(results)} entries for {country}")
    return results

# ─────────────────────────────────────────────
# SOURCE 2 — Government regulators
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
    results = []
    if country in REGULATOR_URLS:
        soup = fetch(REGULATOR_URLS[country])
        if soup:
            for tag in soup.find_all(["td", "li", "h3", "h4"]):
                text = tag.get_text(strip=True)
                if 5 < len(text) < 100 and not text.isdigit() and not is_known(text):
                    results.append({
                        "broker_name": text,
                        "country": country,
                        "source": f"Gov Regulator — {country}",
                        "website": "", "email": "", "phone": "",
                        "description": f"Licensed insurance broker — {country} financial regulator",
                    })
        time.sleep(SCRAPE_DELAY)

    elif country in GAIF_COUNTRY_MAP:
        gaif_name = GAIF_COUNTRY_MAP[country]
        url = f"https://www.gaif.org/FE/Guide?directoryYear=2024&country={gaif_name.replace(' ', '+')}"
        soup = fetch(url)
        if soup:
            for tag in soup.find_all(["td", "h3", "h4", "strong"]):
                text = tag.get_text(strip=True)
                if 5 < len(text) < 120 and not text.isdigit() and not is_known(text):
                    results.append({
                        "broker_name": text,
                        "country": country,
                        "source": "GAIF Arab Insurance Directory",
                        "website": "", "email": "", "phone": "",
                        "description": f"Listed in GAIF Arab Insurance Directory — {country}",
                    })
        time.sleep(SCRAPE_DELAY)

    logging.info(f"  Regulator → {len(results)} entries for {country}")
    return results

# ─────────────────────────────────────────────
# SOURCE 3 — iPMI Global
# ─────────────────────────────────────────────

def scrape_ipmi_global() -> list[dict]:
    results = []
    for url in [
        "https://ipmiglobal.com/provider-network",
        "https://ipmiglobal.com/provider-network/network-directory",
    ]:
        soup = fetch(url)
        if not soup:
            continue
        for tag in soup.find_all(["h2", "h3", "h4", "strong", "a"]):
            text = tag.get_text(strip=True)
            link = tag.get("href", "") if tag.name == "a" else ""
            if 5 < len(text) < 120 and not text.startswith("http") and not is_known(text):
                results.append({
                    "broker_name": text,
                    "country": "Global",
                    "source": "iPMI Global Directory",
                    "website": link, "email": "", "phone": "",
                    "description": "Listed in iPMI Global industry directory",
                })
        time.sleep(SCRAPE_DELAY)

    seen, unique = set(), []
    for r in results:
        if r["broker_name"] not in seen:
            seen.add(r["broker_name"])
            unique.append(r)
    logging.info(f"  iPMI Global → {len(unique)} entries")
    return unique

# ─────────────────────────────────────────────
# SOURCE 4 — LinkedIn via SerpApi
# ─────────────────────────────────────────────

def search_linkedin(country: str, api_key: str) -> list[dict]:
    if country == "India":
        return []
    query = f'site:linkedin.com/company "insurance broker" "international health" "{country}"'
    params = {"q": query, "api_key": api_key, "num": 10, "hl": "en", "gl": "us"}
    results = []
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=15)
        data = r.json()
        if "error" in data:
            logging.error(f"SerpApi: {data['error']}")
            return []
        for item in data.get("organic_results", []):
            name    = re.sub(r'\s*\|.*$', '', item.get("title", "")).strip()
            name    = re.sub(r'\s*-\s*LinkedIn$', '', name).strip()
            url     = item.get("link", "")
            snippet = item.get("snippet", "")
            if name and not is_known(name) and "linkedin.com/company" in url:
                results.append({
                    "broker_name": name,
                    "country": country,
                    "source": "LinkedIn Search",
                    "website": url, "email": "", "phone": "",
                    "description": snippet[:300],
                })
    except Exception as e:
        logging.error(f"LinkedIn search failed {country}: {e}")
    logging.info(f"  LinkedIn → {len(results)} for {country}")
    return results

# ─────────────────────────────────────────────
# SOURCE 5 — Insurer partner pages
# ─────────────────────────────────────────────

INSURER_PAGES = [
    {"name": "Now Health Broker Page",      "url": "https://www.nowhealth.com/en/broker"},
    {"name": "APRIL International Broker",  "url": "https://www.april-international.com/en/brokers"},
    {"name": "AXA Global Healthcare Broker","url": "https://www.axaglobalhealthcare.com/en/intermediaries/"},
    {"name": "Allianz Care Broker",         "url": "https://www.allianzcare.com/en/partners/brokers.html"},
]

SKIP_WORDS = {"read more","contact","click","learn","find","search","home","about","news","login","sign"}

def scrape_insurer_pages() -> list[dict]:
    results = []
    for insurer in INSURER_PAGES:
        soup = fetch(insurer["url"])
        if not soup:
            continue
        for tag in soup.find_all(["h2","h3","h4","li","strong","td"]):
            text = tag.get_text(strip=True)
            if (5 < len(text) < 100
                    and not is_known(text)
                    and not any(s in text.lower() for s in SKIP_WORDS)):
                results.append({
                    "broker_name": text,
                    "country": "Global",
                    "source": insurer["name"],
                    "website": "", "email": "", "phone": "",
                    "description": f"Listed on {insurer['name']}",
                })
        logging.info(f"  {insurer['name']} → scraped")
        time.sleep(SCRAPE_DELAY)

    seen, unique = set(), []
    for r in results:
        if r["broker_name"] not in seen:
            seen.add(r["broker_name"])
            unique.append(r)
    return unique

# ─────────────────────────────────────────────
# SOURCE 6 — Supplementary SerpApi (LATAM)
# ─────────────────────────────────────────────

LATAM_COUNTRIES = {
    "Panama","Costa Rica","Uruguay","Paraguay","Bolivia",
    "Ecuador","Guatemala","Honduras","El Salvador","Dominican Republic",
}

def search_supplementary(country: str, api_key: str) -> list[dict]:
    if country not in LATAM_COUNTRIES:
        return []
    results = []
    for query in [
        f'"seguro de salud internacional" broker "{country}"',
        f'"international health insurance" broker "{country}" expat',
    ]:
        params = {
            "q": query, "api_key": api_key, "num": 10,
            "hl": "es" if "seguro" in query else "en", "gl": "us",
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
                        "website": url, "email": "", "phone": "",
                        "description": snippet[:300],
                    })
            time.sleep(SERPAPI_DELAY)
        except Exception as e:
            logging.error(f"Supplementary search failed {country}: {e}")
    logging.info(f"  Supplementary → {len(results)} for {country}")
    return results

# ─────────────────────────────────────────────
# DEDUPLICATION
# ─────────────────────────────────────────────

def normalize_name(name: str) -> str:
    name = name.lower().strip()
    for s in [" ltd"," limited"," llc"," sarl"," sa"," plc"," inc"," gmbh"," srl"," ag"," bv"," pte"]:
        name = name.replace(s, "")
    return re.sub(r'\s+', ' ', name).strip()

# ─────────────────────────────────────────────
# MAIN AGENT
# ─────────────────────────────────────────────

def run_agent():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    log_file = os.path.join(LOG_DIR, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    logging.info("=" * 60)
    logging.info("IPMI BROKER AGENT v3 — Claude AI Filtering Edition")
    logging.info(f"Countries: {len(COUNTRIES)} | Exclusions: {len(KNOWN_BROKERS)}")
    claude_active = bool(ANTHROPIC_API_KEY)
    logging.info(f"Claude AI filtering: {'✅ ACTIVE' if claude_active else '⚠️  INACTIVE (keyword fallback)'}")
    logging.info("=" * 60)

    try:
        api_key = get_serpapi_key()
        logging.info("SerpApi key loaded ✓")
    except ValueError as e:
        logging.error(str(e))
        return

    raw_leads     = []
    seen_names    = set()
    serpapi_calls = 0

    # ── Collect from all sources ──────────────

    logging.info("\n[SOURCE 3] iPMI Global Directory")
    for lead in scrape_ipmi_global():
        norm = normalize_name(lead["broker_name"])
        if norm not in seen_names:
            seen_names.add(norm)
            raw_leads.append(lead)

    logging.info("\n[SOURCE 5] Insurer Partner Pages")
    for lead in scrape_insurer_pages():
        norm = normalize_name(lead["broker_name"])
        if norm not in seen_names:
            seen_names.add(norm)
            raw_leads.append(lead)

    for country, config in COUNTRIES.items():
        region   = config["region"]
        priority = config["priority"]
        logging.info(f"\n── {country} ({region}, {priority}) ──")

        country_leads = []

        if region == "Small Europe" and country in EIOPA_COUNTRY_CODES:
            country_leads += scrape_eiopa(country)
            time.sleep(SCRAPE_DELAY)

        if region == "Middle East":
            country_leads += scrape_regulator(country)

        if priority in ["high", "medium"] and country != "India":
            country_leads += search_linkedin(country, api_key)
            serpapi_calls += 1
            time.sleep(SERPAPI_DELAY)

        if region == "LATAM":
            country_leads += search_supplementary(country, api_key)
            serpapi_calls += 2
            time.sleep(SERPAPI_DELAY)

        for lead in country_leads:
            norm = normalize_name(lead["broker_name"])
            if norm and norm not in seen_names and not is_known(lead["broker_name"]):
                seen_names.add(norm)
                raw_leads.append(lead)

    logging.info(f"\n[RAW] {len(raw_leads)} total candidates before AI filtering")

    # ── Claude AI filtering ───────────────────

    logging.info(f"\n[CLAUDE] Filtering {len(raw_leads)} leads...")
    all_leads       = []
    filtered_out    = 0
    claude_calls    = 0

    for i, lead in enumerate(raw_leads, 1):
        logging.info(f"  [{i}/{len(raw_leads)}] {lead['broker_name'][:50]}")

        keep, score, verdict = claude_filter(lead)
        claude_calls += 1

        lead["ipmi_score"]   = score
        lead["ipmi_verdict"] = verdict
        lead["run_date"]     = datetime.now().strftime("%Y-%m-%d")
        lead["region"]       = lead.get("region") or COUNTRIES.get(lead.get("country",""), {}).get("region","Global")
        lead["priority"]     = lead.get("priority") or COUNTRIES.get(lead.get("country",""), {}).get("priority","medium")

        if keep:
            all_leads.append(lead)
        else:
            filtered_out += 1
            logging.info(f"    ❌ Filtered: {verdict[:60]}")

    logging.info(f"\n[FILTER] Kept: {len(all_leads)} | Removed: {filtered_out}")

    # ── Save outputs ──────────────────────────

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = os.path.join(OUTPUT_DIR, f"ipmi_brokers_{timestamp}.csv")

    sorted_leads = sorted(all_leads, key=lambda x: x.get("ipmi_score", 0), reverse=True)

    fieldnames = [
        "country","region","priority","broker_name",
        "website","email","phone","description",
        "ipmi_score","ipmi_verdict","source","run_date",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted_leads)

    json_path = os.path.join(OUTPUT_DIR, "latest.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(sorted_leads, f, ensure_ascii=False, indent=2)

    strong   = [r for r in all_leads if r.get("ipmi_score",0) >= 70]
    possible = [r for r in all_leads if 40 <= r.get("ipmi_score",0) < 70]
    weak     = [r for r in all_leads if r.get("ipmi_score",0) < 40]

    logging.info("\n" + "=" * 60)
    logging.info("RUN COMPLETE")
    logging.info(f"Raw candidates       : {len(raw_leads)}")
    logging.info(f"After AI filtering   : {len(all_leads)}")
    logging.info(f"🟢 Strong IPMI       : {len(strong)}")
    logging.info(f"🟡 Possible          : {len(possible)}")
    logging.info(f"🔴 Filtered out      : {filtered_out}")
    logging.info(f"SerpApi calls        : {serpapi_calls}")
    logging.info(f"Claude API calls     : {claude_calls}")
    logging.info(f"CSV                  : {csv_path}")
    logging.info("=" * 60)

    summary = {
        "run_date": datetime.now().isoformat(),
        "raw_candidates": len(raw_leads),
        "total_leads": len(all_leads),
        "strong": len(strong),
        "possible": len(possible),
        "filtered_out": filtered_out,
        "serpapi_calls": serpapi_calls,
        "claude_calls": claude_calls,
        "claude_active": claude_active,
    }
    with open(os.path.join(OUTPUT_DIR, "latest_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n✅ Done! {len(all_leads)} quality leads | {len(strong)} strong | {filtered_out} filtered out")
    print(f"   SerpApi: {serpapi_calls} calls | Claude: {claude_calls} calls")

if __name__ == "__main__":
    run_agent()
