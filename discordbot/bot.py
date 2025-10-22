import os, json, time, asyncio, logging
from datetime import datetime, timezone
import requests
import discord

BASE = "https://topscorers.ch"

EMAIL    = os.getenv("TOPS_EMAIL")
PASSWORD = os.getenv("TOPS_PASSWORD")
LEAGUE_ID = os.getenv("TOPS_LEAGUE_ID", "92556")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "120"))
SEEN_PATH = os.getenv("SEEN_PATH", "/data/seen_transfers.json")

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Language": "fr",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "User-Agent": "Mozilla/5.0",
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "x-app-version": "1.5.5",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_seen():
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_seen(seen):
    try:
        os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
        with open(SEEN_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(list(seen)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"Cannot save seen file: {e}")

def login_session():
    if not EMAIL or not PASSWORD:
        raise RuntimeError("TOPS_EMAIL / TOPS_PASSWORD manquants")
    s = requests.Session()
    s.headers.update(HEADERS)
    r0 = s.get(f"{BASE}/sanctum/csrf-cookie", timeout=15)
    r0.raise_for_status()
    csrf = s.cookies.get("XSRF-TOKEN")
    if not csrf:
        raise RuntimeError("Pas de XSRF-TOKEN")
    s.headers["X-XSRF-TOKEN"] = requests.utils.unquote(csrf)
    r1 = s.post(f"{BASE}/api/login", json={"email": EMAIL, "password": PASSWORD}, timeout=20)
    if r1.status_code == 419:
        raise RuntimeError("419 CSRF mismatch")
    r1.raise_for_status()
    return s

def fetch_market(s: requests.Session):
    r = s.get(f"{BASE}/api/user/leagues/{LEAGUE_ID}/transfers", timeout=20)
    r.raise_for_status()
    j = r.json()
    items = j.get("data")
    if items is None:
        for _, v in (j.items() if isinstance(j, dict) else []):
            if isinstance(v, list):
                items = v
                break
    if items is None: items = []
    if isinstance(items, dict): items = [items]
    return items

def short_item_description(it):
    # On essaye d’extraire des champs utiles, en tolérant les absents
    p = (it.get("player") or {})
    team = p.get("team") or {}
    name = (p.get("firstname","") + " " + p.get("lastname","")).strip() or p.get("name","Joueur")
    price = it.get("price")
    mv = p.get("marketvalue") or it.get("player",{}).get("marketvalue")
    pos = p.get("position_name") or ""
    team_acr = team.get("acronym") or team.get("name") or "—"
    pav = p.get("points_avg")
    seller = it.get("username") or "—"
    expires = it.get("expires_in")
    return name, team_acr, pos, price, mv, pav, seller, expires

def fmt_currency(v):
    try:
        return f"{int(v):,}".replace(",", " ")
    except Exception:
        return str(v)

class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        super().__init__(intents=intents)
        self.sess = None
        self.seen = load_seen()
        self.bg_task = None

    async def on_ready(self):
        logging.info(f"Discord connecté: {self.user}")
        # Tâche de fond
        self.bg_task = asyncio.create_task(self.loop_poll())

    async def loop_poll(self):
        await asyncio.sleep(3)
        backoff = 1
        while True:
            try:
                if self.sess is None:
                    logging.info("Connexion à TopScorers…")
                    self.sess = login_session()
                    logging.info("Connecté à TopScorers")

                items = fetch_market(self.sess)
                chan = self.get_channel(DISCORD_CHANNEL_ID)
                if chan is None:
                    logging.warning("Channel Discord introuvable (ID ?)")
                now = int(time.time())

                new_count = 0
                for it in items:
                    tid = it.get("id")
                    if tid is None:
                        continue
                    if tid in self.seen:
                        continue
                    # Ne pas spammer au premier boot : on seed la liste et on notifie seulement les vraiment nouveaux
                    # Règle : on notifie si l’offre a moins de 10 minutes ou si on n’a pas encore de base
                    created_at = it.get("created_at")
                    notify = True
                    if created_at:
                        try:
                            # created_at format ISO ? on tolère
                            dt = datetime.fromisoformat(created_at.replace("Z","+00:00"))
                            if (datetime.now(timezone.utc) - dt).total_seconds() > 600:
                                notify = False
                        except Exception:
                            pass

                    self.seen.add(tid)

                    if not notify:
                        continue

                    name, team_acr, pos, price, mv, pav, seller, expires = short_item_description(it)
                    desc_lines = []
                    desc_lines.append(f"**{name}** ({team_acr} · {pos or '—'})")
                    if pav is not None:
                        try:
                            desc_lines.append(f"Pts moy.: **{float(pav):.2f}**")
                        except Exception:
                            pass
                    if mv is not None:
                        desc_lines.append(f"Valeur marchée: **{fmt_currency(mv)}**")
                    if price is not None:
                        desc_lines.append(f"Prix demandé: **{fmt_currency(price)}**")
                    if seller:
                        desc_lines.append(f"Vendeur: `{seller}`")
                    if expires is not None:
                        try:
                            h = int(expires) / 3600.0
                            desc_lines.append(f"Expire dans ~ **{h:.1f} h**")
                        except Exception:
                            pass

                    text = "\n".join(desc_lines)
                    if chan:
                        await chan.send(f"🧾 **Nouvelle offre sur le marché**\n{text}")
                        new_count += 1

                if new_count:
                    save_seen(self.seen)

                backoff = 1  # reset
                await asyncio.sleep(POLL_INTERVAL_SEC)
            except requests.HTTPError as e:
                code = getattr(e.response, "status_code", None)
                logging.warning(f"HTTP error {code}: {e}. Re-login.")
                self.sess = None
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)
            except Exception as e:
                logging.exception(f"Loop error: {e}")
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)

if __name__ == "__main__":
    if not DISCORD_TOKEN or not DISCORD_CHANNEL_ID:
        raise SystemExit("DISCORD_TOKEN / DISCORD_CHANNEL_ID manquants")
    client = Bot()
    client.run(DISCORD_TOKEN)
