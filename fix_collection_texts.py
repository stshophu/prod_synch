"""One-off: replace boilerplate collection texts that over-claim (Merchant Center misrepresentation).

  - category pages: "authentic luxury fashion offering the finest ...", "sourced directly from
    trusted trading partners, guaranteeing authenticity at exclusive prices", "fast European
    delivery, transparent pricing, and dedicated customer support"
  - brand pages: "past-season designer items" (part of the stock is current season)

  python fix_collection_texts.py            # dry run
  python fix_collection_texts.py --apply

Env: SHOPIFY_TOKEN, SHOPIFY_STORE
"""
import os
import re
import sys
import time

import requests

STORE = os.getenv("SHOPIFY_STORE", "siebentaschen.myshopify.com")
TOKEN = os.getenv("SHOPIFY_TOKEN", "")
URL = f"https://{STORE}/admin/api/2024-10/graphql.json"
APPLY = "--apply" in sys.argv
S = requests.Session()
S.headers.update({"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"})

REPLACEMENTS = [
    (re.compile(r"\s*—\s*authentic luxury fashion offering the finest [^.<]*\."), " from leading designer brands."),
    (re.compile(r"Each item is sourced directly from trusted trading partners, guaranteeing authenticity at exclusive prices\."),
     "Every piece is new and sourced through established Italian wholesale distributors."),
    (re.compile(r"with fast European delivery, transparent pricing, and dedicated customer support\."),
     "with delivery across Europe and worldwide."),
    (re.compile(r"All pieces at Siebentaschen are past-season designer items, sourced through established Italian distributors and offered below their original retail price\."),
     "Pieces at Siebentaschen are sourced through established Italian wholesale distributors and offered below their original retail price."),
]


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


def main():
    if not TOKEN:
        sys.exit("SHOPIFY_TOKEN not set")
    todo, after = [], None
    while True:
        page = gql("""query($after: String) { collections(first: 100, after: $after) {
            pageInfo { hasNextPage endCursor } nodes { id handle descriptionHtml } } }""",
                   {"after": after})["collections"]
        for c in page["nodes"]:
            old = c["descriptionHtml"] or ""
            new = old
            for pat, rep in REPLACEMENTS:
                new = pat.sub(rep, new)
            if new != old:
                todo.append((c["id"], c["handle"], new))
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    print(f"{len(todo)} collections to update")
    for _, h, new in todo[:3]:
        print(" ", h, "->", re.sub("<[^>]+>", " ", new)[:200])
    if not APPLY:
        print("Dry run — nothing changed.")
        return
    errors = 0
    for cid, h, new in todo:
        res = gql("""mutation($input: CollectionInput!) { collectionUpdate(input: $input) {
            userErrors { field message } } }""", {"input": {"id": cid, "descriptionHtml": new}})
        if res["collectionUpdate"]["userErrors"]:
            errors += 1
            print("ERROR", h, res["collectionUpdate"]["userErrors"])
    print(f"Updated {len(todo) - errors} collections ({errors} errors).")


if __name__ == "__main__":
    main()
