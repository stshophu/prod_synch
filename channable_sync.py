#!/usr/bin/env python3
"""
Channable → Shopify Auto-Sync
──────────────────────────────
• Runs via GitHub Actions every hour
• Groups size variants by item_group_id → one Shopify product each
• Sets Shopify standardized category (taxonomy) from sub_category
• Sets cost per item (wholesale price) on every variant

Pricing (margin-based, calculated from actual wholesale cost):
  Shopify compare-at    = Channable 'retail_price EUR'  (RRP)
  Shopify selling price = calculated for TARGET_MARGIN after VAT
  Shopify cost per item = Channable 'wholesale_ EUR'
"""

import os, sys, re, time, logging, requests, pandas as pd
from io import StringIO
from datetime import datetime

# ── Category-based weight defaults ────────────────────────────────────────────
# Kept in sync with backfill_weights.py / weight_defaults.py
# ORDER MATTERS: first match wins (checked against product_type then title).
_WEIGHT_RULES = [
    (("parka", "down jacket", "puffer", "coat"), 2.5),
    (("suit",), 1.8),
    (("gilet", "vest", "windbreaker"), 1.0),
    (("jacket", "blazer", "bomber", "biker"), 1.5),
    (("boot",), 2.0),
    (("sneaker", "trainer"), 1.5),
    (("flats", "sandal", "pump", "heel", "loafer", "oxford", "derb",
      "slipper", "mule", "slide", "espadrille", "slip-on", "slip on", "shoe"), 1.2),
    (("clutch", "pouch", "purse", "mini bag"), 1.0),
    (("bag", "backpack", "tote", "handbag"), 1.5),
    (("wallet", "cardholder", "card holder", "keyring", "key holder", "case"), 0.5),
    (("belt",), 0.6),
    (("sunglass", "eyewear", "glasses"), 0.5),
    (("bow tie", "pocket square", "necktie", "ties", "tie "), 0.3),
    (("scarf", "glove", "hat", "cap", "beanie"), 0.3),
    (("watch", "jewel", "bracelet", "necklace", "ring", "earring"), 0.5),
    (("swim", "bikini", "underwear", "bra", "brief", "legging", "sock",
      "lingerie", "boxer"), 0.3),
    (("sweater", "knit", "cardigan", "hoodie", "sweatshirt", "pullover",
      "jumper", "turtleneck"), 0.8),
    (("jean", "denim", "trouser", "pant", "chino", "jogger"), 0.8),
    (("dress",), 0.7),
    (("skirt", "short", "bermuda"), 0.5),
    (("shirt", "polo", "t-shirt", "tee", "top", "blouse", "bodysuit"), 0.5),
]

def default_weight_kg(product_type: str = "", title: str = "") -> float:
    """Return a category-default billable weight in kg (never 0)."""
    for haystack in ((product_type or "").lower(), (title or "").lower()):
        for keywords, kg in _WEIGHT_RULES:
            if any(k in haystack for k in keywords):
                return kg
    return 0.8  # fallback

# ── Pricing configuration (loaded from GitHub Secrets) ────────────────────────
TARGET_MARGIN    = float(os.getenv("TARGET_MARGIN",    "0.25"))
VAT_RATE         = float(os.getenv("VAT_RATE",         "0.19"))
MAX_DISC_DEFAULT = float(os.getenv("MAX_DISC_DEFAULT", "0.45"))
MAX_DISC_HALO    = float(os.getenv("MAX_DISC_HALO",    "0.42"))
MAX_DISC_SHOE    = float(os.getenv("MAX_DISC_SHOE",    "0.35"))
MIN_ACCEPTABLE_MARGIN = float(os.getenv("MIN_ACCEPTABLE_MARGIN", "0.10"))

# Brand tiers loaded from secrets (comma-separated lists)
_halo_default = (
    "PRADA,GUCCI,MONCLER,BALENCIAGA,BOTTEGA VENETA,TOM FORD,BALMAIN,"
    "OFF-WHITE,BRUNELLO CUCINELLI,ALAIA,ALAÏA,VALENTINO,LOEWE,CELINE,"
    "CÉLINE,DIOR,CHRISTIAN DIOR,SAINT LAURENT,GIVENCHY,FENDI,VALENTINO GARAVANI"
)
_shoe_default = (
    "CHRISTIAN LOUBOUTIN,LOUBOUTIN,JIMMY CHOO,GIANVITO ROSSI,"
    "SERGIO ROSSI,GIUSEPPE ZANOTTI,MANOLO BLAHNIK,AQUAZZURA"
)
HALO_BRANDS = set(os.getenv("HALO_BRANDS", _halo_default).split(","))
SHOE_BRANDS = set(os.getenv("SHOE_BRANDS", _shoe_default).split(","))

def calc_eu_margin(price, wholesale, vat=VAT_RATE):
    """Actual margin after VAT."""
    if not price or not wholesale: return 0
    return (price / (1 + vat) - wholesale) / (price / (1 + vat))

def price_decision(wholesale, rrp, vendor=""):
    """
    Returns (price, status, tag) where:
      status: 'ok' | 'low-margin' | 'review-margin'
      tag:    tag to add to product, or None
    """
    if not wholesale or not rrp or rrp <= 0 or wholesale <= 0:
        return None, 'ok', None

    v = vendor.upper()
    if any(b in v for b in HALO_BRANDS):   max_disc = MAX_DISC_HALO
    elif any(b in v for b in SHOE_BRANDS): max_disc = MAX_DISC_SHOE
    else:                                   max_disc = MAX_DISC_DEFAULT

    # Minimum price for target margin after VAT
    min_viable = wholesale * (1 + VAT_RATE) / (1 - TARGET_MARGIN)
    # Minimum price for minimum acceptable margin
    min_acceptable = wholesale * (1 + VAT_RATE) / (1 - MIN_ACCEPTABLE_MARGIN)
    # Competitive floor
    floor = rrp * (1 - max_disc)

    # Case 1: Even RRP doesn't cover minimum acceptable margin
    # → unpublish, tag review-margin
    if min_acceptable > rrp:
        margin_at_rrp = calc_eu_margin(rrp, wholesale)
        log.warning(f"  ⚠️  Margin at RRP only {margin_at_rrp:.0%} — flagging for review")
        return rrp, 'review-margin', 'review-margin'

    # Case 2: Can't hit target margin without going above RRP
    # → sell at RRP, tag low-margin
    if min_viable > rrp:
        return rrp, 'low-margin', 'low-margin'

    # Case 3: Normal — apply margin formula with discount
    price = max(min_viable, floor)
    price = min(price, rrp * 0.95)  # max 5% discount shown (keeps it looking premium)
    return round(price / 5) * 5 or round(min_viable / 5) * 5, 'ok', None

# Keep backward-compatible wrapper
def calc_selling_price(wholesale, rrp, vendor=""):
    price, _, _ = price_decision(wholesale, rrp, vendor)
    return price

CHANNABLE_URL = os.getenv("CHANNABLE_URL", "")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "siebentaschen.myshopify.com")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")
SHOPIFY_VER   = "2024-01"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Shopify API ────────────────────────────────────────────────────────────────

S = requests.Session()
S.headers.update({"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"})

def shopify(method, path, body=None, retries=4):
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_VER}/{path}"
    for attempt in range(retries):
        try:
            r = S.request(method, url, json=body, timeout=30)
            used, cap = (int(x) for x in r.headers.get("X-Shopify-Shop-Api-Call-Limit","0/40").split("/"))
            if used >= cap - 5: time.sleep(2)
            if r.status_code == 429:
                time.sleep(int(float(r.headers.get("Retry-After", 5)))); continue
            if r.status_code == 404: return None
            if r.status_code in (200, 201): return r.json()
            log.error(f"  Shopify {r.status_code} on {method} {path}: {r.text[:200]}")
            return None
        except requests.RequestException as e:
            log.warning(f"  Network error (attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)
    return None

def get_location_id():
    d = shopify("GET", "locations.json")
    return d["locations"][0]["id"] if d and d.get("locations") else None

def set_inventory(iid, lid, qty):
    r = shopify("POST", "inventory_levels/set.json",
                {"location_id": lid, "inventory_item_id": iid, "available": int(qty)})
    if not r:
        log.warning(f"  ⚠️  Failed to set inventory for item {iid}")

def set_cost(inventory_item_id, cost):
    """Set 'Cost per item' (wholesale price) on a variant's inventory item."""
    if not cost:
        return
    r = shopify("PUT", f"inventory_items/{inventory_item_id}.json",
                {"inventory_item": {"id": inventory_item_id, "cost": str(cost)}})
    if not r:
        log.warning(f"  ⚠️  Failed to set cost for inventory item {inventory_item_id}")

# ── Product taxonomy (Shopify standardized categories) ────────────────────────

# Maps Channable sub_category → search keywords in Shopify taxonomy names
_CATEGORY_KEYWORDS = {
    "jacket":       ["jacket"],
    "coat":         ["coat"],
    "vest":         ["vest"],
    "gilet":        ["vest"],
    "dress":        ["dress"],
    "pants":        ["pants"],
    "trousers":     ["pants"],
    "joggers":      ["pants"],
    "sweatpants":   ["pants"],
    "shorts":       ["shorts"],
    "skirt":        ["skirt"],
    "sweater":      ["sweater"],
    "pullover":     ["sweater"],
    "cardigan":     ["cardigan"],
    "sweatshirt":   ["sweatshirt", "hoodie"],
    "t-shirt":      ["t-shirt"],
    "t-shirt set":  ["t-shirt"],
    "shirt":        ["shirt"],
    "polo":         ["polo"],
    "top":          ["top"],
    "blazer":       ["blazer"],
    "jeans":        ["jeans"],
    "bag":          ["handbag"],
    "tote":         ["handbag"],
    "shoulder bag": ["shoulder bag", "handbag"],
    "loafers":      ["loafer"],
    "shoes":        ["shoes"],
    "sneakers":     ["sneaker"],
    "boots":        ["boot"],
    "scarf":        ["scarf"],
    "cap":          ["hat"],
    "swimsuit":     ["swimsuit", "swimwear"],
    "bracelet":     ["bracelet"],
    "earrings":     ["earring"],
    "wallet":       ["wallet"],
    "card holder":  ["wallet", "card"],
    "belt":         ["belt"],
    "turtleneck":   ["sweater"],
    "jumper":       ["sweater"],
}

_taxonomy_cache = None

def load_taxonomy():
    """Fetch Shopify's full product taxonomy once and cache it."""
    global _taxonomy_cache
    if _taxonomy_cache is not None:
        return _taxonomy_cache
    _taxonomy_cache = {}
    log.info("  Loading Shopify product taxonomy…")
    try:
        r = S.get(
            f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_VER}/product_categories.json?limit=250",
            timeout=30)
        if r.status_code == 200:
            for cat in r.json().get("product_categories", []):
                # Index by both short name and full hierarchical name
                _taxonomy_cache[cat["name"].lower()] = cat["id"]
                full = cat.get("full_name", "")
                if full:
                    _taxonomy_cache[full.lower()] = cat["id"]
            log.info(f"  Loaded {len(_taxonomy_cache)} taxonomy entries")
        else:
            log.warning(f"  Could not load taxonomy ({r.status_code}) — categories will be skipped")
    except Exception as e:
        log.warning(f"  Taxonomy fetch failed: {e}")
    return _taxonomy_cache

def get_category_id(sub_category):
    """Return a Shopify taxonomy node ID for a given sub_category string."""
    taxonomy = load_taxonomy()
    if not taxonomy:
        return None
    sub = sub_category.strip().lower()
    keywords = _CATEGORY_KEYWORDS.get(sub, [sub])
    for kw in keywords:
        for name, tid in taxonomy.items():
            if kw in name:
                return tid
    return None

# ── Build existing-product map from Shopify tags ──────────────────────────────
#
# FIX (duplicate-blindness): this used to do
#     product_map[item_group_id] = p["id"]
# which silently overwrites on every collision — with N duplicates sharing a
# tag, the script only ever "saw" 1 of them. It now collects ALL products per
# item-group, picks the OLDEST as canonical, and surfaces how many groups had
# duplicates so this is visible in every run's log instead of hiding forever.
#
# It also pulls each product's variants in the same request (fields=...,variants)
# so update_product() can map sku → variant_id from this cached data instead of
# doing a second per-product GET later. That GET was the direct cause of the
# "recreate" duplicate bug: any transient 5xx/timeout on it made the script
# treat an existing product as if it didn't exist and create a new one.

def build_existing_map():
    log.info("  Scanning Shopify for previously-synced products…")
    by_igid, path = {}, "products.json?limit=250&fields=id,tags,created_at,variants"
    pages = 0
    while path:
        full = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_VER}/{path}"
        r = None
        for attempt in range(6):
            try:
                r = S.get(full, timeout=30)
            except requests.RequestException as e:
                log.warning(f"  Network error scanning products (attempt {attempt+1}): {e}")
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 5))
                log.warning(f"  Rate limited while scanning products, waiting {wait}s")
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                log.warning(f"  Shopify {r.status_code} scanning products, retrying")
                time.sleep(2 ** attempt)
                continue
            break  # got a real response (2xx or a non-retryable error)
        if r is None or r.status_code != 200:
            # Do NOT silently return a partial map — a partial map here is what
            # causes every product past this point to look "never synced" on
            # EVERY run, which recreates duplicates forever. Fail loudly instead.
            log.error(f"  Failed to fully scan existing products (status "
                      f"{r.status_code if r is not None else 'no response'}) "
                      f"after {pages} pages / {len(by_igid)} item-groups collected. "
                      f"Aborting sync rather than risk mass duplicate creation.")
            sys.exit(1)
        pages += 1
        for p in r.json().get("products", []):
            igid = None
            for tag in p.get("tags", "").split(","):
                t = tag.strip()
                if t.startswith("channable-"):
                    igid = t[len("channable-"):]; break
            if igid:
                by_igid.setdefault(igid, []).append(p)
        m = re.search(r'<[^>]*[?&]page_info=([^&>]+)[^>]*>;\s*rel="next"', r.headers.get("Link",""))
        path = f"products.json?limit=250&fields=id,tags,created_at,variants&page_info={m.group(1)}" if m else None
        time.sleep(0.5)  # was 0.1 — too fast for REST limit, contributed to the 429s

    product_map, dup_groups, dup_total = {}, 0, 0
    for igid, products in by_igid.items():
        products.sort(key=lambda p: p.get("created_at", ""))  # oldest first
        canonical = products[0]
        product_map[igid] = {
            "id": canonical["id"],
            "variants": {v["sku"]: v["id"] for v in canonical.get("variants", []) if v.get("sku")},
        }
        if len(products) > 1:
            dup_groups += 1
            dup_total += len(products) - 1

    log.info(f"  Scanned {pages} pages · {len(product_map)} item-groups · "
             f"{sum(len(v) for v in by_igid.values())} total tagged products")
    if dup_groups:
        log.warning(f"  ⚠️  {dup_groups} item-groups have duplicates "
                    f"({dup_total} extra copies beyond the oldest) — "
                    f"these are being updated on the oldest copy only; "
                    f"run the dedupe script to archive the rest.")
    return product_map

# ── Data helpers ───────────────────────────────────────────────────────────────

def fetch_channable():
    log.info("📥  Fetching Channable feed…")
    try:
        r = requests.get(CHANNABLE_URL, timeout=60); r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df.columns = df.columns.str.strip()
        for c in ["wholesale_ EUR", "compare at price", "retail_price EUR", "quantity"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["quantity"] = df["quantity"].fillna(0).astype(int)
        active = df[df["quantity"] >= 1].copy()
        log.info(f"  {len(active)} in-stock variants · {active['item_group_id'].nunique()} products")
        return active
    except Exception as e:
        log.error(f"Feed fetch failed: {e}"); return None

def html_desc(raw):
    if not raw or str(raw).strip().lower() in ("nan",""): return ""
    parts = [p.strip("- ").strip() for p in str(raw).split(" - ") if p.strip("- ").strip()]
    return "<ul>"+"".join(f"<li>{p}</li>" for p in parts)+"</ul>" if parts else str(raw)

def collect_images(group):
    images, seen = [], set()
    for _, row in group.iterrows():
        for col in ["image_1","image_2","image_3","image_4","image_5"]:
            url = str(row.get(col,"")).strip()
            if url and url.lower()!="nan" and url not in seen:
                seen.add(url); images.append({"src": url})
    return images[:10]

def build_payload(group, igid, light=False):
    first   = group.iloc[0]
    colors  = list(group["color"].dropna().unique())
    sizes   = list(group["size"].dropna().astype(str).unique())
    multi_c = len(colors) > 1
    sub_cat = str(first.get("sub_category", "")).strip()
    vendor  = str(first.get("vendor",""))

    variants = []
    product_status = "active"
    margin_tag = None

    for _, row in group.iterrows():
        gtin = str(row.get("gtin","")).split(".")[0].strip()

        wholesale = row.get("wholesale_ EUR")
        rrp       = row.get("retail_price EUR")
        cost_val  = f"{float(wholesale):.2f}" if pd.notna(wholesale) and wholesale else None

        # Use margin-aware pricing decision
        selling_price = float(row.get("compare at price", 0) or 0)  # fallback
        if pd.notna(wholesale) and wholesale and pd.notna(rrp) and rrp:
            price, status, tag = price_decision(float(wholesale), float(rrp), vendor)
            if price:
                selling_price = price
            if status == 'review-margin':
                product_status = "draft"  # unpublish
                margin_tag = "review-margin"
            elif status == 'low-margin' and margin_tag != 'review-margin':
                margin_tag = "low-margin"

        wkg = default_weight_kg(sub_cat, str(first.get("title", "")))
        v = {"sku":                  str(row["sku"]),
             "price":                f"{selling_price:.2f}",
             "compare_at_price":     f"{float(row['retail_price EUR']):.2f}",
             "barcode":              gtin if gtin.lower()!="nan" else "",
             "inventory_management": "shopify",
             "inventory_policy":     "deny",
             "taxable":              True,
             "requires_shipping":    True,
             "weight":               wkg,
             "weight_unit":          "kg",
             "_qty":                 int(row.get("quantity", 0)),
             "_cost":                cost_val,
             "_feed":                {"rrp": float(rrp) if pd.notna(rrp) and rrp else 0},
             "option1":              str(row.get("color" if multi_c else "size",""))}
        if multi_c: v["option2"] = str(row.get("size",""))
        variants.append(v)

    options = ([{"name":"Color","values":colors},{"name":"Size","values":sizes}]
               if multi_c else [{"name":"Size","values":sizes}])

    tag_parts = [
        str(first.get("category","")).strip(),
        sub_cat,
        str(first.get("gender","")).strip(),
        vendor.upper().strip(),
        f"channable-{igid}",
        margin_tag,  # 'review-margin', 'low-margin', or None
    ]
    tags = ", ".join(filter(None, tag_parts))

    payload = {
        "title":        str(first["title"]),
        "body_html":    html_desc(first.get("description","")),
        "vendor":       vendor.upper(),
        "product_type": sub_cat,
        "tags":         tags,
        "status":       product_status,  # 'draft' if review-margin, else 'active'
        "options":      options,
        "variants":     variants,
        "images":       [] if light else collect_images(group),
    }

    # Shopify standardized category (taxonomy) — skip in light mode, it's
    # re-synced by the daily full run and costs a taxonomy lookup either way.
    if not light:
        cat_id = get_category_id(sub_cat)
        if cat_id:
            payload["product_category"] = {"product_taxonomy_node_id": cat_id}

    return payload

# ── Create / Update ────────────────────────────────────────────────────────────

def _apply_variant_extras(variants_response, qtys, costs, lid):
    """Set inventory quantity and cost per item for each variant."""
    for var in variants_response:
        sku  = var.get("sku", "")
        iid  = var["inventory_item_id"]
        qty  = qtys.get(sku, 0)
        cost = costs.get(sku)
        if lid:
            set_inventory(iid, lid, qty)
        if cost:
            set_cost(iid, cost)
        time.sleep(0.1)

def create_product(payload, lid):
    qtys  = {v["sku"]: v.pop("_qty",  0)    for v in payload["variants"]}
    costs = {v["sku"]: v.pop("_cost", None) for v in payload["variants"]}
    for v in payload["variants"]: v.pop("_feed", None)

    result = shopify("POST", "products.json", {"product": payload})
    if not result: return None

    p = result["product"]
    _apply_variant_extras(p["variants"], qtys, costs, lid)
    log.info(f"    ✅ CREATED  '{payload['title']}'  ({len(p['variants'])} variants)")
    return p["id"]

def update_product(entry, payload, lid, light=False):
    """
    entry: {"id": product_id, "variants": {sku: variant_id}} from build_existing_map().

    FIX (recreate bug): this used to GET the product first and return
    "recreate" if that GET failed for any reason (5xx, timeout, transient
    None). The main loop then called create_product() on that signal —
    which is exactly how new duplicates kept appearing in production. There
    is no GET here anymore: variant IDs come from the cached scan data, so
    a transient API hiccup on THIS call just fails this one PUT and gets
    logged/skipped — it can no longer fall through into creating a copy.

    light=True (used by the hourly fast sync): only price/compare-at,
    barcode, status and the inventory/cost side-calls are touched. Title,
    vendor, tags, body_html, product_type and taxonomy are left untouched —
    they're re-synced fully by the daily full run. This cuts payload size
    and API calls considerably for the run that has to finish in an hour.
    """
    pid = entry["id"]
    known_variants = entry.get("variants", {})

    qtys  = {v["sku"]: v.pop("_qty",  0)    for v in payload["variants"]}
    costs = {v["sku"]: v.pop("_cost", None) for v in payload["variants"]}
    for v in payload["variants"]: v.pop("_feed", None)

    for v in payload["variants"]:
        if v["sku"] in known_variants:
            v["id"] = known_variants[v["sku"]]
        # else: brand-new variant on an existing product (e.g. new size added)
        # — no "id" key means Shopify creates it as part of this PUT.

    if light:
        # Only touch variants we already know the ID for. A brand-new variant
        # (e.g. a new size just added to an existing product) needs the full
        # field set (option values, inventory_management, etc.) to be created
        # correctly — sending it stripped-down here could create a malformed
        # variant. Defer it to the daily full sync instead.
        light_variants = [
            {k: v[k] for k in ("id","sku","price","compare_at_price","barcode") if k in v}
            for v in payload["variants"] if "id" in v
        ]
        skipped_variants = len(payload["variants"]) - len(light_variants)
        if skipped_variants:
            log.info(f"    ↪ {skipped_variants} new variant(s) on this product "
                     f"deferred to daily full sync")
        body = {"id": pid, "status": payload.get("status", "active"),
                "variants": light_variants}
    else:
        body = {
            "id":           pid,
            "title":        payload["title"],
            "body_html":    payload["body_html"],
            "vendor":       payload["vendor"],
            "product_type": payload["product_type"],
            "tags":         payload["tags"],
            "status":       payload.get("status","active"),
            "variants":     payload["variants"],
            # Skip images on update — they rarely change and save API time
            **({"product_category": payload["product_category"]}
               if "product_category" in payload else {}),
        }

    result = shopify("PUT", f"products/{pid}.json", {"product": body})
    if not result:
        log.error(f"    ❌ Update failed for product {pid} ('{payload['title']}') — "
                  f"skipping this run, will retry next sync")
        return False
    _apply_variant_extras(result["product"]["variants"], qtys, costs, lid)
    log.info(f"    🔄 UPDATED  '{payload['title']}'" + ("  (light)" if light else ""))
    return True

# ── Main ───────────────────────────────────────────────────────────────────────

# FIX (timeout): the old single sequential job needed ~4.5h for ~1,100
# products at ~14.5s/product but was capped at 60 minutes — it died mid-run
# every single hour. Rather than fight that with concurrency (real risk of
# tripping Shopify's rate limiter harder), the sync now runs in two tiers:
#
#   SYNC_MODE=fast (hourly) — only touches products that already exist in
#   Shopify. No creates, no images, no taxonomy, no title/vendor/tags/body —
#   just price, compare-at, barcode, status, inventory and cost. This is the
#   data that actually needs to be fresh every hour, and it's light enough to
#   finish well inside 60 minutes.
#
#   SYNC_MODE=full (daily) — the original full behavior: creates new
#   products, and does a complete field sync (title/vendor/tags/body_html/
#   category/images) on existing ones. Runs once a day on a longer timeout
#   since it's the expensive pass.

SYNC_MODE = os.getenv("SYNC_MODE", "full").strip().lower()

def run():
    if not SHOPIFY_TOKEN:
        log.error("SHOPIFY_TOKEN environment variable not set"); sys.exit(1)
    if not CHANNABLE_URL:
        log.error("CHANNABLE_URL environment variable not set"); sys.exit(1)

    light = SYNC_MODE == "fast"

    log.info("═"*55)
    log.info(f"🔄  Sync started  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  "
             f"· mode={SYNC_MODE}")

    df = fetch_channable()
    if df is None or df.empty: log.error("No feed data — aborting"); return

    product_map = build_existing_map()
    lid = get_location_id()
    if not lid: sys.exit(1)

    if not light:
        # Pre-load taxonomy so it's ready (avoids repeated fetches) — only
        # needed for the full run, since light updates don't touch category.
        load_taxonomy()

    groups  = df.groupby("item_group_id")
    total   = len(groups)
    created = updated = errors = skipped_new = 0

    for i, (igid_raw, group) in enumerate(groups, 1):
        igid = str(igid_raw)
        try:
            payload = build_payload(group, igid, light=light)
        except Exception as e:
            log.error(f"[{i}/{total}] Build error {igid}: {e}"); errors += 1; continue

        log.info(f"[{i}/{total}] {igid}  →  '{payload['title']}'")

        if igid in product_map:
            if update_product(product_map[igid], payload, lid, light=light):
                updated += 1
            else:
                errors += 1
        elif light:
            # Fast mode never creates — new products wait for the daily full
            # run, which also re-scans and would otherwise race the same igid.
            skipped_new += 1
        else:
            pid = create_product(payload, lid)
            if pid: created += 1
            else:   errors  += 1

        time.sleep(0.15)

    summary = f"\n  ✅  {created} created · {updated} updated · {errors} errors"
    if light:
        summary += f" · {skipped_new} new products deferred to daily full sync"
    log.info(summary)
    log.info("═"*55)

if __name__ == "__main__":
    run()
