"""One-off: fill in missing SEO titles, meta descriptions and image alt texts.

Only EMPTY fields are filled. Anything already set (by hand or by an earlier
run) is left exactly as it is, so the script is safe to run more than once.

Text style (Nov 2026 SEO work): brand + gender + item + colour/material,
no "authentic"/"official"/discount claims (Merchant Center misrepresentation).

  python seo_backfill.py                 # dry run: writes seo_preview.csv, changes nothing
  python seo_backfill.py --apply         # writes the changes
  python seo_backfill.py --limit 50      # only the first 50 products that need changes

Env: SHOPIFY_TOKEN, SHOPIFY_STORE
"""
import csv
import html
import os
import re
import sys
import time

import requests

STORE = os.getenv("SHOPIFY_STORE", "siebentaschen.myshopify.com")
TOKEN = os.getenv("SHOPIFY_TOKEN", "")
URL = f"https://{STORE}/admin/api/2026-10/graphql.json"
APPLY = "--apply" in sys.argv
LIMIT = 0
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])

SUFFIX = " | Siebentaschen"
MAX_TITLE = 70
MAX_DESC = 160
TAIL = "Past-season designer fashion at Siebentaschen, delivered across Europe."

S = requests.Session()
S.headers.update({"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"})


def gql(query, variables=None):
    for attempt in range(10):
        try:
            r = S.post(URL, json={"query": query, "variables": variables or {}}, timeout=90)
        except requests.RequestException:
            time.sleep(2 ** min(attempt, 6))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** min(attempt, 6))
            continue
        r.raise_for_status()
        data = r.json()
        if any(e.get("extensions", {}).get("code") == "THROTTLED" for e in data.get("errors", [])):
            time.sleep(2 ** min(attempt, 6))
            continue
        if data.get("errors"):
            raise RuntimeError(data["errors"])
        # be gentle with the cost bucket
        cost = data.get("extensions", {}).get("cost", {}).get("throttleStatus", {})
        if cost and cost.get("currentlyAvailable", 1000) < 200:
            time.sleep(3)
        return data["data"]
    raise RuntimeError("Shopify kept throttling")


# ── text helpers ─────────────────────────────────────────────────────────────

SMALL_UPPER = {"JW", "CP", "ADD", "MSGM", "DG", "YSL", "KNT", "GCDS", "MM6", "A.P.C.", "UGG", "DKNY"}


def nice_case(s: str, keep_short_upper=False) -> str:
    """'SAINT LAURENT LE 5 À 7 BAG' -> 'Saint Laurent Le 5 À 7 Bag'; leaves mixed case alone."""
    s = re.sub(r"\s+", " ", (s or "").strip())
    letters = [c for c in s if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.7:
        return s
    out = []
    for w in s.split(" "):
        if keep_short_upper and w.upper() in SMALL_UPPER:
            out.append(w.upper())
        else:
            out.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(out).replace(" & ", " & ")


def text_of(desc_html: str) -> str:
    t = re.sub(r"<br\s*/?>|</li>|</p>", "\n", desc_html or "", flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", t))


def field(desc: str, *names) -> str:
    for n in names:
        m = re.search(rf"{n}\s*:\s*([^\n]+)", desc, re.I)
        if m:
            return m.group(1).strip().rstrip(".")
    return ""


def main_material(desc: str) -> str:
    m = field(desc, "Material")
    if not m:
        comp = field(desc, "Composition")
        mm = re.search(r"\d+\s*%\s*([A-Za-zÀ-ÿ ]+?)(?=\s*\d|,|;|$)", comp)
        m = mm.group(1) if mm else comp
    m = re.sub(r"\b(virgin|100%)\b", "", m, flags=re.I).strip(" ,")
    if not m or len(m) > 25 or not re.search(r"[A-Za-z]", m):
        return ""
    return m.lower()


def gender_word(tags, product_type, desc) -> str:
    t = {x.strip().lower() for x in tags}
    pt = (product_type or "").lower()
    g = field(desc, "Gender").lower()
    if t & {"women", "woman", "female"} or pt.startswith("women") or g.startswith("wom"):
        return "Women's"
    if t & {"men", "man", "male"} or pt.startswith("men") or g in ("men", "man", "male"):
        return "Men's"
    if t & {"kids", "junior", "kid"} or pt.startswith("kid"):
        return "Kids'"
    return ""


# generic supplier titles look like "Dolce & Gabbana Shirts Pink"
PLURALS = {
    "t-shirts": "T-Shirt", "shirts": "Shirt", "jackets": "Jacket", "coats": "Coat", "bow ties": "Bow Tie",
    "ties": "Tie", "pocket squares": "Pocket Square", "skirts": "Skirt", "belts": "Belt", "dresses": "Dress",
    "sweaters": "Sweater", "bags": "Bag", "scarves": "Scarf", "hats": "Hat", "caps": "Cap", "tops": "Top",
    "polos": "Polo Shirt", "polo shirts": "Polo Shirt", "cardigans": "Cardigan", "blazers": "Blazer",
    "vests": "Vest", "hoodies": "Hoodie", "sweatshirts": "Sweatshirt", "wallets": "Wallet",
    "backpacks": "Backpack", "suits": "Suit", "jumpsuits": "Jumpsuit", "blouses": "Blouse",
    "boots": "Boots", "sneakers": "Sneakers", "sandals": "Sandals", "loafers": "Loafers", "slippers": "Slippers",
    "pumps": "Pumps", "mules": "Mules", "trousers": "Trousers", "jeans": "Jeans", "shorts": "Shorts",
    "swimwear": "Swimwear", "knitwear": "Knitwear", "gloves": "Gloves", "sunglasses": "Sunglasses",
    "clutches": "Clutch", "card holders": "Card Holder", "shoes": "Shoes", "pants": "Trousers",
}
PLURAL_RE = re.compile(r"^(" + "|".join(sorted(map(re.escape, PLURALS), key=len, reverse=True)) + r")\b\s*(.*)$", re.I)


def build(p):
    """Return (name, seo_title, seo_desc) for a product."""
    brand = nice_case(p["vendor"], keep_short_upper=True)
    title = nice_case(p["title"], keep_short_upper=True)
    desc = text_of(p.get("descriptionHtml"))
    colour = nice_case(field(desc, "Colour", "Color"))
    material = main_material(desc)
    gender = gender_word(p.get("tags") or [], p.get("productType"), desc)

    starts_with_brand = title.lower().startswith(brand.lower()) if brand else False
    core = title[len(brand):].strip(" -–") if starts_with_brand else title

    m = PLURAL_RE.match(core)
    if m and starts_with_brand and len(core.split()) <= 5:  # generic: "<Types> <Colour>"
        item = PLURALS[m.group(1).lower()]
        rest = m.group(2).replace("/", " & ").strip() or colour
        mat = material.title() if material and material.lower() not in rest.lower() else ""
        core = " ".join(x for x in (rest, mat, item) if x)

    if re.search(r"\b(men|women|man|woman|kids?)\b", core, re.I) or not starts_with_brand:
        gender = ""

    def name_with(g):
        parts = [brand if starts_with_brand or brand.lower() not in core.lower() else "", g, core]
        return re.sub(r"\s+", " ", " ".join(x for x in parts if x)).strip()

    name = name_with(gender)
    seo_title = name + SUFFIX
    if len(seo_title) > MAX_TITLE:
        name_short = name_with("")
        seo_title = name_short + SUFFIX
        if len(seo_title) > MAX_TITLE:
            room = MAX_TITLE - len(SUFFIX)
            cut = name_short[:room]
            cut = cut.rsplit(",", 1)[0] if "," in cut else cut.rsplit(" ", 1)[0]
            seo_title = cut.rstrip(" ,-–") + SUFFIX

    extra = []
    if material and material.lower() not in name.lower():
        extra.append(f"in {material}")
    if colour and colour.replace("/", " & ").lower() not in name.lower():
        extra.append(f"in {colour.lower()}")
    first = f"{name} {' '.join(extra)}".strip() + "."
    if re.search(r"made in italy", desc, re.I):
        first += " Made in Italy."
    seo_desc = f"{first} {TAIL}"
    if len(seo_desc) > MAX_DESC:
        seo_desc = f"{first} Shop at Siebentaschen."
    if len(seo_desc) > MAX_DESC:
        seo_desc = seo_desc[:MAX_DESC - 1].rsplit(" ", 1)[0] + "…"
    return name, seo_title, seo_desc


# ── main ─────────────────────────────────────────────────────────────────────

Q = """query($after: String) { products(first: 50, after: $after, query: "-status:archived") {
  pageInfo { hasNextPage endCursor }
  nodes { id title vendor productType tags status descriptionHtml
    seo { title description }
    media(first: 30) { nodes { ... on MediaImage { id alt } } } } } }"""

M_PRODUCT = """mutation($p: ProductUpdateInput!) { productUpdate(product: $p) {
  userErrors { field message } } }"""
M_FILES = """mutation($f: [FileUpdateInput!]!) { fileUpdate(files: $f) {
  userErrors { field message } } }"""


def main():
    if not TOKEN:
        sys.exit("SHOPIFY_TOKEN not set")
    rows, todo_products, todo_files = [], [], []
    scanned = 0
    after = None
    while True:
        page = gql(Q, {"after": after})["products"]
        for p in page["nodes"]:
            scanned += 1
            seo = p.get("seo") or {}
            empty_imgs = [m for m in p["media"]["nodes"] if m and m.get("id") and not (m.get("alt") or "").strip()]
            need_t = not (seo.get("title") or "").strip()
            need_d = not (seo.get("description") or "").strip()
            if not (need_t or need_d or empty_imgs):
                continue
            name, st, sd = build(p)
            new_seo = {"title": st if need_t else seo["title"],
                       "description": sd if need_d else seo["description"]}
            if need_t or need_d:
                todo_products.append({"id": p["id"], "seo": new_seo})
            all_imgs = [m for m in p["media"]["nodes"] if m and m.get("id")]
            for i, m in enumerate(all_imgs):
                if m in empty_imgs:
                    todo_files.append({"id": m["id"], "alt": name if i == 0 else f"{name} – view {i + 1}"})
            rows.append({"product_id": p["id"].split("/")[-1], "status": p["status"], "title": p["title"],
                         "new_seo_title": st if need_t else "", "new_seo_description": sd if need_d else "",
                         "new_alt": name if empty_imgs else "", "images_filled": len(empty_imgs)})
            if LIMIT and len(rows) >= LIMIT:
                break
        if (LIMIT and len(rows) >= LIMIT) or not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
        print(f"  scanned {scanned} …", flush=True)

    with open("seo_preview.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["product_id"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nScanned {scanned} products.")
    print(f"{len(rows)} products need changes: {len(todo_products)} SEO title/description, "
          f"{len(todo_files)} image alt texts.")
    for r in rows[:25]:
        print(f"  {r['title'][:45]:45} -> {r['new_seo_title'] or r['new_alt']}")
    if not APPLY:
        print("\nDry run — nothing changed. See seo_preview.csv.")
        return

    errors = 0
    for i, p in enumerate(todo_products, 1):
        res = gql(M_PRODUCT, {"p": p})["productUpdate"]
        if res["userErrors"]:
            errors += 1
            print("ERROR", p["id"], res["userErrors"])
        if i % 100 == 0:
            print(f"  SEO {i}/{len(todo_products)}", flush=True)
    for i in range(0, len(todo_files), 25):
        batch = todo_files[i:i + 25]
        res = gql(M_FILES, {"f": batch})["fileUpdate"]
        if res["userErrors"]:
            errors += 1
            print("ERROR alt batch", i, res["userErrors"])
        if (i // 25) % 20 == 0:
            print(f"  alt {i + len(batch)}/{len(todo_files)}", flush=True)
    print(f"\nDone: {len(todo_products)} products, {len(todo_files)} images ({errors} errors).")


if __name__ == "__main__":
    main()
