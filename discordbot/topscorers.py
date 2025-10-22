import os, time, io
import requests
import pandas as pd
import numpy as np
from urllib.parse import unquote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------- Config ----------
BASE = "https://topscorers.ch"
POLL_EVERY = int(os.getenv("POLL_EVERY", "60"))
LEAGUE_ID = os.getenv("TOPS_LEAGUE_ID", "92556")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0")) or None

TOPS_EMAIL = os.getenv("TOPS_EMAIL")
TOPS_PASSWORD = os.getenv("TOPS_PASSWORD")

HEADERS_COMMON = {
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Language": "fr",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "User-Agent": "Mozilla/5.0",
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "x-app-version": "1.5.5",
    "Connection": "keep-alive",
}

# ---------- Session / Login ----------
def _mount_retries(session: requests.Session) -> None:
    retry = Retry(
        total=5, connect=5, read=5,
        backoff_factor=0.6,  # 0.6, 1.2, 1.8, ...
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset({"GET","POST","PUT","DELETE","HEAD","OPTIONS","PATCH"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

def _csrf_and_login(session: requests.Session) -> None:
    r0 = session.get(f"{BASE}/sanctum/csrf-cookie", timeout=(5, 15))
    r0.raise_for_status()
    csrf = session.cookies.get("XSRF-TOKEN")
    if not csrf:
        raise RuntimeError("Pas de XSRF-TOKEN (CSRF).")
    session.headers["X-XSRF-TOKEN"] = unquote(csrf)

    payload = {"email": TOPS_EMAIL, "password": TOPS_PASSWORD}
    r1 = session.post(f"{BASE}/api/login", json=payload, timeout=(5, 20))
    if r1.status_code == 419:
        # CSRF mismatch -> on ré-essaie une fois la séquence CSRF
        r0b = session.get(f"{BASE}/sanctum/csrf-cookie", timeout=(5, 15))
        r0b.raise_for_status()
        csrf = session.cookies.get("XSRF-TOKEN")
        session.headers["X-XSRF-TOKEN"] = unquote(csrf) if csrf else ""
        r1 = session.post(f"{BASE}/api/login", json=payload, timeout=(5, 20))
    r1.raise_for_status()

def login_session() -> requests.Session:
    if not TOPS_EMAIL or not TOPS_PASSWORD:
        raise RuntimeError("TOPS_EMAIL / TOPS_PASSWORD manquants dans l'env")
    s = requests.Session()
    s.headers.update(HEADERS_COMMON)
    _mount_retries(s)
    _csrf_and_login(s)
    return s

def _relogin_inplace(sess: requests.Session) -> bool:
    try:
        _csrf_and_login(sess)
        return True
    except Exception:
        return False

# ---------- Market ----------
def fetch_market(sess):
    """Récupère les transferts du marché de la ligue, avec retries manuels + relogin si besoin."""
    url = f"{BASE}/api/user/leagues/{int(LEAGUE_ID)}/transfers"
    for attempt in range(3):
        try:
            r = sess.get(url, timeout=(5, 25))
            if r.status_code in (401, 419):
                if _relogin_inplace(sess):
                    r = sess.get(url, timeout=(5, 25))
            r.raise_for_status()
            j = r.json()
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
        except requests.RequestException:
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise

# ---------- Price history ----------
def _extract_price_series_from_player_payload(detail_json: dict) -> pd.Series:
    if not isinstance(detail_json, dict):
        return pd.Series(dtype="float64")
    d = detail_json.get("data") if "data" in detail_json else detail_json
    mv = (d or {}).get("marketvalue_metrics") or []
    if not isinstance(mv, list) or not mv:
        return pd.Series(dtype="float64")
    try:
        dt_index = pd.to_datetime([x.get("measured_at") for x in mv], utc=True, errors="coerce")
        vals = pd.to_numeric([x.get("measured_value") for x in mv], errors="coerce")
        s = pd.Series(vals, index=dt_index).dropna()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        return s
    except Exception:
        return pd.Series(dtype="float64")

def fetch_price_series(sess, player_id: int) -> pd.Series:
    url = f"{BASE}/api/players/{int(player_id)}"
    for attempt in range(3):
        try:
            r = sess.get(url, timeout=(5, 20))
            if r.status_code in (401, 419):
                if _relogin_inplace(sess):
                    r = sess.get(url, timeout=(5, 20))
            if r.status_code == 404:
                return pd.Series(dtype="float64")
            r.raise_for_status()
            return _extract_price_series_from_player_payload(r.json())
        except requests.RequestException:
            if attempt < 2:
                time.sleep(1.2 * (attempt + 1))
                continue
            return pd.Series(dtype="float64")

# ---------- Features + image (Y-min = 60'000) ----------
def _price_features_from_series(s: pd.Series):
    """
    Retourne: mv90, mvmax, mvmin, momentum, png_bytes
    Le graphique PNG force un Y-min strict à 60'000.
    """
    import matplotlib.pyplot as plt

    if s is None or s.empty:
        return None, None, None, None, None

    s = s.sort_index().dropna().astype(float)
    now = pd.Timestamp.now(tz="UTC")

    # MV 90j (fallback moyenne globale)
    s90 = s.loc[s.index >= (now - pd.Timedelta(days=90))]
    mv90 = float(s90.mean()) if not s90.empty else float(s.mean())

    # Min/Max 365j (fallback global)
    s365 = s.loc[s.index >= (now - pd.Timedelta(days=365))]
    mvmax = float(s365.max()) if not s365.empty else float(s.max())
    mvmin = float(s365.min()) if not s365.empty else float(s.min())

    # Momentum 30j
    s_mom = s.loc[s.index >= (now - pd.Timedelta(days=30))]
    momentum = None
    if len(s_mom) >= 2:
        first = float(s_mom.iloc[0]); last = float(s_mom.iloc[-1])
        if first != 0:
            momentum = (last - first) / abs(first) * 100.0

    # Graph
    try:
        fig, ax = plt.subplots(figsize=(7, 2.3), dpi=180)
        ax.plot(s.index, s.values, linewidth=2)
        ax.grid(True, alpha=0.25, linestyle="--")
        ax.set_xlabel("")
        ax.set_ylabel("")

        y_min = 60000.0
        vmax = float(np.nanmax(s.values)) if np.isfinite(np.nanmax(s.values)) else 70000.0
        y_max = max(vmax * 1.05, y_min * 1.05)
        ax.set_ylim(y_min, y_max)

        for spine in ax.spines.values():
            spine.set_alpha(0.4)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        png = buf.getvalue()
    except Exception:
        png = None

    return mv90, mvmax, mvmin, momentum, png
