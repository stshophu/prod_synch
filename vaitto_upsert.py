"""
vaitto_upsert.py — shared write layer for all Vaitto supplier pipelines.

Env vars:
  VAITTO_SUPABASE_URL
  VAITTO_SUPABASE_SERVICE_KEY
  VAITTO_DRY_RUN=1  (optional)
"""
import os, sys, logging, time, requests
from typing import Optional

log = logging.getLogger(__name__)

URL     = os.environ.get("VAITTO_SUPABASE_URL", "").rstrip("/")
KEY     = os.environ.get("VAITTO_SUPABASE_SERVICE_KEY", "")
DRY_RUN = os.environ.get("VAITTO_DRY_RUN", "0") == "1"

if not URL or not KEY:
    sys.exit("Missing VAITTO_SUPABASE_URL or VAITTO_SUPABASE_SERVICE_KEY")

_H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

def _req(method, table, params=None, body=None, prefer="return=minimal"):
    headers = {**_H, "Prefer": prefer}
    for attempt in range(4):
        try:
            r = requests.request(method, f"{URL}/rest/v1/{table}",
                                 headers=headers, params=params, json=body, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 5))); continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt); continue
            return r
        except requests.RequestException as e:
            log.warning(f"Network error (attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)
    return None


class VaittoUpsertSession:
    def __init__(self, supplier_id: str, supplier_name: str):
        self.supplier_id   = supplier_id
        self.supplier_name = supplier_name
        self.counts        = {"created": 0, "updated": 0, "deactivated": 0,
                              "skipped": 0, "errors": 0}
        # Load existing products for this supplier (vaitto_sku → product id)
        r = _req("GET", "products",
                 params={"supplier_id": f"eq.{supplier_id}",
                         "select": "id,vaitto_sku", "limit": "10000"})
        self.existing = {}
        if r is not None and r.status_code == 200:
            self.existing = {row["vaitto_sku"]: row["id"]
                             for row in r.json() if row.get("vaitto_sku")}
        elif r is not None:
            log.error(f"  ⚠️  Failed to load existing products: "
                      f"{r.status_code} {r.text[:300]}")
        else:
            log.error("  ⚠️  Failed to load existing products: no response "
                      "(network error / retries exhausted)")
        log.info(f"  {supplier_name}: {len(self.existing)} existing products")

    def upsert(self, *, sku: str, name: str,
               brand_id: Optional[str],
               category_id: Optional[str] = None,
               subcategory_id: Optional[str] = None,
               gender: Optional[str] = None,
               supplier_price: Optional[float] = None,
               rrp: Optional[float] = None,
               stock_qty: int,
               description: Optional[str] = None,
               image_url: Optional[str] = None,
               images: list = None):

        is_new = sku not in self.existing

        # Skip new zero-stock products
        if is_new and stock_qty == 0:
            self.counts["skipped"] += 1
            return

        # Deactivate existing zero-stock products
        if not is_new and stock_qty == 0:
            if not DRY_RUN:
                _req("PATCH", "products",
                     params={"id": f"eq.{self.existing[sku]}"},
                     body={"active": False, "stock_qty": 0})
            log.info(f"  🔴 DEACTIVATED  '{name}'")
            self.counts["deactivated"] += 1
            return

        slug = f"{self.supplier_id[:8]}-{sku}".lower().replace(" ", "-")[:200]
        body = {
            "supplier_id":        self.supplier_id,
            "vaitto_sku":         sku,
            "name":               name,
            "slug":               slug,
            "brand_id":           brand_id,
            "category_id":        category_id,
            "subcategory_id":     subcategory_id,
            "gender":             gender,
            "description":        description or "",
            "supplier_price":     round(supplier_price, 2) if supplier_price else None,
            "rrp":                round(rrp, 2) if rrp else None,
            "stock_qty":          stock_qty,
            "active":             True,
            "dropship_available": True,
            "image_url":          image_url,
            "images":             [{"url": u} for u in (images or [])] or [],
        }

        if DRY_RUN:
            log.info(f"  [DRY RUN] {'CREATE' if is_new else 'UPDATE'} '{name}' (stock={stock_qty})")
            return

        if is_new:
            r = _req("POST", "products", body=body, prefer="return=representation")
            if r is not None and r.status_code in (200, 201):
                data = r.json()
                self.existing[sku] = data[0]["id"] if isinstance(data, list) else data["id"]
                log.info(f"  ✅ CREATED  '{name}'  (stock={stock_qty})")
                self.counts["created"] += 1
            else:
                status = r.status_code if r is not None else "no response"
                detail = r.text[:150] if r is not None else "(network error / retries exhausted)"
                log.error(f"  ❌ CREATE failed {sku}: {status} {detail}")
                self.counts["errors"] += 1
        else:
            update = {k: v for k, v in body.items() if k not in ("slug", "vaitto_sku")}
            r = _req("PATCH", "products",
                     params={"id": f"eq.{self.existing[sku]}"}, body=update)
            if r is not None and r.status_code in (200, 204):
                log.info(f"  🔄 UPDATED  '{name}'  (stock={stock_qty})")
                self.counts["updated"] += 1
            else:
                status = r.status_code if r is not None else "no response"
                detail = r.text[:150] if r is not None else "(network error / retries exhausted)"
                log.error(f"  ❌ UPDATE failed {sku}: {status} {detail}")
                self.counts["errors"] += 1

    def finish(self):
        c = self.counts
        log.info(f"\n  {self.supplier_name} done — "
                 f"✅{c['created']} created  🔄{c['updated']} updated  "
                 f"🔴{c['deactivated']} deactivated  "
                 f"⏭{c['skipped']} skipped  ❌{c['errors']} errors")
        return c
