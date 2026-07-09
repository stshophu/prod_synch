"""
vaitto_upsert.py — shared write layer for all Vaitto supplier pipelines.
Uses direct Postgres connection (psycopg2) — bypasses Supabase REST/PostgREST.

Env vars:
  VAITTO_DB_URL   postgresql://postgres:xxx@db.haxjeeurccsprxkpasjk.supabase.co:5432/postgres
  VAITTO_DRY_RUN  '1' to log without writing
"""
import os, sys, logging, time, json
from typing import Optional

log = logging.getLogger(__name__)

DB_URL  = os.environ.get("VAITTO_DB_URL", "")
DRY_RUN = os.environ.get("VAITTO_DRY_RUN", "0") == "1"

if not DB_URL:
    sys.exit("Missing VAITTO_DB_URL")

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    sys.exit("Run: pip install psycopg2-binary")

def _conn():
    return psycopg2.connect(DB_URL, connect_timeout=15)


class VaittoUpsertSession:
    def __init__(self, supplier_id: str, supplier_name: str):
        self.supplier_id   = supplier_id
        self.supplier_name = supplier_name
        self.counts        = {"created": 0, "updated": 0, "deactivated": 0,
                              "skipped": 0, "errors": 0}
        # Load existing products (vaitto_sku → product id)
        self.existing = {}
        try:
            with _conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT id, vaitto_sku FROM products WHERE supplier_id = %s AND vaitto_sku IS NOT NULL",
                    (supplier_id,)
                )
                self.existing = {row[1]: row[0] for row in cur.fetchall()}
        except Exception as e:
            log.error(f"Failed to load existing products: {e}")
        log.info(f"  {supplier_name}: {len(self.existing)} existing products")

    def upsert(self, *, sku: str, name: str,
               brand_id: Optional[str] = None,
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
                try:
                    with _conn() as conn, conn.cursor() as cur:
                        cur.execute(
                            "UPDATE products SET active = false, stock_qty = 0 WHERE id = %s",
                            (self.existing[sku],)
                        )
                        conn.commit()
                except Exception as e:
                    log.error(f"  ❌ Deactivate failed {sku}: {e}")
                    return
            log.info(f"  🔴 DEACTIVATED  '{name}'")
            self.counts["deactivated"] += 1
            return

        slug = f"{self.supplier_id[:8]}-{sku}".lower().replace(" ", "-")[:200]
        images_json = json.dumps([{"url": u} for u in (images or [])])

        if DRY_RUN:
            log.info(f"  [DRY RUN] {'CREATE' if is_new else 'UPDATE'} '{name}' (stock={stock_qty})")
            return

        try:
            with _conn() as conn, conn.cursor() as cur:
                if is_new:
                    cur.execute("""
                        INSERT INTO products (
                            supplier_id, vaitto_sku, name, slug, brand_id,
                            category_id, subcategory_id, gender, description,
                            supplier_price, rrp, stock_qty, active,
                            dropship_available, image_url, images
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, true,
                            true, %s, %s
                        ) RETURNING id
                    """, (
                        self.supplier_id, sku, name, slug, brand_id,
                        category_id, subcategory_id, gender, description or "",
                        supplier_price, rrp, stock_qty,
                        image_url, images_json
                    ))
                    new_id = cur.fetchone()[0]
                    conn.commit()
                    self.existing[sku] = new_id
                    log.info(f"  ✅ CREATED  '{name}'  (stock={stock_qty})")
                    self.counts["created"] += 1
                else:
                    cur.execute("""
                        UPDATE products SET
                            name = %s, brand_id = %s,
                            category_id = %s, subcategory_id = %s, gender = %s,
                            description = %s, supplier_price = %s, rrp = %s,
                            stock_qty = %s, active = true,
                            image_url = %s, images = %s
                        WHERE id = %s
                    """, (
                        name, brand_id,
                        category_id, subcategory_id, gender,
                        description or "", supplier_price, rrp,
                        stock_qty,
                        image_url, images_json,
                        self.existing[sku]
                    ))
                    conn.commit()
                    log.info(f"  🔄 UPDATED  '{name}'  (stock={stock_qty})")
                    self.counts["updated"] += 1
        except Exception as e:
            log.error(f"  ❌ {'CREATE' if is_new else 'UPDATE'} failed {sku}: {e}")
            self.counts["errors"] += 1

        time.sleep(0.05)  # gentle pacing

    def finish(self):
        c = self.counts
        log.info(f"\n  {self.supplier_name} done — "
                 f"✅{c['created']} created  🔄{c['updated']} updated  "
                 f"🔴{c['deactivated']} deactivated  "
                 f"⏭{c['skipped']} skipped  ❌{c['errors']} errors")
        return c
