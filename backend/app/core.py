# core.py — logique métier / API TopScorers, scoring, agrégations
import os, sys, time, json, math
import pandas as pd
import numpy as np
import requests
import datetime as dt
from urllib.parse import unquote
from dotenv import load_dotenv
from typing import Tuple, List, Dict, Any

# Chargement .env
load_dotenv()
pd.set_option('future.no_silent_downcasting', True)

# ----------------- CONFIG -----------------
BASE = "https://topscorers.ch"
EMAIL          = os.getenv("TOPS_EMAIL")
PASSWORD       = os.getenv("TOPS_PASSWORD")
LEAGUE_ID      = os.getenv("TOPS_LEAGUE_ID", "92556")
TEAM_ID        = (os.getenv("TOPS_TEAM_ID") or "506387").strip()
TEAM_QUERY     = (os.getenv("TOPS_TEAM_QUERY") or "").strip()
RECO_BUDGET    = int(os.getenv("RECO_BUDGET", "10000000"))

# Poids AlphaScore
ALPHA_W_VALUE   = float(os.getenv("ALPHA_W_VALUE",  "0.30"))
ALPHA_W_EFF     = float(os.getenv("ALPHA_W_EFF",    "0.20"))
ALPHA_W_FORM    = float(os.getenv("ALPHA_W_FORM",   "0.20"))
ALPHA_W_CONSIST = float(os.getenv("ALPHA_W_CONSIST","0.10"))
ALPHA_W_USAGE   = float(os.getenv("ALPHA_W_USAGE",  "0.10"))
ALPHA_W_CTX     = float(os.getenv("ALPHA_W_CTX",    "0.07"))
ALPHA_W_MARKET  = float(os.getenv("ALPHA_W_MARKET", "0.03"))

# Forme multi-saisons
FORM_W_CUR = float(os.getenv("FORM_W_CUR", "0.6"))
FORM_W_N1  = float(os.getenv("FORM_W_N1",  "0.3"))
FORM_W_N2  = float(os.getenv("FORM_W_N2",  "0.1"))

# Ajustements
FOREIGNER_PENALTY = float(os.getenv("FOREIGNER_PENALTY", "0.03"))
OFFERS_PENALTY    = float(os.getenv("OFFERS_PENALTY",    "0.02"))
EXPIRY_BOOST_HRS  = float(os.getenv("EXPIRY_BOOST_HOURS","6"))

MUST_BUY_THRESHOLD_FALLBACK = float(os.getenv("MUST_BUY_THRESHOLD", "85"))

# Historique valeurs
ADD_PRICE_FEATURES  = os.getenv("ADD_PRICE_FEATURES", "1").strip().lower() in ("1","true","yes","on")
PRICE_WINDOW_DAYS   = int(os.getenv("PRICE_WINDOW_DAYS", "180"))
PRICE_MOMENTUM_DAYS = int(os.getenv("PRICE_MOMENTUM_DAYS", "30"))

# Équipes pour "Tous les joueurs"
DEFAULT_TEAMS = [103144,101152,102126,101150,101149,102127,102128,101139,101144,103138,103140,103141,101060,101151]
ALL_PLAYERS_TEAMS_ENV = os.getenv("ALL_PLAYERS_TEAMS", "").strip()
ALL_PLAYERS_FETCH_DETAILS = os.getenv("ALL_PLAYERS_FETCH_DETAILS", "1").strip().lower() in ("1","true","yes","on")

# Équipes des autres managers
OTHER_TEAM_IDS_ENV   = os.getenv("OTHER_TEAM_IDS", "").strip()
OTHER_TEAM_NAMES_ENV = os.getenv("OTHER_TEAM_NAMES", "").strip()
SHOW_ME_AS_USERNAME  = os.getenv("SHOW_ME_AS_USERNAME", "1").strip().lower() in ("1","true","yes","on")

TEAM_LOGO_URL  = os.getenv("TEAM_LOGO_URL","https://assets.topscorers.ch/img/cache/t672/logos/103141.png")

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
TEAM_USERNAME_CACHE: Dict[int,str] = {}

# Import du rendu HTML (génération de page + tableaux)
from .html import build_html_page, df_to_html_table

# ----------------- HELPERS -----------------
def require(v, name):
    if not v:
        raise RuntimeError(f"❌ Variable manquante: {name} (cf. .env / Secret)")
    return v

def login_session():
    require(EMAIL, "TOPS_EMAIL")
    require(PASSWORD, "TOPS_PASSWORD")
    s = requests.Session()
    s.headers.update(HEADERS_COMMON)
    r0 = s.get(f"{BASE}/sanctum/csrf-cookie", timeout=15)
    r0.raise_for_status()
    csrf = s.cookies.get("XSRF-TOKEN")
    if not csrf:
        raise RuntimeError("Pas de XSRF-TOKEN (CSRF).")
    s.headers["X-XSRF-TOKEN"] = unquote(csrf)
    payload = {"email": EMAIL, "password": PASSWORD}
    r1 = s.post(f"{BASE}/api/login", json=payload, timeout=20)
    if r1.status_code == 419:
        raise RuntimeError("419 CSRF mismatch — vérifie headers/cookies.")
    r1.raise_for_status()
    return s

def sanitize_for_html(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    df2 = df.copy()
    if "offers" in df2.columns:
        df2["Offres (#)"] = df2["offers"].apply(lambda v: len(v) if isinstance(v, list) else 0)
        df2 = df2.drop(columns=["offers"])
    drop_cols = [c for c in df2.columns if any(k in c for k in ["portrait_image","logo","logo_lg","portrait_image_lg"])]
    if drop_cols:
        df2 = df2.drop(columns=drop_cols)
    for c in df2.columns:
        df2[c] = df2[c].apply(lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":")) if isinstance(x,(list,dict)) else x)
    return df2

def _parse_ids_list(env_str):
    out = []
    if not env_str: return out
    for tok in env_str.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok: continue
        try: out.append(int(tok))
        except: pass
    return list(dict.fromkeys(out))

def _parse_team_ids_env(env_str: str, fallback_ids):
    if not env_str:
        return list(dict.fromkeys(fallback_ids))
    out = []
    for tok in env_str.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok: continue
        try: out.append(int(tok))
        except: pass
    return list(dict.fromkeys(out)) or list(dict.fromkeys(fallback_ids))

def _parse_owner_name_overrides(env_str):
    m = {}
    if not env_str: return m
    for part in env_str.split(","):
        part = part.strip()
        if "=" in part:
            k,v = part.split("=",1)
            try: m[int(k.strip())] = v.strip()
            except: pass
    return m

# ---- NUMERIC SAFETY HELPERS ----
def _num_series(df: pd.DataFrame, col: str):
    if isinstance(df, pd.DataFrame) and col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    if isinstance(df, pd.Series):
        return pd.to_numeric(df, errors="coerce")
    try:
        n = len(df)
        return pd.Series([np.nan]*n, index=df.index, dtype="float64")
    except Exception:
        return pd.Series(dtype="float64")

# ----------------- PRICE HISTORY -----------------
def _parse_marketvalue_series(detail_json: dict) -> pd.Series:
    if not isinstance(detail_json, dict):
        return pd.Series(dtype="float64")
    d = detail_json.get("data") if "data" in detail_json else detail_json
    mv = d.get("marketvalue_metrics") or []
    if not isinstance(mv, list) or not mv:
        return pd.Series(dtype="float64")
    try:
        dt_index = pd.to_datetime([x.get("measured_at") for x in mv], utc=True, errors="coerce")
        vals     = pd.to_numeric([x.get("measured_value") for x in mv], errors="coerce")
        s = pd.Series(vals, index=dt_index).dropna()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        return s
    except Exception:
        return pd.Series(dtype="float64")

def _spark_svg(series: pd.Series, width=180, height=40, stroke="#19C37D") -> str:
    if series is None or series.empty:
        return ""
    s = series.dropna().astype(float)
    if s.empty:
        return ""
    x = np.linspace(0, width, num=len(s))
    y_raw = s.values
    y_min, y_max = float(np.min(y_raw)), float(np.max(y_raw))
    if y_max == y_min:
        y = np.full_like(x, height/2.0)
    else:
        y = height - ((y_raw - y_min) / (y_max - y_min)) * (height - 4) - 2
    points = " ".join(f"{x[i]:.1f},{y[i]:.1f}" for i in range(len(x)))
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <polyline fill="none" stroke="{stroke}" stroke-width="2" points="{points}"/>
</svg>"""

def _price_features_from_series(s: pd.Series):
    """
    Retourne:
      mv90 (moyenne 90 j, sinon moyenne globale),
      mvmax365 (max 365 j, sinon max global),
      mvmin365 (min 365 j, sinon min global),
      momentum 30j (% si possible),
      spark_svg (toujours, basé sur fenêtre récente si possible, sinon global)
    """
    if s is None or s.empty:
        return None, None, None, None, ""
    now = pd.Timestamp.now(tz="UTC")
    s = s.sort_index()

    # 90 j -> fallback global
    s90   = s.loc[s.index >= (now - pd.Timedelta(days=90))]
    mv90  = float(s90.mean()) if not s90.empty else float(s.mean())

    # 365 j -> fallback global
    s365  = s.loc[s.index >= (now - pd.Timedelta(days=365))]
    mvmax = float(s365.max()) if not s365.empty else float(s.max())
    mvmin = float(s365.min()) if not s365.empty else float(s.min())

    # Momentum 30 j si au moins 2 points, sinon None
    s_tail = s.loc[s.index >= (now - pd.Timedelta(days=PRICE_MOMENTUM_DAYS))]
    momentum = None
    if len(s_tail) >= 2:
        first = float(s_tail.iloc[0]); last  = float(s_tail.iloc[-1])
        if first != 0: momentum = (last - first) / abs(first) * 100.0

    # Sparkline: fenêtre PRICE_WINDOW_DAYS, sinon global
    swin = s.loc[s.index >= (now - pd.Timedelta(days=PRICE_WINDOW_DAYS))]
    if swin.empty: swin = s
    swin = swin.ffill(limit=3)
    spark = _spark_svg(swin)
    return mv90, mvmax, mvmin, momentum, spark

# ----------------- API FETCHES -----------------
def fetch_player_detail(s, player_id:int) -> dict:
    r = s.get(f"{BASE}/api/players/{player_id}", timeout=20)
    if r.status_code == 404:
        return {"data": None, "error": "not_found", "player_id": player_id}
    if r.status_code != 200:
        time.sleep(0.3); r = s.get(f"{BASE}/api/players/{player_id}", timeout=20)
    r.raise_for_status()
    return r.json()

def parse_player_seasons(detail_json: dict):
    out = {"cur_games": None, "cur_avg": None, "n1_games": None, "n1_avg": None, "n2_games": None, "n2_avg": None}
    if not isinstance(detail_json, dict): return out
    d = detail_json.get("data") if "data" in detail_json else detail_json
    pm = d.get("point_metrics") or []
    if not isinstance(pm, list) or not pm:
        ss = d.get("stats_summary") or []
        smap = {x.get("key"): x.get("value") for x in ss if isinstance(x, dict)}
        out["cur_games"] = smap.get("games")
        out["cur_avg"] = d.get("points_avg")
        return out
    try:
        pm_sorted = sorted(pm, key=lambda x: x.get("season", 0), reverse=True)
    except Exception:
        pm_sorted = pm

    def _avg_safe(x):
        if x is None: return None
        if "points_avg" in x and x["points_avg"] is not None:
            return x["points_avg"]
        try:
            pts = float(x.get("points")) if x.get("points") is not None else None
            gms = float(x.get("games")) if x.get("games") is not None else None
            if pts is not None and gms and gms > 0: return pts / gms
        except Exception:
            pass
        return None

    slots = [("cur_", 0), ("n1_", 1), ("n2_", 2)]
    for prefix, idx in slots:
        if idx < len(pm_sorted):
            item = pm_sorted[idx]
            out[prefix + "games"] = item.get("games")
            out[prefix + "avg"]   = _avg_safe(item)
    if out["cur_avg"] is None and d.get("points_avg") is not None:
        out["cur_avg"] = d.get("points_avg")
    return out

def fetch_rankings_maps(s):
    try:
        r = s.get(f"{BASE}/api/rankings", timeout=20)
        if r.status_code != 200: return {}, {}, {}
        j = r.json()
        data = j.get("data") or {}
        teams = data.get("teams") or []
        games_by_id, acr_by_id, pav_by_id = {}, {}, {}
        for t in teams:
            tid = t.get("id")
            if tid is None: continue
            tid = int(tid)
            games_by_id[tid] = t.get("games")
            acr_by_id[tid]   = t.get("acronym") or t.get("name")
            pav = t.get("points_avg")
            try: pav_by_id[tid] = float(pav) if pav is not None else None
            except: pav_by_id[tid] = None
        return games_by_id, acr_by_id, pav_by_id
    except Exception:
        return {}, {}, {}

def _extract_username_from_payload(d):
    if not isinstance(d, dict): return ""
    v = d.get("username")
    if isinstance(v, str) and v.strip(): return v.strip()
    for k in ("user","owner","account"):
        obj = d.get(k)
        if isinstance(obj, dict):
            for kk in ("username","name","display_name","nickname"):
                v = obj.get(kk)
                if isinstance(v,str) and v.strip(): return v.strip()
    return ""

def fetch_my_team_views(s):
    try:
        j = None
        if TEAM_ID:
            r = s.get(f"{BASE}/api/user/teams/{TEAM_ID}", timeout=20)
            if r.status_code == 200: j = r.json()
        if j is None and TEAM_QUERY:
            r = s.get(f"{BASE}/api/user/teams", params={"team": TEAM_QUERY}, timeout=20)
            if r.status_code == 200: j = r.json()
        if not j: return pd.DataFrame(), pd.DataFrame(), ""
        data = j.get("data", j)
        if isinstance(data, list): data = data[0] if data else {}
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), ""

    my_username = _extract_username_from_payload(data)
    players = data.get("players", []) or []
    lineup  = data.get("lineup", []) or []

    rows = []
    for p in players:
        team = (p.get("team") or {})
        rows.append({
            "ID": p.get("id"),
            "Joueur": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
            "Poste": p.get("position_name"),
            "Équipe": team.get("acronym") or team.get("name"),
            "Points": p.get("points"),
            "Pts moy.": p.get("points_avg"),
            "Valeur": p.get("marketvalue"),
            "Étranger": "Étranger" if bool(p.get("is_foreigner")) else "",
        })
    df_effectif = pd.DataFrame(rows)

    id2name = {p.get("id"): f"{p.get('firstname','')} {p.get('lastname','')}".strip() for p in players}
    line_rows = []
    for slot in lineup:
        pos_id = slot.get("position_id")
        cur_id = slot.get("current")
        avail  = slot.get("available") or []
        pool   = slot.get("lined_up") or []
        line_rows.append({
            "Slot": pos_id,
            "Actuel": id2name.get(cur_id, cur_id),
            "Banc dispo (#)": len(avail),
            "Candidats (#)": len(pool),
        })
    df_lineup = pd.DataFrame(line_rows).sort_values("Slot")
    return df_effectif, df_lineup, my_username

def fetch_team_username(s, team_id:int) -> str:
    try:
        tid = int(team_id)
    except Exception:
        return ""
    if tid in TEAM_USERNAME_CACHE:
        return TEAM_USERNAME_CACHE[tid]
    try:
        r = s.get(f"{BASE}/api/user/teams/{tid}/stats", timeout=15)
        if r.status_code == 200:
            j = r.json()
            d = j.get("data", j)
            u = (d.get("username") or "").strip()
            TEAM_USERNAME_CACHE[tid] = u
            return u
    except Exception:
        pass
    try:
        r = s.get(f"{BASE}/api/user/teams/{tid}", timeout=15)
        if r.status_code == 200:
            j = r.json()
            d = j.get("data", j)
            u = (d.get("username") or "").strip()
            if not u and isinstance(d.get("user"), dict):
                u = (d["user"].get("username") or d["user"].get("name") or "").strip()
            TEAM_USERNAME_CACHE[tid] = u
            return u
    except Exception:
        pass
    TEAM_USERNAME_CACHE[tid] = ""
    return ""

def fetch_players_of_user_team(s, team_id:int):
    try:
        r = s.get(f"{BASE}/api/user/teams/{team_id}/players", timeout=20)
        if r.status_code != 200:
            return []
        j = r.json()
        data = j.get("data", j)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def build_owners_index(s, my_effectif_df: pd.DataFrame, other_team_ids: list, owner_overrides: dict, my_username: str):
    owners = {}
    me_label = my_username if SHOW_ME_AS_USERNAME and my_username else "Moi"
    if my_effectif_df is not None and not my_effectif_df.empty and "ID" in my_effectif_df.columns:
        try:
            for pid in pd.to_numeric(my_effectif_df["ID"], errors="coerce").dropna().astype(int).tolist():
                owners[pid] = me_label
        except Exception:
            pass
    for tid in other_team_ids:
        username = fetch_team_username(s, tid) or owner_overrides.get(tid, "")
        label = username if username else f"Équipe {tid}"
        players = fetch_players_of_user_team(s, tid)
        for p in players:
            pid = p.get("id")
            if isinstance(pid, int):
                owners[pid] = label
        time.sleep(0.05)
    return owners

def fetch_team_roster(s, team_id: int) -> list:
    try:
        r = s.get(f"{BASE}/api/players", params={"team": int(team_id)}, timeout=20)
        if r.status_code != 200:
            return []
        j = r.json()
        data = j.get("data", j)
        return data if isinstance(data, list) else []
    except Exception:
        return []

# ----------------- NUM HELPERS -----------------
def _winsor_rankpct(s: pd.Series, lo=0.05, hi=0.95):
    s = pd.to_numeric(s, errors="coerce")
    if isinstance(s, pd.Series): x = s.copy()
    else: x = pd.Series([s], dtype="float64")
    if x.dropna().empty:
        return pd.Series([None]*len(x), index=x.index)
    ql, qh = x.quantile(lo), x.quantile(hi)
    x = x.clip(lower=ql, upper=qh)
    ranks = x.rank(pct=True)
    return ranks

def _safe_div(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    return a / b.replace({0: np.nan})

def _asfloat(s, fill=0.0):
    if isinstance(s, pd.Series):
        return pd.to_numeric(s, errors="coerce").fillna(fill).astype(float)
    try:
        return float(s)
    except Exception:
        return float(fill)

def _round_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty: return df
    df = df.copy()
    num_cols = df.select_dtypes(include="number").columns.tolist()
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").round(2)
    return df

def blended_form(cur_avg, n1_avg, n2_avg, w_cur=FORM_W_CUR, w_n1=FORM_W_N1, w_n2=FORM_W_N2):
    vals, w = [], 0.0
    if pd.notna(cur_avg): vals.append((float(cur_avg), w_cur)); w += w_cur
    if pd.notna(n1_avg):  vals.append((float(n1_avg),  w_n1));  w += w_n1
    if pd.notna(n2_avg):  vals.append((float(n2_avg),  w_n2));  w += w_n2
    if not vals or w == 0: return None
    return sum(v*wt for v,wt in vals) / w

# ----------------- ALPHASCORE (affiché seulement) -----------------
def compute_alpha_score(df):
    if df is None or df.empty: return df
    df = df.copy()

    disc   = _num_series(df, "Décote (%)")
    eff    = _num_series(df, "Pts / 100k")
    cur    = _num_series(df, "Pts moy. (saison)")
    base   = _num_series(df, "Pts moy.")
    cur    = cur.fillna(base)

    n1     = _num_series(df, "Pts moy. N-1")
    n2     = _num_series(df, "Pts moy. N-2")
    m_j    = _num_series(df, "Matchs (saison)")
    m_t    = _num_series(df, "Matchs (équipe)")
    usage  = _safe_div(m_j, m_t)
    team_ctx = _num_series(df, "Team PtsAvg") if "Team PtsAvg" in df.columns else pd.Series([np.nan]*len(df), index=df.index, dtype="float64")
    offers = _num_series(df, "Offres (#)") if "Offres (#)" in df.columns else pd.Series([np.nan]*len(df), index=df.index, dtype="float64")
    exp_s  = _num_series(df, "Expire dans (s)") if "Expire dans (s)" in df.columns else pd.Series([np.nan]*len(df), index=df.index, dtype="float64")

    if "Étranger" in df.columns:
        is_foreigner = df["Étranger"].astype(str).str.lower().str.contains("étranger")
    else:
        is_foreigner = pd.Series([False]*len(df), index=df.index)

    form_multi = []
    for a,b,c in zip(cur, n1, n2):
        form_multi.append(blended_form(a, b, c))
    df["Forme (multi)"] = pd.Series(form_multi, index=df.index)

    tmp_cons = []
    for a,b,c in zip(cur, n1, n2):
        arr = [v for v in [a,b,c] if pd.notna(v)]
        if len(arr) < 2: tmp_cons.append(None)
        else:
            s = pd.Series(arr); std = s.std()
            tmp_cons.append(1/(1+std) if std==std else None)
    df["Régularité"] = pd.Series(tmp_cons, index=df.index)

    n_disc  = _asfloat(_winsor_rankpct(disc))
    n_eff   = _asfloat(_winsor_rankpct(eff))
    n_form  = _asfloat(_winsor_rankpct(df["Forme (multi)"]))
    n_cons  = _asfloat(_winsor_rankpct(df["Régularité"]))
    n_usage = _asfloat(_winsor_rankpct(usage))
    n_ctx   = _asfloat(_winsor_rankpct(team_ctx)) if team_ctx is not None else _asfloat(pd.Series([None]*len(df), index=df.index))

    market_adj = pd.Series(0.0, index=df.index, dtype="float64")
    if "Offres (#)" in df.columns:
        market_adj = market_adj - OFFERS_PENALTY*(_asfloat(offers)>0).astype(float)
    if "Expire dans (s)" in df.columns:
        hours = _asfloat(exp_s)/3600.0
        soon  = (hours <= EXPIRY_BOOST_HRS).astype(float)
        market_adj = market_adj + 0.01*soon

    foreign_adj = - FOREIGNER_PENALTY * _asfloat(is_foreigner.astype(float))

    base_score = (
        ALPHA_W_VALUE   * n_disc +
        ALPHA_W_EFF     * n_eff  +
        ALPHA_W_FORM    * n_form +
        ALPHA_W_CONSIST * n_cons +
        ALPHA_W_USAGE   * n_usage+
        ALPHA_W_CTX     * n_ctx
    )
    score = base_score + (ALPHA_W_MARKET * _asfloat(market_adj)) + _asfloat(foreign_adj)
    score = _asfloat(score).clip(lower=0.0, upper=1.0)
    df["AlphaScore"] = (score*100.0).round(1)

    # Badges
    if "Étranger" in df.columns:
        df["Étranger"] = df["Étranger"].apply(lambda x: f"<span class='badge-chip chip-foreign'>Étranger</span>" if isinstance(x,str) and x.strip() else "")
    if "Propriétaire" in df.columns:
        df["Propriétaire"] = df["Propriétaire"].apply(lambda x: f"<span class='badge-chip chip-owner'>{x}</span>" if isinstance(x,str) and x.strip() else "")

    df["Usage"] = _safe_div(_num_series(df,"Matchs (saison)"),
                            _num_series(df,"Matchs (équipe)")).round(3)
    return _round_metrics(df).sort_values("AlphaScore", ascending=False)

# ----------------- MARKET FETCH + PRICE FEATURES -----------------
def fetch_market_enriched(s):
    r = s.get(f"{BASE}/api/user/leagues/{LEAGUE_ID}/transfers", timeout=20)
    r.raise_for_status()
    j = r.json()
    items = j.get("data")
    if items is None:
        for _, v in j.items():
            if isinstance(v, list): items=v; break
    if items is None: items=[]
    if isinstance(items, dict): items=[items]
    base = pd.json_normalize(items, sep='.')
    # enrich
    if "player.marketvalue" in base.columns and "price" in base.columns:
        mv = pd.to_numeric(base["player.marketvalue"], errors="coerce")
        pr = pd.to_numeric(base["price"], errors="coerce")
        base["discount"] = mv.fillna(0) - pr.fillna(0)
        base["discount_pct"] = (base["discount"] / mv.replace(0, np.nan)) * 100
    if "player.points_avg" in base.columns and "price" in base.columns:
        pts = pd.to_numeric(base["player.points_avg"], errors="coerce")
        pr  = pd.to_numeric(base["price"], errors="coerce")
        base["ratio_pts_per_100k"] = pts.fillna(0) / (pr.replace(0, np.nan)/100000)
    if "player.team.acronym" in base.columns and "team.acronym" not in base.columns:
        base["team.acronym"] = base["player.team.acronym"]
    if "player.team.name" in base.columns and "team.name" not in base.columns:
        base["team.name"] = base["player.team.name"]
    if "player.team.id" in base.columns and "team.id" not in base.columns:
        base["team.id"] = base["player.team.id"]
    if "player.name" not in base.columns:
        base["player.name"] = base.get("player.firstname","").fillna("").astype(str) + " " + base.get("player.lastname","").fillna("").astype(str)

    team_games_map, _, team_ptsavg_map = fetch_rankings_maps(s)
    base["Matchs (équipe)"] = pd.to_numeric(base.get("team.id"), errors="coerce").map(lambda v: team_games_map.get(int(v)) if pd.notna(v) else None)
    base["Team PtsAvg"]     = pd.to_numeric(base.get("team.id"), errors="coerce").map(lambda v: team_ptsavg_map.get(int(v)) if pd.notna(v) else None)

    add = []
    for pid in pd.to_numeric(base.get("player.id"), errors="coerce").dropna().astype(int).unique().tolist():
        rec = {"player.id": pid}
        try:
            det = fetch_player_detail(s, pid)
            seas = parse_player_seasons(det)
            rec.update({
                "Matchs (saison)": seas["cur_games"],
                "Pts moy. (saison)": seas["cur_avg"],
                "Matchs N-1": seas["n1_games"],
                "Pts moy. N-1": seas["n1_avg"],
                "Matchs N-2": seas["n2_games"],
                "Pts moy. N-2": seas["n2_avg"],
            })
            if ADD_PRICE_FEATURES:
                s_hist = _parse_marketvalue_series(det)
                mv90, mvmax, mvmin, momentum, spark = _price_features_from_series(s_hist)
                rec.update({
                    "MV_90": mv90,
                    "MV_MAX_365": mvmax,
                    "MV_MIN_365": mvmin,
                    "MV_MOMENTUM_30": momentum,
                    "MV_SPARK_HTML": spark
                })
        except Exception:
            pass
        add.append(rec)
        time.sleep(0.04)
    df_add = pd.DataFrame(add)
    base = base.merge(df_add, on="player.id", how="left")

    if "price" in base.columns and "MV_MAX_365" in base.columns:
        base["discount_vs_max365_pct"] = ( (pd.to_numeric(base["MV_MAX_365"], errors="coerce") - pd.to_numeric(base["price"], errors="coerce")) /
                                           pd.to_numeric(base["MV_MAX_365"], errors="coerce").replace(0, np.nan) ) * 100

    df_disp = base.copy()
    if "offers" in df_disp.columns:
        df_disp["Offres (#)"] = df_disp["offers"].apply(lambda v: len(v) if isinstance(v, list) else 0)
        df_disp = df_disp.drop(columns=["offers"])

    if "MV_SPARK_HTML" in df_disp.columns:
        df_disp["MV Spark"] = df_disp["MV_SPARK_HTML"].fillna("").astype(str)

    nice = {
        "player.name":"Joueur","player.position_name":"Poste","team.acronym":"Équipe",
        "price":"Prix","player.marketvalue":"Valeur marchée","discount_pct":"Décote (%)","ratio_pts_per_100k":"Pts / 100k",
        "player.points_avg":"Pts moy.","username":"Vendeur","expires_in":"Expire dans (s)",
        "MV_90": "MV 90 j", "MV_MAX_365":"MV max 365 j", "MV_MIN_365":"MV min 365 j", "MV_MOMENTUM_30":"Momentum 30 j (%)",
        "discount_vs_max365_pct":"Décote vs max 365 (%)"
    }

    keep_cols = [c for c in [
        "player.name","player.position_name","team.acronym",
        "price","player.marketvalue","discount_pct","ratio_pts_per_100k","player.points_avg",
        "Matchs (équipe)","Matchs (saison)","Pts moy. (saison)","Team PtsAvg",
        "MV_90","MV_MIN_365","MV_MAX_365","MV_MOMENTUM_30","discount_vs_max365_pct","MV Spark",
        "username","expires_in"
    ] if c in df_disp.columns]
    df_disp = df_disp[keep_cols].rename(columns=nice)

    return sanitize_for_html(df_disp), base

# ----------------- DECISION SCORE (interne pour recos) -----------------
DECISION_W_PERF, DECISION_W_ROLE, DECISION_W_PHYS, DECISION_W_CONTR = 0.30, 0.25, 0.20, 0.25
def _norm_rank(s):
    r = _winsor_rankpct(s)
    r = r if isinstance(r, pd.Series) else pd.Series([r])
    return r.fillna(0).clip(lower=0, upper=1)

def compute_decision_score(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    pts_cur   = _num_series(out, "Pts moy. (saison)").fillna(_num_series(out, "Pts moy."))
    forme     = _num_series(out, "Forme (multi)") if "Forme (multi)" in out.columns else _num_series(out, "Pts moy.")
    reg       = _num_series(out, "Régularité") if "Régularité" in out.columns else _num_series(out, "Pts moy.")
    usage     = _num_series(out, "Usage") if "Usage" in out.columns else _num_series(out, "Pts moy.")
    team_ctx  = _num_series(out, "Team PtsAvg") if "Team PtsAvg" in out.columns else _num_series(out, "Pts moy.")
    eff_cost  = _num_series(out, "Pts / 100k")
    discount  = _num_series(out, "Décote (%)")
    disc_vmax = _num_series(out, "Décote vs max 365 (%)") if "Décote vs max 365 (%)" in out.columns else None
    offers    = _num_series(out, "Offres (#)") if "Offres (#)" in out.columns else pd.Series(0.0, index=out.index, dtype="float64")
    expires_s = _num_series(out, "Expire dans (s)") if "Expire dans (s)" in out.columns else pd.Series(float("nan"), index=out.index, dtype="float64")
    is_foreigner = out["Étranger"].astype(str).str.contains("Étranger", case=False) if "Étranger" in out.columns else pd.Series([False]*len(out), index=out.index)

    perf = 0.55*_norm_rank(pts_cur) + 0.25*_norm_rank(forme) + 0.20*_norm_rank(usage)
    role = 0.7*_norm_rank(team_ctx) + 0.3*_norm_rank(usage)
    phys = 0.65*_norm_rank(reg) + 0.35*_norm_rank(usage)
    if disc_vmax is not None:
        contr_market = 0.45*_norm_rank(eff_cost) + 0.30*_norm_rank(discount) + 0.25*_norm_rank(disc_vmax)
    else:
        contr_market = 0.55*_norm_rank(eff_cost) + 0.35*_norm_rank(discount)
    contr_market = contr_market - 0.15 * is_foreigner.astype(float)
    soon = (expires_s <= EXPIRY_BOOST_HRS*3600).fillna(False).astype(float)
    contr_market = contr_market + 0.03*soon - 0.02*(offers.fillna(0) > 0).astype(float)

    decision = (
        DECISION_W_PERF  * perf +
        DECISION_W_ROLE  * role +
        DECISION_W_PHYS  * phys +
        DECISION_W_CONTR * contr_market
    )
    out["__ScoreDecision"] = (pd.to_numeric(decision, errors="coerce").fillna(0.0).clip(0,1)*100).round(1)
    return out

def pick_recommendations(df, budget, foreign_slots, needs_by_pos):
    if df is None or df.empty:
        return pd.DataFrame(), 0
    work  = df.copy()
    if "__ScoreDecision" not in work.columns:
        work = compute_decision_score(work)
    price = _num_series(work, "Prix").fillna(0)
    score = _num_series(work, "__ScoreDecision").fillna(0)
    dens  = score / price.replace(0, np.nan)
    work["__dens"] = dens.fillna(0)
    work = work.sort_values(["__dens","__ScoreDecision"], ascending=[False, False])

    pos = work["Poste"].astype(str).str.upper() if "Poste" in work.columns else pd.Series([""]*len(work), index=work.index)
    def fam(p):
        p = p.strip()
        if p.startswith("G"): return "G"
        if p.startswith("D"): return "D"
        if p.startswith("C"): return "C"
        if "W" in p or "AIL" in p: return "W"
        return "W"
    fams = pos.map(fam)

    is_foreigner = work["Étranger"].astype(str).str.contains("Étranger", case=False) if "Étranger" in work.columns else pd.Series([False]*len(work), index=work.index)

    take_idx, spent, used_foreign = [], 0, 0
    used_by_pos = {"C":0,"W":0,"D":0,"G":0}

    for i, row in work.iterrows():
        p = float(_num_series(work.loc[[i]], "Prix").iloc[0] or 0)
        if p<=0 or spent + p > budget:
            continue
        f = fams.loc[i]
        if used_by_pos[f] >= needs_by_pos.get(f, 999):
            continue
        if bool(is_foreigner.loc[i]) and used_foreign + 1 > foreign_slots:
            continue

        take_idx.append(i)
        spent += p
        used_by_pos[f] += 1
        if bool(is_foreigner.loc[i]): used_foreign += 1

    sel = work.loc[take_idx].drop(columns=["__dens"]) if take_idx else pd.DataFrame()
    return sel, spent

# ----------------- OWNER / ROSTER ENRICHED -----------------
def fetch_team_meta(s, team_id: int):
    try:
        r = s.get(f"{BASE}/api/user/teams/{int(team_id)}", timeout=20)
        if r.status_code != 200:
            return None, None, ""
        j = r.json()
        d = j.get("data", j)
        if isinstance(d, list): d = d[0] if d else {}
        budget    = d.get("budget")
        teamvalue = d.get("teamvalue")
        uname     = _extract_username_from_payload(d)
        return budget, teamvalue, uname
    except Exception:
        return None, None, ""

def pos_family_label(p: str) -> str:
    if not p: return "W"
    p = p.upper()
    if p.startswith("G"): return "G"
    if p.startswith("D"): return "D"
    if p.startswith("C"): return "C"
    if "W" in p or "AIL" in p: return "W"
    return "W"

def build_my_enriched_roster(s, my_team_id: str, team_games_map: dict, team_ptsavg_map: dict) -> pd.DataFrame:
    if not my_team_id:
        return pd.DataFrame()
    try:
        tid = int(my_team_id)
    except:
        return pd.DataFrame()

    rows = []
    players = fetch_players_of_user_team(s, tid)
    for p in players:
        t = p.get("team") or {}
        pid = p.get("id")
        t_id = t.get("id")
        t_games = team_games_map.get(int(t_id)) if isinstance(t_id, int) else None
        t_pavg  = team_ptsavg_map.get(int(t_id)) if isinstance(t_id, int) else None

        cur_games = cur_avg = n1_games = n1_avg = n2_games = n2_avg = None
        mv90 = mvmax = mvmin = momentum = None
        try:
            if isinstance(pid, int):
                det = fetch_player_detail(s, pid)
                seas = parse_player_seasons(det)
                cur_games, cur_avg = seas["cur_games"], seas["cur_avg"]
                n1_games, n1_avg   = seas["n1_games"],  seas["n1_avg"]
                n2_games, n2_avg   = seas["n2_games"],  seas["n2_avg"]
                if ADD_PRICE_FEATURES:
                    s_hist = _parse_marketvalue_series(det)
                    mv90, mvmax, mvmin, momentum, _ = _price_features_from_series(s_hist)
                time.sleep(0.03)
        except Exception:
            pass

        rows.append({
            "ID": pid,
            "Joueur": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
            "Poste": p.get("position_name"),
            "Équipe": t.get("acronym") or t.get("name") or "",
            "Points": p.get("points"),
            "Pts moy.": p.get("points_avg"),
            "Valeur": p.get("marketvalue"),
            "Étranger": "Étranger" if bool(p.get("is_foreigner")) else "",
            "Matchs (équipe)": t_games,
            "Matchs (saison)": cur_games,
            "Pts moy. (saison)": cur_avg,
            "Team PtsAvg": t_pavg,
            "Matchs N-1": n1_games,
            "Pts moy. N-1": n1_avg,
            "Matchs N-2": n2_games,
            "Pts moy. N-2": n2_avg,
            "MV 90 j": mv90,
            "MV min 365 j": mvmin,
            "MV max 365 j": mvmax,
            "Momentum 30 j (%)": momentum
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["Pts / 100k"] = _num_series(df, "Pts moy.") / (_num_series(df, "Valeur").replace(0, np.nan) / 100000)
    df = compute_alpha_score(df)
    return _round_metrics(df)

def build_owner_rosters(s, my_team_id: str, other_team_ids_env: str,
                        owner_overrides_env: str, team_games_map: dict, team_ptsavg_map: dict) -> pd.DataFrame:
    other_ids = _parse_ids_list(other_team_ids_env)
    owner_overrides = _parse_owner_name_overrides(owner_overrides_env)

    team_id_list = []
    if my_team_id:
        try: team_id_list.append(int(my_team_id))
        except: pass
    team_id_list.extend(other_ids)
    team_id_list = list(dict.fromkeys([x for x in team_id_list if isinstance(x, int)]))
    if not team_id_list:
        return pd.DataFrame()

    rows = []
    for tid in team_id_list:
        owner_label = fetch_team_username(s, tid) or owner_overrides.get(tid, f"Équipe {tid}")
        players = fetch_players_of_user_team(s, tid)
        for p in players:
            t = p.get("team") or {}
            pid = p.get("id")
            t_id = t.get("id")
            t_games = team_games_map.get(int(t_id)) if isinstance(t_id, int) else None
            t_pavg  = team_ptsavg_map.get(int(t_id)) if isinstance(t_id, int) else None

            cur_games = cur_avg = n1_games = n1_avg = n2_games = n2_avg = None
            mv90 = mvmax = mvmin = momentum = None
            try:
                if isinstance(pid, int):
                    det = fetch_player_detail(s, pid)
                    seas = parse_player_seasons(det)
                    cur_games, cur_avg = seas["cur_games"], seas["cur_avg"]
                    n1_games, n1_avg   = seas["n1_games"],  seas["n1_avg"]
                    n2_games, n2_avg   = seas["n2_games"],  seas["n2_avg"]
                    if ADD_PRICE_FEATURES:
                        s_hist = _parse_marketvalue_series(det)
                        mv90, mvmax, mvmin, momentum, _ = _price_features_from_series(s_hist)
                    time.sleep(0.035)
            except Exception:
                pass

            rows.append({
                "ID": pid,
                "Joueur": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
                "Poste": p.get("position_name"),
                "Équipe": t.get("acronym") or t.get("name") or "",
                "Points": p.get("points"),
                "Pts moy.": p.get("points_avg"),
                "Valeur": p.get("marketvalue"),
                "Étranger": "Étranger" if bool(p.get("is_foreigner")) else "",
                "Propriétaire": owner_label,
                "Matchs (équipe)": t_games,
                "Matchs (saison)": cur_games,
                "Pts moy. (saison)": cur_avg,
                "Team PtsAvg": t_pavg,
                "Matchs N-1": n1_games,
                "Pts moy. N-1": n1_avg,
                "Matchs N-2": n2_games,
                "Pts moy. N-2": n2_avg,
                "MV 90 j": mv90,
                "MV min 365 j": mvmin,
                "MV max 365 j": mvmax,
                "Momentum 30 j (%)": momentum
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["Pts / 100k"] = _num_series(df, "Pts moy.") / (_num_series(df, "Valeur").replace(0, np.nan) / 100000)
    df["Décote (%)"] = pd.Series([np.nan]*len(df), index=df.index)
    df = compute_alpha_score(df)

    if "Propriétaire" in df.columns:
        df["Propriétaire"] = df["Propriétaire"].astype(str).str.replace(r"<.*?>", "", regex=True).str.strip()
    if "Étranger" in df.columns:
        df["Étranger"] = df["Étranger"].astype(str).str.contains("Étranger", case=False).map(lambda b: "Étranger" if b else "")

    df = _round_metrics(df)
    keep_cols = [c for c in [
        "Joueur","Poste","Équipe","Propriétaire","Étranger",
        "Points","Pts moy.","Valeur","Pts / 100k",
        "Matchs (équipe)","Matchs (saison)","Pts moy. (saison)","Team PtsAvg",
        "Matchs N-1","Pts moy. N-1","Matchs N-2","Pts moy. N-2",
        "MV 90 j","MV min 365 j","MV max 365 j","Momentum 30 j (%)",
        "AlphaScore"
    ] if c in df.columns]
    return df[keep_cols]

# ----------------- ALL PLAYERS -----------------
def fetch_all_players_by_teams(s, team_ids: list, fetch_details: bool,
                               df_effectif: pd.DataFrame,
                               owners_index: dict,
                               team_games: dict,
                               team_ptsavg: dict) -> pd.DataFrame:
    rows = []
    my_ids = set()
    if df_effectif is not None and not df_effectif.empty and "ID" in df_effectif.columns:
        try:
            my_ids = set(pd.to_numeric(df_effectif["ID"], errors="coerce").dropna().astype(int).tolist())
        except Exception:
            my_ids = set()

    for tid in team_ids:
        players = fetch_team_roster(s, tid)
        for p in players:
            t = p.get("team") or {}
            pid = p.get("id")
            is_foreigner = bool(p.get("is_foreigner"))
            owner = owners_index.get(pid, "Moi" if (isinstance(pid,int) and pid in my_ids) else "")
            t_id = t.get("id")
            t_games = team_games.get(int(t_id), None) if isinstance(t_id,int) else None
            t_pavg  = team_ptsavg.get(int(t_id), None) if isinstance(t_id,int) else None

            cur_games = cur_avg = n1_games = n1_avg = n2_games = n2_avg = None
            mv90 = mvmax = mvmin = momentum = None
            spark = ""
            if fetch_details and isinstance(pid, int):
                try:
                    detail = fetch_player_detail(s, int(pid))
                    seas = parse_player_seasons(detail)
                    cur_games, cur_avg = seas["cur_games"], seas["cur_avg"]
                    n1_games, n1_avg   = seas["n1_games"],  seas["n1_avg"]
                    n2_games, n2_avg   = seas["n2_games"],  seas["n2_avg"]
                    if ADD_PRICE_FEATURES:
                        s_hist = _parse_marketvalue_series(detail)
                        mv90, mvmax, mvmin, momentum, spark = _price_features_from_series(s_hist)
                except Exception:
                    pass
                time.sleep(0.04)

            rows.append({
                "ID": pid,
                "Joueur": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
                "Poste": p.get("position_name"),
                "Équipe": t.get("acronym") or t.get("name") or "",
                "Points": p.get("points"),
                "Pts moy.": p.get("points_avg"),
                "Valeur": p.get("marketvalue"),
                "Étranger": "Étranger" if is_foreigner else "",
                "Propriétaire": owner,
                "Matchs (équipe)": t_games,
                "Matchs (saison)": cur_games,
                "Pts moy. (saison)": cur_avg,
                "Team PtsAvg": t_pavg,
                "Matchs N-1": n1_games,
                "Pts moy. N-1": n1_avg,
                "Matchs N-2": n2_games,
                "Pts moy. N-2": n2_avg,
                "MV 90 j": mv90,
                "MV min 365 j": mvmin,
                "MV max 365 j": mvmax,
                "Momentum 30 j (%)": momentum,
                "MV Spark": spark,
            })
        time.sleep(0.05)

    df = pd.DataFrame(rows).drop_duplicates(subset=["ID"])
    if not df.empty:
        pts_avg = _num_series(df, "Pts moy.")
        mv      = _num_series(df, "Valeur")
        df["Pts / 100k"] = pts_avg / (mv.replace(0, np.nan) / 100000)
        df["Décote (%)"] = pd.Series([np.nan]*len(df), index=df.index, dtype="float64")
    return df

# ----------------- UI HELPERS -----------------
def reorder_columns(df: pd.DataFrame, desired_order: list) -> pd.DataFrame:
    if df is None or df.empty: return df
    cols = [c for c in desired_order if c in df.columns]
    rest = [c for c in df.columns if c not in cols]
    return df[cols + rest]

# ----------------- PUBLIC: BUILD EVERYTHING FOR API -----------------
def build_all_datasets() -> Tuple[str, dict]:
    """
    Construit le HTML (sections principales) et renvoie aussi des méta-données.
    Appelé par l'endpoint /api/dashboard.
    """
    s = login_session()

    # Marché enrichi
    df_sales_display, _df_market_calc = fetch_market_enriched(s)

    # Ventes → AlphaScore
    df_sales_for_view = compute_alpha_score(df_sales_display.copy()) if not df_sales_display.empty else df_sales_display
    df_sales_for_view = reorder_columns(df_sales_for_view, [
        "Joueur","Poste","Équipe","Prix","Valeur marchée","Décote (%)","Pts / 100k","Pts moy.",
        "Matchs (équipe)","Matchs (saison)","Pts moy. (saison)","Team PtsAvg",
        "MV 90 j","MV min 365 j","MV max 365 j","Momentum 30 j (%)","Décote vs max 365 (%)","MV Spark",
        "Vendeur","Expire dans (s)","AlphaScore"
    ])
    df_sales_for_view = _round_metrics(df_sales_for_view)

    # Mon équipe
    df_effectif, df_lineup, my_username = fetch_my_team_views(s)

    # Budget / meta team (optionnel)
    budget_live, teamvalue_live, uname_live = fetch_team_meta(s, int(TEAM_ID) if TEAM_ID else 506387)

    # Owners index (optionnel si tu veux l’onglet “Équipe” plus tard)
    other_team_ids  = _parse_ids_list(OTHER_TEAM_IDS_ENV)
    owner_overrides = _parse_owner_name_overrides(OTHER_TEAM_NAMES_ENV)
    owners_index = build_owners_index(s, df_effectif, other_team_ids, owner_overrides, my_username)

    # Rankings
    team_games_map, _, team_ptsavg_map = fetch_rankings_maps(s)

    # Tous les joueurs
    team_ids = _parse_team_ids_env(ALL_PLAYERS_TEAMS_ENV, DEFAULT_TEAMS)
    df_all_players = fetch_all_players_by_teams(
        s, team_ids, ALL_PLAYERS_FETCH_DETAILS, df_effectif, owners_index, team_games_map, team_ptsavg_map
    )
    df_all_players_scored = compute_alpha_score(df_all_players.copy()) if not df_all_players.empty else df_all_players
    df_all_players_scored = reorder_columns(df_all_players_scored, [
        "Joueur","Poste","Équipe","Propriétaire","Étranger",
        "Points","Pts moy.","Valeur","Pts / 100k",
        "Matchs (équipe)","Matchs (saison)","Pts moy. (saison)","Team PtsAvg",
        "MV 90 j","MV min 365 j","MV max 365 j","Momentum 30 j (%)","MV Spark","AlphaScore"
    ])
    df_all_players_scored = _round_metrics(df_all_players_scored)

    # Seuil dynamique AlphaScore
    if not df_sales_for_view.empty and "AlphaScore" in df_sales_for_view.columns:
        sseries = pd.to_numeric(df_sales_for_view["AlphaScore"], errors="coerce").dropna()
        if len(sseries) >= 3:
            top = float(sseries.max())
            q85 = float(sseries.quantile(0.85))
            mu, sigma = float(sseries.mean()), float(sseries.std(ddof=0))
            band = mu + 0.6 * sigma
            base = max(q85, band)
            dyn_threshold = min(base, top - 1.0) if top > 47 else top * 0.98
            dyn_threshold = max(45.0, round(dyn_threshold, 1))
        else:
            dyn_threshold = max(45.0, float(MUST_BUY_THRESHOLD_FALLBACK))
    else:
        dyn_threshold = max(45.0, float(MUST_BUY_THRESHOLD_FALLBACK))

    # Sections HTML
    sections = []

    sections.append({
        "id":"tabVentes", "title":"Ventes",
        "content": f"""
<div class="card p-3">
  <h2 class="h5 mb-2">Ventes du marché</h2>
  <div class="small text-secondary mb-2">Lignes surlignées en <b>vert</b> = AlphaScore ≥ {dyn_threshold:.0f} (seuil dynamique).</div>
  {df_to_html_table(df_sales_for_view, "tblVentes", "Filtrer les ventes…")}
</div>"""
    })

    if not df_all_players_scored.empty:
        sections.append({
            "id":"tabAllPlayers","title":"Tous les joueurs",
            "content": f"""
<div class="card p-3">
  <h2 class="h5 mb-2">Tous les joueurs (par équipes)</h2>
  <div class="small text-secondary mb-2">Équipes interrogées : {', '.join(map(str, team_ids))}. Détails joueur : {'ON' if ALL_PLAYERS_FETCH_DETAILS else 'OFF'}.</div>
  {df_to_html_table(sanitize_for_html(df_all_players_scored), "tblAllPlayers", "Filtrer tous les joueurs…")}
</div>"""
        })
    else:
        sections.append({"id":"tabAllPlayers","title":"Tous les joueurs","content":"<div class='text-secondary'>Aucun joueur récupéré (vérifie la liste d’IDs d’équipes).</div>"})

    # Légende
    legend_html = """
<div class="card p-3">
  <h2 class="h5 mb-2">Aide & légende</h2>
  <ul>
    <li><b>MV 90 j</b> : moyenne sur 90 jours (ou historique disponible si &lt; 90 j).</li>
    <li><b>MV min/max 365 j</b> : min/max sur 365 jours (ou historique disponible si &lt; 365 j).</li>
    <li><b>Momentum 30 j (%)</b> : variation % sur 30 jours.</li>
    <li><b>Décote vs max 365 (%)</b> : (MV max 365 – Prix) / MV max 365.</li>
    <li><b>MV Spark</b> : mini-courbe basée sur l’historique récent.</li>
    <li><b>AlphaScore</b> : indicateur d’opportunité marché.</li>
  </ul>
</div>
"""
    sections.append({"id":"tabHelp","title":"Aide","content": legend_html})

    html = build_html_page(sections, dyn_threshold)
    meta = {
        "team_logo": TEAM_LOGO_URL,
        "username": my_username or uname_live or "",
        "budget": budget_live,
        "teamvalue": teamvalue_live,
        "threshold": dyn_threshold
    }
    return html, meta
