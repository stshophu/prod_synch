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

def build_existing_map():
    log.info("  Scanning Shopify for previously-synced products…")
    product_map, path = {}, "products.json?limit=250&fields=id,tags"
    while path:
        full = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_VER}/{path}"
        r = S.get(full, timeout=30)
        if r.status_code != 200: break
        for p in r.json().get("products", []):
            for tag in p.get("tags", "").split(","):
                t = tag.strip()
                if t.startswith("channable-"):
                    product_map[t[len("channable-"):]] = p["id"]; break
        m = re.search(r'<[^>]*[?&]page_info=([^&>]+)[^>]*>;\s*rel="next"', r.headers.get("Link",""))
        path = f"products.json?limit=250&fields=id,tags&page_info={m.group(1)}" if m else None
        time.sleep(0.1)
    log.info(f"  Found {len(product_map)} previously synced")
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

def build_payload(group, igid):
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

        v = {"sku":                  str(row["sku"]),
             "price":                f"{selling_price:.2f}",
             "compare_at_price":     f"{float(row['retail_price EUR']):.2f}",
             "barcode":              gtin if gtin.lower()!="nan" else "",
             "inventory_management": "shopify",
             "inventory_policy":     "deny",
             "taxable":              True,
             "requires_shipping":    True,
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
        "images":       collect_images(group),
    }

    # Shopify standardized category (taxonomy)
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

def update_product(pid, payload, lid):
    existing = shopify("GET", f"products/{pid}.json")
    if existing is None: return "recreate"

    ex    = {v["sku"]: v for v in existing["product"].get("variants",[])}
    qtys  = {v["sku"]: v.pop("_qty",  0)    for v in payload["variants"]}
    costs = {v["sku"]: v.pop("_cost", None) for v in payload["variants"]}
    for v in payload["variants"]: v.pop("_feed", None)

    for v in payload["variants"]:
        if v["sku"] in ex: v["id"] = ex[v["sku"]]["id"]

    result = shopify("PUT", f"products/{pid}.json", {"product": {
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
    }})

    if not result: return False
    _apply_variant_extras(result["product"]["variants"], qtys, costs, lid)
    log.info(f"    🔄 UPDATED  '{payload['title']}'")
    return True

# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    if not SHOPIFY_TOKEN:
        log.error("SHOPIFY_TOKEN environment variable not set"); sys.exit(1)
    if not CHANNABLE_URL:
        log.error("CHANNABLE_URL environment variable not set"); sys.exit(1)

    log.info("═"*55)
    log.info(f"🔄  Sync started  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    df = fetch_channable()
    if df is None or df.empty: log.error("No feed data — aborting"); return

    product_map = build_existing_map()
    lid = get_location_id()
    if not lid: sys.exit(1)

    # Pre-load taxonomy so it's ready (avoids repeated fetches)
    load_taxonomy()

    groups  = df.groupby("item_group_id")
    total   = len(groups)
    created = updated = errors = 0

    for i, (igid, group) in enumerate(groups, 1):
        try:
            payload = build_payload(group, str(igid))
        except Exception as e:
            log.error(f"[{i}/{total}] Build error {igid}: {e}"); errors += 1; continue

        log.info(f"[{i}/{total}] {igid}  →  '{payload['title']}'")

        if igid in product_map:
            result = update_product(product_map[igid], payload, lid)
            if result == "recreate":
                pid = create_product(payload, lid)
                if pid: created += 1
                else:   errors  += 1
            elif result: updated += 1
            else:        errors  += 1
        else:
            pid = create_product(payload, lid)
            if pid: created += 1
            else:   errors  += 1

        time.sleep(0.15)

    log.info(f"\n  ✅  {created} created · {updated} updated · {errors} errors")
    log.info("═"*55)

if __name__ == "__main__":
    run()
