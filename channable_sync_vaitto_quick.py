#!/usr/bin/env python3
"""
Channable → Vaitto  QUICK SYNC  (Tluxy / EU-WAR-2)
Price + stock only — meant to run every 15–30 min alongside the full sync.

Sends a minimal payload per product: sku, name, brand_id, stock_qty,
supplier_price, rrp. Omits images/category/subcategory/description/gender
since those rarely change and this keeps each run fast and light.

Env vars: CHANNABLE_URL, VAITTO_SUPABASE_URL, VAITTO_SUPABASE_SERVICE_KEY,
          VAITTO_HOOK_URL, IMPORT_HOOK_SECRET, VAITTO_DRY_RUN
"""
import os, sys, logging
from io import StringIO
from datetime import datetime
import requests, pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from vaitto_upsert import VaittoUpsertSession
from vaitto_taxonomy import load_brands

SUPPLIER_ID   = "a4d69ebf-8916-440c-9640-3aec9770053e"
SUPPLIER_NAME = "Tluxy (EU-WAR-2) [quick]"
CHANNABLE_URL = os.environ.get("CHANNABLE_URL", "")
SB_URL        = os.environ.get("VAITTO_SUPABASE_URL", "")
SB_KEY        = os.environ.get("VAITTO_SUPABASE_SERVICE_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

SWEEP_URL = os.environ.get("VAITTO_SWEEP_URL") or os.environ.get(
    "VAITTO_HOOK_URL", "https://vaitto.com/api/public/hooks/vaitto-product-import"
).replace("vaitto-product-import", "vaitto-product-sweep")


def get_existing_skus(supplier_id: str) -> set:
    """Fetch the set of vaitto_sku values already in Vaitto for this supplier.
    Used to skip brand-new products in the quick sync — new products should
    only be created by the full sync, which sends images/category/etc.

    Asks the Vaitto app (vaitto-product-sweep hook, action=list) instead of
    reading Supabase directly: the VAITTO_SUPABASE_URL secret points at a
    different project, which made this list incomplete and silently skipped
    ~130 existing products on every quick run."""
    try:
        r = requests.post(
            SWEEP_URL,
            headers={"x-hook-secret": os.environ.get("IMPORT_HOOK_SECRET", ""),
                     "Content-Type": "application/json"},
            json={"action": "list", "supplier_id": supplier_id},
            timeout=60,
        )
        res = r.json()
    except Exception as e:
        log.error(f"  Failed to fetch existing SKUs: {e}")
        sys.exit(1)
    if r.status_code != 200 or not res.get("ok"):
        # Never guess: without the list we can't tell new from existing, and
        # sending new products here would create them without images/category.
        log.error(f"  Failed to fetch existing SKUs: HTTP {r.status_code} {str(res)[:300]}")
        sys.exit(1)
    return set(res.get("skus") or [])


def run():
    if not CHANNABLE_URL:
        sys.exit("Missing CHANNABLE_URL")

    log.info(f"⚡  Channable → Vaitto  QUICK  {datetime.now():%Y-%m-%d %H:%M:%S}")

    # Brands are still required by the webhook schema, so still load them —
    # but this is a fast cached lookup, not the bottleneck.
    brands = load_brands(SB_URL, SB_KEY)
    log.info(f"  {len(brands)} brands loaded")

    existing_skus = get_existing_skus(SUPPLIER_ID)
    log.info(f"  {len(existing_skus)} existing SKUs found — new products will be skipped "
             f"(handled by full sync instead)")

    r = requests.get(CHANNABLE_URL, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    df.columns = df.columns.str.strip()
    df["quantity"]         = pd.to_numeric(df.get("quantity"),         errors="coerce").fillna(0).astype(int)
    df["wholesale_ EUR"]   = pd.to_numeric(df.get("wholesale_ EUR"),   errors="coerce")
    df["retail_price EUR"] = pd.to_numeric(df.get("retail_price EUR"), errors="coerce")
    log.info(f"  Feed: {len(df)} rows · {df['item_group_id'].nunique()} products")

    session = VaittoUpsertSession(SUPPLIER_ID, SUPPLIER_NAME)

    skipped_new = 0
    for i, (igid, group) in enumerate(df.groupby("item_group_id"), 1):
        if str(igid) not in existing_skus:
            skipped_new += 1
            continue

        first     = group.iloc[0]
        stock_qty = int(group["quantity"].sum())
        ref       = group[group["quantity"] > 0].iloc[0] if stock_qty > 0 else first
        cost      = ref.get("wholesale_ EUR")
        rrp       = ref.get("retail_price EUR")
        vendor    = str(first.get("vendor", "")).strip()

        # Minimal payload: no images, no category/subcategory/gender/description.
        # vaitto_upsert only sends keys that have a value, so omitted fields are
        # left untouched by the webhook rather than overwritten with blanks.
        session.upsert(
            sku=str(igid),
            name=str(first.get("title", igid)),
            brand=vendor or None,
            supplier_price=float(cost) if pd.notna(cost) and cost else None,
            rrp=float(rrp) if pd.notna(rrp) and rrp else None,
            stock_qty=stock_qty,
        )

    log.info(f"  {skipped_new} new products skipped (will be created by the full sync)")
    session.finish()

if __name__ == "__main__":
    run()
