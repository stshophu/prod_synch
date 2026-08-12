#!/usr/bin/env python3
"""
Channable → Vaitto  (Tluxy / EU-WAR-2)
Env vars: CHANNABLE_URL, VAITTO_SUPABASE_URL, VAITTO_SUPABASE_SERVICE_KEY, VAITTO_DRY_RUN
"""
import os, sys, logging
from io import StringIO
from datetime import datetime
import requests, pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from vaitto_upsert import VaittoUpsertSession
from vaitto_taxonomy import (resolve_category, resolve_subcategory,
                             resolve_gender, load_brands)

SUPPLIER_ID   = "a4d69ebf-8916-440c-9640-3aec9770053e"
SUPPLIER_NAME = "Tluxy (EU-WAR-2)"
CHANNABLE_URL = os.environ.get("CHANNABLE_URL", "")
SB_URL        = os.environ.get("VAITTO_SUPABASE_URL", "")
SB_KEY        = os.environ.get("VAITTO_SUPABASE_SERVICE_KEY", "")


def _clean(v) -> str:
    """CSV cell -> stripped string; pandas NaN becomes empty."""
    s = str(v).strip() if v is not None else ""
    return "" if s.lower() in ("nan", "none") else s


logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

def run():
    if not CHANNABLE_URL:
        sys.exit("Missing CHANNABLE_URL")

    log.info(f"🚀  Channable → Vaitto  {datetime.now():%Y-%m-%d %H:%M:%S}")

    # Load brands once
    brands = load_brands(SB_URL, SB_KEY)
    log.info(f"  {len(brands)} brands loaded")

    r = requests.get(CHANNABLE_URL, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    df.columns = df.columns.str.strip()
    df["quantity"]         = pd.to_numeric(df.get("quantity"),         errors="coerce").fillna(0).astype(int)
    df["wholesale_ EUR"]   = pd.to_numeric(df.get("wholesale_ EUR"),   errors="coerce")
    df["retail_price EUR"] = pd.to_numeric(df.get("retail_price EUR"), errors="coerce")
    log.info(f"  Feed: {len(df)} rows · {df['item_group_id'].nunique()} products")

    session = VaittoUpsertSession(SUPPLIER_ID, SUPPLIER_NAME)

    unmapped_cat, unmapped_sub = set(), set()
    missing_desc = missing_img = missing_barcode = 0
    for i, (igid, group) in enumerate(df.groupby("item_group_id"), 1):
        first     = group.iloc[0]
        stock_qty = int(group["quantity"].sum())
        ref       = group[group["quantity"] > 0].iloc[0] if stock_qty > 0 else first
        cost      = ref.get("wholesale_ EUR")
        rrp       = ref.get("retail_price EUR")

        vendor   = _clean(first.get("vendor"))
        cat      = _clean(first.get("category"))
        subcat   = _clean(first.get("sub_category"))
        gender   = _clean(first.get("gender"))
        desc     = _clean(first.get("description"))
        barcode  = _clean(ref.get("gtin"))   # not yet accepted by the webhook

        images, seen = [], set()
        for _, row in group.iterrows():
            for col in ["image_1","image_2","image_3","image_4","image_5"]:
                u = str(row.get(col, "")).strip()
                if u and u.lower() != "nan" and u not in seen:
                    seen.add(u); images.append(u)

        cat_id    = resolve_category(cat, subcat)
        subcat_id = resolve_subcategory(subcat)

        if not cat_id:    unmapped_cat.add(cat or subcat)
        if not subcat_id: unmapped_sub.add(subcat)

        log.info(f"[{i}]  {igid}  '{first.get('title','')}' stock={stock_qty}")
        session.upsert(
            sku=str(igid),
            name=str(first.get("title", igid)),
            brand=vendor or None,
            category_id=cat_id,
            subcategory_id=subcat_id,
            gender=resolve_gender(gender),
            supplier_price=float(cost) if pd.notna(cost) and cost else None,
            rrp=float(rrp) if pd.notna(rrp) and rrp else None,
            stock_qty=stock_qty,
            description=desc or None,
            image_url=images[0] if images else None,
            images=images[:10],
        )

        if not desc:    missing_desc += 1
        if not images:  missing_img += 1
        if not barcode: missing_barcode += 1

    session.finish()

    log.info(f"\n  Feed coverage — no description: {missing_desc}  "
             f"no image: {missing_img}  no barcode: {missing_barcode}")
    if unmapped_cat:
        log.warning(f"  Unmapped categories: {sorted(v for v in unmapped_cat if v)}")
    if unmapped_sub:
        log.warning(f"  Unmapped sub_categories: {sorted(v for v in unmapped_sub if v)}")

if __name__ == "__main__":
    run()
