#discordbot/bot.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, io, sys, time, asyncio, logging, requests
import discord
from discord import app_commands
from discord.ui import View, Button, Select

# ==========================
#  ENV
# ==========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

def _parse_ids_env(val: str) -> list[int]:
    out = []
    for tok in (val or "").replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            v = int(tok)
            if v not in out:
                out.append(v)
        except Exception:
            pass
    return out

# Multi-guild
_g_multi  = _parse_ids_env(os.getenv("DISCORD_GUILD_IDS", ""))
_g_single = int(os.getenv("DISCORD_GUILD_ID", "0") or "0")
DISCORD_GUILD_IDS = _g_multi or ([ _g_single ] if _g_single else [])

# Multi-channel
_c_multi  = _parse_ids_env(os.getenv("DISCORD_CHANNEL_IDS", ""))
_c_single = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")
DISCORD_CHANNEL_IDS = [x for x in (_c_multi or ([ _c_single ] if _c_single else [])) if x]

TOPS_LEAGUE_ID       = int(os.getenv("TOPS_LEAGUE_ID", "0") or "0")
OTHER_TEAM_IDS_ENV   = os.getenv("OTHER_TEAM_IDS", "")
OTHER_TEAM_NAMES_ENV = os.getenv("OTHER_TEAM_NAMES", "")
POLL_EVERY           = int(os.getenv("POLL_EVERY", "120") or "120")
BASE                 = "https://topscorers.ch"

# Dashboard backend (ton vrai service)
BACKEND_BASE_URL     = os.getenv("BACKEND_BASE_URL", "").rstrip("/")  # ex: http://topscorers-backend:8080
PUBLIC_DASHBOARD_URL = os.getenv("PUBLIC_DASHBOARD_URL", "").rstrip("/")  # ex: http://88.184.158.243:50080

from topscorers import (
    login_session, fetch_market, fetch_price_series, _price_features_from_series
)

# ==========================
#  Logging
# ==========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")
try:
    log.info("PY %s  discord.py %s", sys.version.split()[0], discord.__version__)
except Exception:
    pass

# ==========================
#  Utils
# ==========================
def _fmt_num(x):
    try:
        return f"{int(round(float(x))):,}".replace(",", " ")
    except Exception:
        return "—"

def _parse_name_map(s: str):
    out = {}
    for tok in (s or "").split(","):
        tok = tok.strip()
        if not tok or "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        try:
            out[int(k.strip())] = v.strip()
        except Exception:
            continue
    return out

def _chunk_strings(lines, max_chars=1800):
    chunks, cur = [], []
    cur_len = 0
    for ln in lines:
        add = len(ln) + 1
        if cur and cur_len + add > max_chars:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(ln)
        cur_len += add
    if cur:
        chunks.append("\n".join(cur))
    return chunks

def _sum_team_value(players: list[dict]) -> int | None:
    total = 0
    have_any = False
    for p in players or []:
        mv = p.get("marketvalue") \
             or (p.get("stats_summary") or {}).get("marketvalue") \
             or p.get("value")
        try:
            if mv is None:
                continue
            total += int(round(float(mv)))
            have_any = True
        except Exception:
            continue
    return total if have_any else None

# ==========================
#  UI Views
# ==========================
class OfferView(View):
    def __init__(self, player_id: int, timeout: float = 1800):  # 30 minutes
        super().__init__(timeout=timeout)
        self.player_id = int(player_id)

        btn = Button(
            label="Détails",
            style=discord.ButtonStyle.primary,
            custom_id=f"details:{self.player_id}"
        )

        async def _on_click(interaction: discord.Interaction):
            # Ack rapide (éphémère) + log
            log.info("Détails: click user=%s player_id=%s",
                     getattr(interaction.user, "id", "?"), self.player_id)
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception as e:
                log.warning("interaction.defer failed: %r", e)

            bot = interaction.client  # type: ignore
            assert isinstance(bot, TopscorerBot)

            # Session TopScorers
            try:
                bot._ensure_login()
            except Exception as e:
                await interaction.followup.send(f"❌ Connexion TopScorers impossible : {e}", ephemeral=True)
                return

            # Données + features
            try:
                s = fetch_price_series(bot.sess, self.player_id)
                mv90, mvmax, mvmin, momentum, png = _price_features_from_series(s)
            except Exception as e:
                await interaction.followup.send(f"❌ Impossible de charger les détails : {e}", ephemeral=True)
                return

            link = f"{BASE}/players/{self.player_id}"
            desc = []
            if mv90 is not None:  desc.append(f"**MV 90 j** : {_fmt_num(mv90)}")
            if mvmin is not None: desc.append(f"**Min 365 j** : {_fmt_num(mvmin)}")
            if mvmax is not None: desc.append(f"**Max 365 j** : {_fmt_num(mvmax)}")
            if momentum is not None:
                sign = "▲" if momentum >= 0 else "▼"
                desc.append(f"**Momentum 30 j** : {sign} {momentum:.1f}%")
            if not desc:
                desc.append("_Aucune métrique disponible_")

            emb = discord.Embed(
                title=f"Détails joueur #{self.player_id}",
                url=link,
                description="\n".join(desc),
                color=0x2B7A0B,
            )

            files = []
            if png:
                try:
                    buf = io.BytesIO(png); buf.seek(0)
                    f = discord.File(buf, filename="mv.png")
                    emb.set_image(url="attachment://mv.png")
                    files = [f]
                except Exception as e:
                    log.warning("attach png failed: %r", e)

            try:
                await interaction.followup.send(embed=emb, files=files, ephemeral=True)
            except Exception as e:
                log.warning("followup.send failed: %r", e)

        btn.callback = _on_click
        self.add_item(btn)


class TeamSelect(Select):
    def __init__(self, choices):
        options = [
            discord.SelectOption(
                label=(label or f"Équipe {tid}")[:100],
                description=(desc or "")[:100] or None,
                value=str(tid),
            )
            for (label, desc, tid) in choices
        ][:25]
        super().__init__(placeholder="Choisis un manager…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            log.warning(f"TeamSelect.defer failed: {e!r}")

        team_id = int(self.values[0])
        bot = interaction.client  # type: ignore
        assert isinstance(bot, TopscorerBot)
        bot._ensure_login()

        # Roster complet (privé -> public fallback)
        import requests as _requests
        players = []
        try:
            players = bot._fetch_user_team_players(team_id)
        except _requests.HTTPError as e:
            log.info(f"user_team_players failed for {team_id}: {e}. Fallback /api/players?team=")
            try:
                players = bot._fetch_team_roster_public(team_id)
            except Exception as e2:
                await interaction.followup.send(f"❌ Impossible de charger l’équipe : {e2}", ephemeral=True)
                return
        except Exception as e:
            await interaction.followup.send(f"❌ Impossible de charger l’équipe : {e}", ephemeral=True)
            return

        # Valeur d’équipe
        team_value = None
        try:
            meta = bot._fetch_user_team_meta(team_id)
            team_value = meta.get("value") or meta.get("squad_value") or meta.get("value_total")
        except Exception as e:
            log.info(f"meta fetch failed for {team_id}: {e!r}")
        if team_value is None:
            team_value = _sum_team_value(players)

        username = bot._best_effort_username(team_id)
        header = "\n".join([
            f"**Manager** : {username}",
            f"**Valeur d’équipe** : {_fmt_num(team_value) if team_value is not None else '—'}",
        ])

        # Liste complète
        lines = []
        for p in players:
            pid = p.get("id")
            n = p.get("name") or f"{p.get('firstname','')} {p.get('lastname','')}".strip() or f"#{pid or ''}"
            pos = p.get("position_name") or p.get("position") or ""
            mv  = p.get("marketvalue") or (p.get("stats_summary") or {}).get("marketvalue") or p.get("value")
            team_obj = p.get("team") or {}
            club_acr = team_obj.get("acronym") or team_obj.get("name") or "—"
            lines.append(f"- {n} ({pos}, {club_acr}) — MV: {_fmt_num(mv)}")

        if not lines:
            await interaction.followup.send(content=f"✅ {header}\n\n*(aucun joueur trouvé)*", ephemeral=True)
            return

        chunks = _chunk_strings(lines, max_chars=1750)
        await interaction.followup.send(content=f"✅ {header}\n\n" + chunks[0], ephemeral=True)
        for ch in chunks[1:]:
            await interaction.followup.send(content=ch, ephemeral=True)

class TeamSelectView(View):
    def __init__(self, choices, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.add_item(TeamSelect(choices))

# ==========================
#  Bot
# ==========================
class TopscorerBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.sess: requests.Session | None = None
        self.last_seen_ids = set()
        self._live_views: list[tuple[float, discord.ui.View]] = []  # (expire_ts, view)

        self.guild_objs = [discord.Object(id=g) for g in DISCORD_GUILD_IDS]
        self.channel_ids = DISCORD_CHANNEL_IDS[:]
        self._channel_cache: dict[int, discord.abc.MessageableChannel] = {}

        # Managers env
        self.other_team_ids   = _parse_ids_env(OTHER_TEAM_IDS_ENV)
        self.other_team_names = _parse_name_map(OTHER_TEAM_NAMES_ENV)

        # Dashboard cooldown (anti-spam)
        self._last_dash_gen_ts = 0
        self._dash_cooldown_s  = 90

    def keep_view(self, view: discord.ui.View, ttl: float = 1900.0):
        """Garde la View en vie ~31 min (légèrement > timeout du bouton)."""
        now = time.time()
        self._live_views.append((now + ttl, view))
        # Purge légère si la liste grandit trop
        if len(self._live_views) > 200:
            t = time.time()
            self._live_views = [(exp, v) for (exp, v) in self._live_views if exp > t]

    # ---- Dashboard ----
    async def _trigger_dashboard_generation(self) -> str | None:
        """
        Déclenche la génération côté backend sans bloquer l'event loop.
        Retourne l'URL publique si définie, sinon fallback backend.
        """
        if not BACKEND_BASE_URL:
            return None

        now = time.time()
        if now - self._last_dash_gen_ts >= self._dash_cooldown_s:
            self._last_dash_gen_ts = now

            async def _fire_and_forget():
                def _do_post():
                    try:
                        # timeouts courts: (connect, read)
                        requests.post(f"{BACKEND_BASE_URL}/api/generate", timeout=(2, 4))
                    except Exception as e:
                        log.warning("Génération backend (async) échouée: %r", e)

                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, _do_post)
                    log.info("Dashboard: POST /api/generate lancé en arrière-plan.")
                except Exception as e:
                    log.warning("run_in_executor failed: %r", e)

            asyncio.create_task(_fire_and_forget())

        # 👉 retourne la RACINE du frontend si présente
        if PUBLIC_DASHBOARD_URL:
            return f"{PUBLIC_DASHBOARD_URL}/"
        return f"{BACKEND_BASE_URL}/api/dashboard"

    # ---- API TopScorers ----
    def _ensure_login(self):
        if self.sess is None:
            log.info("Connexion à TopScorers…")
            self.sess = login_session()
            log.info("Connecté à TopScorers")

    def _fetch_user_team_players(self, team_id: int) -> list[dict]:
        assert self.sess is not None
        r = self.sess.get(f"{BASE}/api/user/teams/{int(team_id)}/players", timeout=25)
        r.raise_for_status()
        j = r.json()
        return j if isinstance(j, list) else j.get("data") or []

    def _fetch_team_roster_public(self, team_id: int) -> list[dict]:
        assert self.sess is not None
        r = self.sess.get(f"{BASE}/api/players", params={"team": int(team_id)}, timeout=25)
        r.raise_for_status()
        j = r.json()
        return j if isinstance(j, list) else j.get("data") or []

    def _fetch_user_team_meta(self, team_id: int) -> dict:
        assert self.sess is not None
        r = self.sess.get(f"{BASE}/api/user/teams/{int(team_id)}", timeout=20)
        r.raise_for_status()
        j = r.json()
        d = j.get("data", j)
        if isinstance(d, list) and d:
            d = d[0]
        return dict(d)

    def _best_effort_username(self, team_id: int) -> str:
        name = self.other_team_names.get(team_id)
        if name:
            return name
        try:
            assert self.sess is not None
            r = self.sess.get(f"{BASE}/api/user/teams/{int(team_id)}", timeout=12)
            if r.status_code == 200:
                j = r.json()
                d = j.get("data") or j
                if isinstance(d, list) and d:
                    d = d[0]
                val = d.get("username") or (d.get("user") or {}).get("username")
                if isinstance(val, str) and val.strip():
                    return val.strip()
        except Exception:
            pass
        return f"Équipe {team_id}"

    def _choices_from_env(self):
        return [(self.other_team_names.get(tid) or f"Équipe {tid}", "", tid) for tid in self.other_team_ids][:25]

    # ==========================
    #  Slash Commands
    # ==========================
    async def _cmd_scan(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=False)
        except Exception:
            pass
        try:
            self._ensure_login()
            items = fetch_market(self.sess) or []
            if not items:
                await interaction.followup.send("Aucune offre trouvée pour le moment.")
                return
            for it in items[:20]:
                p = it.get("player", {}) if isinstance(it, dict) else {}
                team = p.get("team") or {}
                pid = p.get("id")
                name = p.get("name") or f"{p.get('firstname','')} {p.get('lastname','')}".strip() or "Joueur"
                pos = p.get("position_name") or "—"
                team_acr = team.get("acronym") or team.get("name") or "—"
                mv = p.get("marketvalue") or it.get("marketvalue")
                price = it.get("price")
                link = f"{BASE}/players/{pid}" if pid else BASE
                emb = discord.Embed(
                    title=f"{name} — {team_acr} ({pos})",
                    url=link,
                    description=f"**Prix**: {_fmt_num(price)}\n**Valeur marchée**: {_fmt_num(mv)}",
                    color=0xC8102E,
                )
                view = OfferView(pid) if pid else None
                if view:
                    self.keep_view(view)
                await interaction.followup.send(embed=emb, view=view if view else None)
        except Exception as e:
            await interaction.followup.send(f"Erreur pendant le scan : `{e}`")

    async def _cmd_marche(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=False)
        except Exception:
            pass
        try:
            self._ensure_login()
            items = fetch_market(self.sess) or []
            if not items:
                await interaction.followup.send("Marché vide pour le moment.")
                return
            for it in items[:20]:
                p = it.get("player", {}) if isinstance(it, dict) else {}
                team = p.get("team") or {}
                pid = p.get("id")
                name = p.get("name") or f"{p.get('firstname','')} {p.get('lastname','')}".strip() or "Joueur"
                pos = p.get("position_name") or "—"
                team_acr = team.get("acronym") or team.get("name") or "—"
                mv = p.get("marketvalue") or it.get("marketvalue")
                price = it.get("price")
                link = f"{BASE}/players/{pid}" if pid else BASE
                emb = discord.Embed(
                    title=f"{name} — {team_acr} ({pos})",
                    url=link,
                    description=f"**Prix**: {_fmt_num(price)}\n**Valeur marchée**: {_fmt_num(mv)}",
                    color=0x5865F2,
                )
                view = OfferView(pid) if pid else None
                if view:
                    self.keep_view(view)
                await interaction.followup.send(embed=emb, view=view if view else None)
        except Exception as e:
            await interaction.followup.send(f"Erreur : `{e}`")

    async def _cmd_equipe(self, interaction: discord.Interaction):
        choices = self._choices_from_env()
        view = TeamSelectView(choices)
        await interaction.response.send_message("Sélectionne un manager :", view=view, ephemeral=True)

    async def _cmd_dashboard(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        url = await self._trigger_dashboard_generation()
        if url:
            await interaction.followup.send(f"📊 Dashboard prêt : {url}", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ BACKEND_BASE_URL non configuré sur le bot.", ephemeral=True)

    async def _cmd_purge(self, interaction: discord.Interaction, count: int):
        """Supprime jusqu’à N messages du bot dans ce salon."""
        await interaction.response.defer(ephemeral=True)
        ch = interaction.channel
        me = self.user
        if not isinstance(ch, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
            await interaction.followup.send("Ce type de salon n’est pas supporté.", ephemeral=True)
            return
        deleted = 0
        try:
            async for msg in ch.history(limit=max(10, min(500, count*5))):
                if msg.author.id == me.id:
                    try:
                        await msg.delete()
                        deleted += 1
                        if deleted >= count:
                            break
                    except Exception:
                        pass
        except Exception as e:
            await interaction.followup.send(f"Erreur purge : {e}", ephemeral=True)
            return
        await interaction.followup.send(f"🧹 Supprimé {deleted} message(s) du bot.", ephemeral=True)

    # ==========================
    #  Setup / Sync
    # ==========================
    async def setup_hook(self):
        scan_cmd      = app_commands.Command(name="scan",      description="Scanner immédiatement le marché.",                       callback=self._cmd_scan)
        marche_cmd    = app_commands.Command(name="marche",    description="Lister le marché courant (20 offres max).",             callback=self._cmd_marche)
        equipe_cmd    = app_commands.Command(name="equipe",    description="Choisir un manager et afficher tout l’effectif.",       callback=self._cmd_equipe)
        dashboard_cmd = app_commands.Command(name="dashboard", description="Générer (si besoin) et obtenir le lien du dashboard.",  callback=self._cmd_dashboard)

        @app_commands.command(name="purge", description="Supprimer X messages du bot dans ce salon.")
        @app_commands.describe(count="Nombre de messages du bot à supprimer")
        async def purge_cmd(interaction: discord.Interaction, count: int):
            await self._cmd_purge(interaction, max(1, min(200, count)))

        if self.guild_objs:
            for g in self.guild_objs:
                self.tree.clear_commands(guild=g)
                self.tree.add_command(scan_cmd,      guild=g)
                self.tree.add_command(marche_cmd,    guild=g)
                self.tree.add_command(equipe_cmd,    guild=g)
                self.tree.add_command(dashboard_cmd, guild=g)
                self.tree.add_command(purge_cmd,     guild=g)
                cmds = await self.tree.sync(guild=g)
                log.info("Slash commands synchronisées (guild %s) : %s", g.id, [c.name for c in cmds])
        else:
            self.tree.clear_commands()
            self.tree.add_command(scan_cmd)
            self.tree.add_command(marche_cmd)
            self.tree.add_command(equipe_cmd)
            self.tree.add_command(dashboard_cmd)
            self.tree.add_command(purge_cmd)
            cmds = await self.tree.sync()
            log.info("Slash commands synchronisées (global) : %s", [c.name for c in cmds])

    # ==========================
    #  Events / Poll loop
    # ==========================
    async def on_ready(self):
        log.info("Discord connecté: %s", self.user)
        for g in self.guilds:
            log.info("[GUILD] %s (id=%s)", g.name, g.id)
            for c in g.text_channels[:10]:
                log.info("  - [CHAN] %s (id=%s)", c.name, c.id)
        asyncio.create_task(self.loop_poll())

    async def loop_poll(self):
        await self.wait_until_ready()

        async def _get_channel(ch_id: int):
            ch = self._channel_cache.get(ch_id)
            if ch:
                return ch
            try:
                ch = self.get_channel(ch_id) or await self.fetch_channel(ch_id)
                self._channel_cache[ch_id] = ch
                return ch
            except Exception as e:
                log.warning("Impossible d'accéder au salon %s : %r", ch_id, e)
                return None

        while not self.is_closed():
            try:
                self._ensure_login()
                items = fetch_market(self.sess) or []
                new_items = []
                for it in items:
                    iid = it.get("id")
                    if iid and iid not in self.last_seen_ids:
                        new_items.append(it)
                        self.last_seen_ids.add(iid)
                log.info("poll: %d offres (%d nouvelles)", len(items), len(new_items))

                if new_items and self.channel_ids:
                    targets = []
                    for ch_id in self.channel_ids:
                        ch = await _get_channel(ch_id)
                        if ch:
                            targets.append(ch)

                    for it in new_items[:5]:
                        p = it.get("player", {}) if isinstance(it, dict) else {}
                        team = p.get("team") or {}
                        pid = p.get("id")
                        name = p.get("name") or f"{p.get('firstname','')} {p.get('lastname','')}".strip() or "Joueur"
                        pos = p.get("position_name") or "—"
                        team_acr = team.get("acronym") or team.get("name") or "—"
                        mv = p.get("marketvalue") or it.get("marketvalue")
                        price = it.get("price")
                        link = f"{BASE}/players/{pid}" if pid else BASE

                        emb = discord.Embed(
                            title=f"{name} — {team_acr} ({pos})",
                            url=link,
                            description=f"**Prix**: {_fmt_num(price)}\n**Valeur marchée**: {_fmt_num(mv)}",
                            color=0xC8102E
                        )
                        view = OfferView(pid) if pid else None
                        if view:
                            self.keep_view(view)
                        for ch in targets:
                            try:
                                await ch.send(embed=emb, view=view if view else None)
                            except Exception as e:
                                log.warning("send to channel %s failed: %r", getattr(ch, "id", "?"), e)

                    # Déclenche génération dashboard (cooldown) SANS bloquer
                    url = await self._trigger_dashboard_generation()
                    if url:
                        log.info("Dashboard demandé → %s", url)

            except Exception:
                logging.exception("loop_poll")
            finally:
                await asyncio.sleep(POLL_EVERY)

# ==========================
#  Entrypoint
# ==========================
async def main():
    intents = discord.Intents.none()
    intents.guilds = True
    intents.messages = True
    bot = TopscorerBot(intents=intents)
    token = DISCORD_TOKEN
    if not token:
        log.error("DISCORD_TOKEN manquant")
        return
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
