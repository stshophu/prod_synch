#!/usr/bin/env python3
"""
Channable → Shopify Auto-Sync
──────────────────────────────
• Runs via GitHub Actions every hour (no server / no terminal needed)
• Groups size variants by item_group_id → one Shopify product each
• Stateless: finds existing products via Shopify tags

Pricing (matches your existing store):
  Shopify selling price = Channable 'compare at price'
  Shopify compare-at    = Channable 'retail_price EUR'
"""

import os, sys, re, time, logging, requests, pandas as pd
from io import StringIO
from datetime import datetime

CHANNABLE_URL = os.getenv("CHANNABLE_URL",
    "https://files.channable.com/p3c5dKKrUlPQZVH_aBglWA==.csv")
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
                time.sleep(int(r.headers.get("Retry-After", 5))); continue
            if r.status_code == 404: return None
            if r.status_code in (200, 201): return r.json()
            log.error(f"  Shopify {r.status_code}: {r.text[:200]}")
            return None
        except requests.RequestException as e:
            log.warning(f"  Network error (attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)
    return None

def get_location_id():
    d = shopify("GET", "locations.json")
    return d["locations"][0]["id"] if d and d.get("locations") else None

def set_inventory(iid, lid, qty):
    shopify("POST", "inventory_levels/set.json",
            {"location_id": lid, "inventory_item_id": iid, "available": int(qty)})

# ── Build map of already-synced products from Shopify tags ────────────────────

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
        time.sleep(0.3)
    log.info(f"  Found {len(product_map)} previously synced")
    return product_map

# ── Data helpers ───────────────────────────────────────────────────────────────

def fetch_channable():
    log.info("📥  Fetching Channable feed…")
    try:
        r = requests.get(CHANNABLE_URL, timeout=60); r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df.columns = df.columns.str.strip()
        for c in ["wholesale_ EUR","compare at price","retail_price EUR","quantity"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["quantity"] = df["quantity"].fillna(0).astype(int)
        active = df[df["quantity"] >= 1].copy()
        log.info(f"  {len(active)} in-stock variants · {active['item_group_id'].nunique()} products")
        return active
    except Exception as e:
        log.error(f"Feed fetch failed: {e}"); return None

def html_desc(raw):
    if not raw or str(raw).strip().lower() in ("nan",""):  return ""
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

    variants = []
    for _, row in group.iterrows():
        gtin = str(row.get("gtin","")).split(".")[0].strip()
        v = {"sku": str(row["sku"]),
             "price": f"{float(row['compare at price']):.2f}",
             "compare_at_price": f"{float(row['retail_price EUR']):.2f}",
             "barcode": gtin if gtin.lower()!="nan" else "",
             "inventory_management": "shopify", "inventory_policy": "deny",
             "taxable": True, "requires_shipping": True,
             "_qty": int(row.get("quantity", 0)),
             "option1": str(row.get("color" if multi_c else "size",""))}
        if multi_c: v["option2"] = str(row.get("size",""))
        variants.append(v)

    options = ([{"name":"Color","values":colors},{"name":"Size","values":sizes}]
               if multi_c else [{"name":"Size","values":sizes}])

    tags = ", ".join(filter(None, [
        str(first.get("category","")).strip(),
        str(first.get("sub_category","")).strip(),
        str(first.get("gender","")).strip(),
        str(first.get("vendor","")).upper().strip(),
        f"channable-{igid}"]))

    return {"title": str(first["title"]), "body_html": html_desc(first.get("description","")),
            "vendor": str(first["vendor"]).upper(), "product_type": str(first.get("sub_category","")),
            "tags": tags, "status": "active", "options": options,
            "variants": variants, "images": collect_images(group)}

# ── Create / Update ────────────────────────────────────────────────────────────

def create_product(payload, lid):
    qtys = {v["sku"]: v.pop("_qty", 0) for v in payload["variants"]}
    result = shopify("POST", "products.json", {"product": payload})
    if not result: return None
    p = result["product"]
    for var in p["variants"]:
        qty = qtys.get(var.get("sku",""), 0)
        if qty > 0 and lid: set_inventory(var["inventory_item_id"], lid, qty)
        time.sleep(0.3)
    log.info(f"    ✅ CREATED  '{payload['title']}'  ({len(p['variants'])} variants)")
    return p["id"]

def update_product(pid, payload, lid):
    existing = shopify("GET", f"products/{pid}.json")
    if existing is None: return "recreate"
    ex = {v["sku"]: v for v in existing["product"].get("variants",[])}
    qtys = {v["sku"]: v.pop("_qty", 0) for v in payload["variants"]}
    for v in payload["variants"]:
        if v["sku"] in ex: v["id"] = ex[v["sku"]]["id"]
    result = shopify("PUT", f"products/{pid}.json", {"product": {
        "id": pid, "title": payload["title"], "body_html": payload["body_html"],
        "vendor": payload["vendor"], "product_type": payload["product_type"],
        "tags": payload["tags"], "variants": payload["variants"], "images": payload["images"]}})
    if not result: return False
    for var in result["product"]["variants"]:
        if lid: set_inventory(var["inventory_item_id"], lid, qtys.get(var.get("sku",""), 0))
        time.sleep(0.2)
    log.info(f"    🔄 UPDATED  '{payload['title']}'")
    return True

# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    if not SHOPIFY_TOKEN:
        log.error("SHOPIFY_TOKEN environment variable not set"); sys.exit(1)

    log.info("═"*55)
    log.info(f"🔄  Sync started  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    df = fetch_channable()
    if df is None or df.empty: log.error("No feed data — aborting"); return

    product_map = build_existing_map()
    lid = get_location_id()
    if not lid: sys.exit(1)

    groups = df.groupby("item_group_id")
    total = len(groups)
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
                else: errors += 1
            elif result: updated += 1
            else: errors += 1
        else:
            pid = create_product(payload, lid)
            if pid: created += 1
            else: errors += 1

        time.sleep(0.4)

    log.info(f"\n  ✅  {created} created · {updated} updated · {errors} errors")
    log.info("═"*55)

if __name__ == "__main__":
    run()
