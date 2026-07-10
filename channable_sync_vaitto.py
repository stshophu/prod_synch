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
from vaitto_taxonomy import resolve_brand, resolve_category, resolve_subcategory, resolve_gender, load_brands

SUPPLIER_ID   = "a4d69ebf-8916-440c-9640-3aec9770053e"
SUPPLIER_NAME = "Tluxy (EU-WAR-2)"
CHANNABLE_URL = os.environ.get("CHANNABLE_URL", "")
SB_URL        = os.environ.get("VAITTO_SUPABASE_URL", "")
SB_KEY        = os.environ.get("VAITTO_SUPABASE_SERVICE_KEY", "")


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

    for i, (igid, group) in enumerate(df.groupby("item_group_id"), 1):
        first     = group.iloc[0]
        stock_qty = int(group["quantity"].sum())
        ref       = group[group["quantity"] > 0].iloc[0] if stock_qty > 0 else first
        cost      = ref.get("wholesale_ EUR")
        rrp       = ref.get("retail_price EUR")

        vendor   = str(first.get("vendor", "")).strip()
        subcat   = str(first.get("sub_category", "")).strip()
        gender   = str(first.get("gender", "")).strip()

        images, seen = [], set()
        for _, row in group.iterrows():
            for col in ["image_1","image_2","image_3","image_4","image_5"]:
                u = str(row.get(col, "")).strip()
                if u and u.lower() != "nan" and u not in seen:
                    seen.add(u); images.append(u)

        log.info(f"[{i}]  {igid}  '{first.get('title','')}' stock={stock_qty}")
        session.upsert(
            sku=str(igid),
            name=str(first.get("title", igid)),
            brand_id=resolve_brand(vendor),
            category_id=resolve_category(subcat),
            subcategory_id=resolve_subcategory(subcat),
            gender=resolve_gender(gender),
            supplier_price=float(cost) if pd.notna(cost) and cost else None,
            rrp=float(rrp) if pd.notna(rrp) and rrp else None,
            stock_qty=stock_qty,
            image_url=images[0] if images else None,
            images=images[:10],
        )

    session.finish()

if __name__ == "__main__":
    run()
