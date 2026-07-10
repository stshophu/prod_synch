"""
vaitto_taxonomy.py — maps feed values to Vaitto UUID references.
Call load_brands() once at session start, then use resolve_*() functions.
"""

# ── CATEGORIES ─────────────────────────────────────────────────────────────────
CATEGORY_IDS = {
    "Clothing":    "9ad0fa3b-6630-4191-ad42-833a3416fde0",
    "Shoes":       "99f535ee-1331-4cb5-b963-2d831d13ef92",
    "Bags":        "ff381def-e899-4964-92db-8e7c25c2a7fc",
    "Accessories": "56e164a3-7815-4436-bf92-f3399b4047a4",
    "Jewelry":     "eff88827-38ad-4d6e-a693-56a66650ee43",
}
_CAT = {
    "clothing":"Clothing","apparel":"Clothing","abbigliamento":"Clothing",
    "jackets":"Clothing","jacket":"Clothing","coats":"Clothing","coat":"Clothing",
    "dresses":"Clothing","dress":"Clothing","pants":"Clothing","trousers":"Clothing",
    "jeans":"Clothing","shorts":"Clothing","skirts":"Clothing","skirt":"Clothing",
    "knitwear":"Clothing","sweaters":"Clothing","shirts":"Clothing","shirt":"Clothing",
    "polos":"Clothing","polo":"Clothing","t-shirts":"Clothing","tops":"Clothing",
    "hoodies":"Clothing","vests":"Clothing","jumpsuits":"Clothing",
    "swimwear":"Clothing","underwear":"Clothing","intimo":"Clothing",
    "shoes":"Shoes","calzature":"Shoes","scarpe":"Shoes",
    "sneakers":"Shoes","boots":"Shoes","sandals":"Shoes",
    "loafers":"Shoes","heels":"Shoes","flats":"Shoes",
    "bags":"Bags","borse":"Bags","handbags":"Bags","tote":"Bags",
    "clutch":"Bags","backpack":"Bags","crossbody":"Bags",
    "accessories":"Accessories","accessori":"Accessories",
    "wallets":"Accessories","belts":"Accessories","scarves":"Accessories",
    "hats":"Accessories","gloves":"Accessories","sunglasses":"Accessories",
    "ties":"Accessories","watches":"Accessories","hosiery":"Accessories",
    "jewelry":"Jewelry","gioielleria":"Jewelry","gioielli":"Jewelry",
    "bracelets":"Jewelry","earrings":"Jewelry","rings":"Jewelry","necklaces":"Jewelry",
}

# ── SUBCATEGORIES ──────────────────────────────────────────────────────────────
SUBCATEGORY_IDS = {
    "Backpack":"cc5a9482-cd7b-41bf-aec9-effc00d69993",
    "Belts":"2c8fa9f9-f8ea-4f07-bfbd-cd4801017f91",
    "Boots":"3da4e73b-65dc-411f-a72b-84333c5b7ca1",
    "Bracelets":"a601ef62-39d2-4541-a5ab-55264b53440d",
    "Clutch":"8f5d0136-1bf9-47f7-8b62-d80ad0e52b50",
    "Crossbody":"f4522ac4-6199-48de-a498-f0cf9e6ea484",
    "Dresses":"47c51da6-f98b-4241-a09a-8f32e955ae05",
    "Earrings":"0a796024-5aad-4a98-a8a9-291481b1ea94",
    "Flats":"cedfb795-4b57-40e2-96dd-dc1bcdb80421",
    "Gloves":"eaf4598f-447b-49c5-83cf-0c42c317c899",
    "Handbags":"5dcc7f6b-1501-4f64-b889-187300cc79c8",
    "Hats":"7d1822e7-ff8b-4da4-9c6c-56e900e69e44",
    "Heels":"d9d5b2f8-9ae6-4395-9b74-50ed2ec876b8",
    "Hoodies":"20e9220b-8eda-4785-a6bb-20166fe29202",
    "Hosiery":"26c39120-2046-405d-9570-25ac8b90a55d",
    "Jackets":"4a128ad6-cfaf-466c-a75d-d1b975115569",
    "Jeans":"6c8b8116-f5fa-48f5-a8da-1cfab2cfcb69",
    "Jumpsuits":"c8bad908-dad9-4a83-976b-e56f138e80a2",
    "Knitwear":"94546098-d2dc-425d-b58c-5d8f5fa9a3c3",
    "Loafers":"645bb508-d7a5-4e19-8878-7bc91fadbbb7",
    "Necklaces":"6da8eff6-1f4a-4ce1-ace9-1deb50708ab3",
    "Pants":"a2d88207-e237-44ee-add0-b3978537fc57",
    "Pocket Squares":"23f3a868-01aa-4592-899f-26c7820eeb4b",
    "Polos":"33d34d41-bea6-4667-923e-288dd53fb6da",
    "Rings":"8deb498c-0e2e-4597-beec-77fc11ead436",
    "Sandals":"8ba79a40-73ea-4075-9a95-61cd15c59c45",
    "Scarves":"f4f3316e-7f29-4941-afd8-2bb81b161601",
    "Shirts":"40e0597d-2017-4f0a-866f-c9971f9e2cb6",
    "Shorts":"0abb7d0f-ac23-4e79-b5c6-cff8fe6a41d6",
    "Shoulder":"38e359f4-8322-40bf-a73b-28cdaf306627",
    "Skirts":"a2a34f28-96fa-4b2f-8c45-35a9d3cfd072",
    "Sneakers":"72748281-5d72-44ae-8808-85d022aa2a64",
    "Sunglasses":"6a817ca7-fc74-4333-8a2b-0397ba885b33",
    "Swimwear":"6c874f0b-8a1c-49d1-acf4-65c39335329b",
    "T-shirts & Tops":"3f93efc4-2383-48af-8fe7-6baf63fc6bb0",
    "Ties":"1f5a66ad-7d67-43c2-9d66-68b7a56335dc",
    "Tote":"16398e34-45d4-4df6-aabe-fe79c50665d1",
    "Underwear":"7d2fb1b0-e7d2-4286-9746-bc9f9be41d1d",
    "Vests":"7cb3e006-8e2c-42ee-947a-93fd52c84565",
    "Wallet":"68e60a05-8d28-4f80-9975-db5d053712e8",
    "Watches":"c39b5dc5-9280-421c-9f16-a43831887111",
}
_SUB = {
    "jackets":"Jackets","jacket":"Jackets","giacche":"Jackets","giubbini":"Jackets",
    "coats":"Jackets","coat":"Jackets","cappotti":"Jackets","trench":"Jackets",
    "down jackets":"Jackets","piumini":"Jackets","bomber":"Jackets","blazer":"Jackets",
    "dresses":"Dresses","dress":"Dresses","abiti":"Dresses",
    "pants":"Pants","trousers":"Pants","pantaloni":"Pants","sweatpants":"Pants",
    "jeans":"Jeans",
    "shorts":"Shorts","pantaloncini":"Shorts","bermuda":"Shorts",
    "skirts":"Skirts","skirt":"Skirts","gonne":"Skirts",
    "knitwear":"Knitwear","maglie":"Knitwear","maglieria":"Knitwear",
    "sweaters":"Knitwear","sweater":"Knitwear","maglioni":"Knitwear",
    "cardigans":"Knitwear","cardigan":"Knitwear","turtlenecks":"Knitwear",
    "sweatshirts":"Knitwear","felpe":"Knitwear","pullover":"Knitwear",
    "shirts":"Shirts","shirt":"Shirts","camicie":"Shirts",
    "polo":"Polos","polo shirts":"Polos","polos":"Polos",
    "t-shirts":"T-shirts & Tops","t-shirt":"T-shirts & Tops",
    "tops":"T-shirts & Tops","top":"T-shirts & Tops",
    "t-shirts & tops":"T-shirts & Tops","tank tops":"T-shirts & Tops",
    "hoodies":"Hoodies","hoodie":"Hoodies",
    "vests":"Vests","vest":"Vests","gilet":"Vests","smanicati":"Vests",
    "jumpsuits":"Jumpsuits","tute":"Jumpsuits","suits":"Jumpsuits",
    "swimwear":"Swimwear","costumi":"Swimwear","bikinis":"Swimwear","bikini":"Swimwear",
    "underwear":"Underwear","intimo":"Underwear",
    "sneakers":"Sneakers","sneaker":"Sneakers",
    "boots":"Boots","stivali":"Boots","ankle boots":"Boots","stivaletti":"Boots",
    "sandals":"Sandals","sandali":"Sandals",
    "loafers":"Loafers","mocassini":"Loafers","espadrilles":"Loafers",
    "heels":"Heels","decollete":"Heels","pumps":"Heels",
    "flats":"Flats","ballerine":"Flats","ballet flats":"Flats",
    "handbags":"Handbags","borse a mano":"Handbags",
    "shoulder bags":"Shoulder","borse a spalla":"Shoulder",
    "crossbody":"Crossbody","borse a tracolla":"Crossbody",
    "clutch":"Clutch","clutches":"Clutch","pochette":"Clutch",
    "tote":"Tote","tote bags":"Tote",
    "backpack":"Backpack","backpacks":"Backpack","zaini":"Backpack","belt bags":"Backpack",
    "wallets":"Wallet","wallet":"Wallet","portafogli":"Wallet","card holders":"Wallet",
    "belts":"Belts","belt":"Belts","cinture":"Belts",
    "scarves":"Scarves","scarf":"Scarves","sciarpe":"Scarves",
    "hats":"Hats","hat":"Hats","cappelli":"Hats","caps":"Hats",
    "gloves":"Gloves","guanti":"Gloves",
    "sunglasses":"Sunglasses","occhiali da sole":"Sunglasses",
    "ties":"Ties","tie":"Ties","cravatte":"Ties","bow ties":"Ties",
    "pocket squares":"Pocket Squares","fazzoletti":"Pocket Squares",
    "hosiery":"Hosiery","socks":"Hosiery","calze":"Hosiery",
    "bracelets":"Bracelets","bracciali":"Bracelets",
    "earrings":"Earrings","orecchini":"Earrings",
    "rings":"Rings","necklaces":"Necklaces","watches":"Watches",
}

# ── GENDER ─────────────────────────────────────────────────────────────────────
_GENDER = {
    "men":"Men","man":"Men","uomo":"Men","uoomo":"Men","m":"Men",
    "women":"Women","woman":"Women","donna":"Women","f":"Women",
    "unisex":"Unisex","u":"Unisex",
    "kids":"Kids","junior":"Kids","bambino":"Kids","bambina":"Kids",
}

# ── BRAND CACHE ────────────────────────────────────────────────────────────────
_brands: dict = {}  # name.lower() → uuid
_unknown_id: str = ""

def load_brands(db_url: str = None, *args) -> dict:
    """Load all brands from DB into cache via direct Postgres connection."""
    global _brands, _unknown_id
    import psycopg2
    url = db_url or os.environ.get("VAITTO_DB_URL", "")
    if not url:
        return {}
    try:
        with psycopg2.connect(url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name FROM brands WHERE active = true")
                for row in cur.fetchall():
                    bid, bname = row
                    _brands[bname.strip().lower()] = str(bid)
                    if bname.strip().lower() == "unknown":
                        _unknown_id = str(bid)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Brand load failed: {e}")
    return _brands

# ── PUBLIC RESOLVERS ───────────────────────────────────────────────────────────

def resolve_brand(name: str, *args) -> str | None:
    """Returns brand UUID or None if not found."""
    if not name:
        return _unknown_id or None
    return _brands.get(name.strip().lower()) or _unknown_id or None

def resolve_category(raw: str) -> str | None:
    if not raw: return None
    key = raw.strip().lower()
    name = _CAT.get(key)
    if not name:
        for k, v in _CAT.items():
            if k in key:
                name = v; break
    return CATEGORY_IDS.get(name) if name else None

def resolve_subcategory(raw: str) -> str | None:
    if not raw: return None
    key = raw.strip().lower()
    name = _SUB.get(key)
    if not name:
        for k, v in _SUB.items():
            if k in key:
                name = v; break
    return SUBCATEGORY_IDS.get(name) if name else None

def resolve_gender(raw: str) -> str | None:
    if not raw: return None
    return _GENDER.get(raw.strip().lower())
