"""One-off cleanup: empty every Shopify variant barcode that is not a valid GTIN.

Google Merchant Center flags fake/internal barcodes as misrepresentation, so a
variant with no barcode is better than one with a wrong one. The supplier syncs
now only write valid GTINs; this clears the invalid ones already in the shop
(all suppliers, all product statuses).

  python clear_invalid_barcodes.py            # dry run: writes invalid_barcodes.csv, changes nothing
  python clear_invalid_barcodes.py --apply    # actually clears them

Env: SHOPIFY_TOKEN, SHOPIFY_STORE
"""
import csv
import os
import sys
import time
from collections import defaultdict

import requests

from channable_sync import valid_gtin

STORE = os.getenv("SHOPIFY_STORE", "siebentaschen.myshopify.com")
TOKEN = os.getenv("SHOPIFY_TOKEN", "")
URL = f"https://{STORE}/admin/api/2024-10/graphql.json"
APPLY = "--apply" in sys.argv

S = requests.Session()
S.headers.update({"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"})


def gql(query, variables=None):
    for attempt in range(8):
        r = S.post(URL, json={"query": query, "variables": variables or {}}, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        data = r.json()
        if any(e.get("extensions", {}).get("code") == "THROTTLED" for e in data.get("errors", [])):
            time.sleep(2 ** attempt)
            continue
        if data.get("errors"):
            raise RuntimeError(data["errors"])
        return data["data"]
    raise RuntimeError("Shopify kept throttling")


SCAN = """query($after: String) {
  productVariants(first: 250, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { id sku barcode product { id title vendor status } }
  }
}"""

UPDATE = """mutation($p: ID!, $v: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $p, variants: $v) { userErrors { field message } }
}"""


def main():
    if not TOKEN:
        sys.exit("SHOPIFY_TOKEN not set")
    bad, after, scanned = [], None, 0
    while True:
        page = gql(SCAN, {"after": after})["productVariants"]
        for v in page["nodes"]:
            scanned += 1
            code = (v.get("barcode") or "").strip()
            if code and not valid_gtin(code):
                bad.append(v)
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    with open("invalid_barcodes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["vendor", "product", "status", "sku", "barcode", "variant_id"])
        for v in bad:
            p = v["product"]
            w.writerow([p["vendor"], p["title"], p["status"], v["sku"], v["barcode"], v["id"]])
    print(f"Scanned {scanned} variants; {len(bad)} invalid -> invalid_barcodes.csv")

    if not APPLY:
        print("Dry run — nothing changed. Re-run with --apply to clear them.")
        return

    by_product = defaultdict(list)
    for v in bad:
        by_product[v["product"]["id"]].append({"id": v["id"], "barcode": ""})
    errors = 0
    for i, (pid, variants) in enumerate(by_product.items(), 1):
        res = gql(UPDATE, {"p": pid, "v": variants})["productVariantsBulkUpdate"]
        if res["userErrors"]:
            errors += 1
            print("ERROR", pid, res["userErrors"])
        if i % 50 == 0:
            print(f"  {i}/{len(by_product)} products done")
    print(f"Cleared {len(bad)} barcodes on {len(by_product)} products ({errors} products with errors).")


if __name__ == "__main__":
    main()
