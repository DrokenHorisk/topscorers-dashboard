import os, time, requests
from urllib.parse import unquote

# ---------- Config ----------
BASE        = "https://topscorers.ch"
EMAIL       = os.getenv("TOPS_EMAIL")
PASSWORD    = os.getenv("TOPS_PASSWORD")
LEAGUE_ID   = os.getenv("TOPS_LEAGUE_ID", "92556")

# Poll fréquence & channel discord (utilisés par bot.py)
POLL_EVERY         = int(os.getenv("BOT_POLL_SECONDS", "900"))   # 15 min par défaut
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

HEADERS_COMMON = {
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Language": "fr",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "User-Agent": "Mozilla/5.0",
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "x-app-version": "1.5.5",
}

# ---------- Login ----------
def login_session():
    if not EMAIL or not PASSWORD:
        raise RuntimeError("TOPS_EMAIL / TOPS_PASSWORD manquants.")
    s = requests.Session()
    s.headers.update(HEADERS_COMMON)

    # CSRF
    r0 = s.get(f"{BASE}/sanctum/csrf-cookie", timeout=15)
    r0.raise_for_status()
    csrf = s.cookies.get("XSRF-TOKEN")
    if not csrf:
        raise RuntimeError("Pas de XSRF-TOKEN (CSRF).")
    s.headers["X-XSRF-TOKEN"] = unquote(csrf)

    # Login
    payload = {"email": EMAIL, "password": PASSWORD}
    r1 = s.post(f"{BASE}/api/login", json=payload, timeout=20)
    if r1.status_code == 419:
        raise RuntimeError("419 CSRF mismatch")
    r1.raise_for_status()
    return s

# ---------- Market ----------
def _normalize_transfers(j):
    items = j.get("data")
    if items is None:
        for _, v in j.items():
            if isinstance(v, list):
                items = v
                break
    if items is None:
        items = []
    if isinstance(items, dict):
        items = [items]
    return items

def fetch_market(s):
    """Retourne une liste d'offres (dict) avec quelques champs utiles normalisés."""
    r = s.get(f"{BASE}/api/user/leagues/{LEAGUE_ID}/transfers", timeout=20)
    r.raise_for_status()
    items = _normalize_transfers(r.json())

    # Petites features pour l'embed
    out = []
    for it in items:
        d = dict(it)
        p = d.get("player") or {}
        mv = None
        if isinstance(p, dict):
            mv = p.get("marketvalue")
            if mv is None:
                # fallback: parfois marketvalue est au niveau racine
                mv = d.get("player.marketvalue") or d.get("marketvalue")
        price = d.get("price")
        # % décote simple si data dispo
        try:
            if mv and price:
                d["discount_pct"] = ( (mv - price) / mv ) * 100.0
        except Exception:
            pass
        out.append(d)
    return out
