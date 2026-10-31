"""One-off cleanup: remove compare-at (strikethrough) prices from Tluxy and Loxuno products.

Their "RRP" is the supplier's own shop price, which Google Merchant Center treats
as a misleading discount. The syncs no longer set it; this clears what is left on
products the syncs no longer touch (e.g. sold out / dropped from the feed).
Rewix products (Italian retail price) are not touched.

  python clear_supplier_compare_at.py            # dry run: counts only
  python clear_supplier_compare_at.py --apply    # clears them

Env: SHOPIFY_TOKEN, SHOPIFY_STORE
"""
import os
import sys
import time

import requests

STORE = os.getenv("SHOPIFY_STORE", "siebentaschen.myshopify.com")
TOKEN = os.getenv("SHOPIFY_TOKEN", "")
URL = f"https://{STORE}/admin/api/2024-10/graphql.json"
APPLY = "--apply" in sys.argv
# Tluxy products carry a "channable-<code>" tag; Loxuno products carry SupplierSync / LXNsync.
QUERY = "tag:channable* OR tag:SupplierSync OR tag:LXNsync"

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


SCAN = """query($after: String, $q: String) {
  products(first: 100, after: $after, query: $q) {
    pageInfo { hasNextPage endCursor }
    nodes { id title tags variants(first: 100) { nodes { id compareAtPrice } } }
  }
}"""

UPDATE = """mutation($p: ID!, $v: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $p, variants: $v) { userErrors { field message } }
}"""


def is_rewix(tags):
    return any(t.lower() == "rewixsync" for t in tags)


def main():
    if not TOKEN:
        sys.exit("SHOPIFY_TOKEN not set")
    todo, after, scanned = [], None, 0
    while True:
        page = gql(SCAN, {"after": after, "q": QUERY})["products"]
        for p in page["nodes"]:
            scanned += 1
            if is_rewix(p["tags"]):
                continue
            vs = [{"id": v["id"], "compareAtPrice": None}
                  for v in p["variants"]["nodes"] if v.get("compareAtPrice")]
            if vs:
                todo.append((p["id"], p["title"], vs))
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    n_var = sum(len(v) for _, _, v in todo)
    print(f"Scanned {scanned} Tluxy/Loxuno products; {len(todo)} products / {n_var} variants still have a compare-at price")
    if not APPLY:
        print("Dry run — nothing changed. Re-run with --apply.")
        return
    errors = 0
    for i, (pid, title, vs) in enumerate(todo, 1):
        res = gql(UPDATE, {"p": pid, "v": vs})["productVariantsBulkUpdate"]
        if res["userErrors"]:
            errors += 1
            print("ERROR", title, res["userErrors"])
        if i % 100 == 0:
            print(f"  {i}/{len(todo)} done")
    print(f"Cleared compare-at on {len(todo)} products ({errors} with errors).")


if __name__ == "__main__":
    main()
