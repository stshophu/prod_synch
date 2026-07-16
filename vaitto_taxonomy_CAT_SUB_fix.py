# ── PATCH: add these missing entries to _CAT in vaitto_taxonomy.py ─────────────
# (Every plural-only or singular-only entry below gets its missing counterpart.
#  "purse" was entirely absent from both _CAT and _SUB — added as Bags/Handbags.)

_CAT_ADDITIONS = {
    # Clothing — missing singulars
    "sweater":"Clothing",
    "t-shirt":"Clothing",
    "top":"Clothing",
    "hoodie":"Clothing",
    "vest":"Clothing",
    "jumpsuit":"Clothing",

    # Shoes — missing singulars
    "shoe":"Shoes",
    "sneaker":"Shoes",
    "boot":"Shoes",
    "sandal":"Shoes",
    "loafer":"Shoes",
    "heel":"Shoes",
    "flat":"Shoes",

    # Bags — missing singulars/variants, incl. Purse which was absent entirely
    "handbag":"Bags",
    "purse":"Bags",
    "shoulder bag":"Bags",
    "shoulder bags":"Bags",

    # Accessories — missing singulars
    "wallet":"Accessories",
    "belt":"Accessories",
    "scarf":"Accessories",
    "hat":"Accessories",
    "glove":"Accessories",
    "tie":"Accessories",
    "watch":"Accessories",

    # Jewelry — missing singulars
    "bracelet":"Jewelry",
    "earring":"Jewelry",
    "ring":"Jewelry",
    "necklace":"Jewelry",
}

# ── PATCH: add this to _SUB in vaitto_taxonomy.py ──────────────────────────────
# "Purse" had zero coverage in _SUB, so subcategory_id was also None for it.
# Mapping to "Handbags" since that's the closest existing subcategory bucket —
# confirm this is the right bucket for your storefront before merging.

_SUB_ADDITIONS = {
    "purse":"Handbags",
    "purses":"Handbags",
}
