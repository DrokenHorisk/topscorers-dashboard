#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, io, sys, asyncio, logging, requests, discord
from discord import app_commands
from discord.ui import View, Button, Select

# ==========================
#  ENV
# ==========================
DISCORD_TOKEN       = os.getenv("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID  = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")
DISCORD_GUILD_ID    = int(os.getenv("DISCORD_GUILD_ID", "0") or "0")
TOPS_LEAGUE_ID      = int(os.getenv("TOPS_LEAGUE_ID", "0") or "0")

OTHER_TEAM_IDS_ENV   = os.getenv("OTHER_TEAM_IDS", "")
OTHER_TEAM_NAMES_ENV = os.getenv("OTHER_TEAM_NAMES", "")

POLL_EVERY          = int(os.getenv("POLL_EVERY", "120") or "120")
BACKEND_BASE_URL    = os.getenv("BACKEND_BASE_URL", "").rstrip("/")
BASE                = "https://topscorers.ch"

from topscorers import (
    login_session, fetch_market, fetch_price_series,
    _price_features_from_series
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

def _parse_ids(s: str):
    out = []
    for tok in (s or "").replace(";", ",").split(","):
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

# ==========================
#  UI Views
# ==========================
class OfferView(View):
    def __init__(self, player_id: int, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.add_item(Button(label="Détails", style=discord.ButtonStyle.primary, custom_id=f"details:{int(player_id)}"))

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
        # Déferer très vite (3s max Discord)
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            log.warning(f"TeamSelect.defer failed: {e!r}")

        team_id = int(self.values[0])
        label = next((opt.label for opt in self.options if opt.value == str(team_id)), f"Équipe {team_id}")

        bot = interaction.client  # type: ignore
        assert isinstance(bot, TopscorerBot)
        bot._ensure_login()

        # 1) Essai endpoint “privé” (plus riche) -> /api/user/teams/{team_id}/players
        # 2) Fallback endpoint “public”        -> /api/players?team={team_id}
        players = []
        used_endpoint = ""
        try:
            players = bot._fetch_user_team_players(team_id)
            used_endpoint = f"{BASE}/api/user/teams/{team_id}/players"
        except requests.HTTPError as e:
            log.info(f"user_team_players failed for {team_id}: {e}. Fallback /api/players?team=")
            try:
                players = bot._fetch_team_roster_public(team_id)
                used_endpoint = f"{BASE}/api/players?team={team_id}"
            except Exception as e2:
                await interaction.followup.send(f"❌ Impossible de charger l’équipe {team_id} : {e2}", ephemeral=True)
                return
        except Exception as e:
            await interaction.followup.send(f"❌ Impossible de charger l’équipe {team_id} : {e}", ephemeral=True)
            return

        username = bot._best_effort_username(team_id)
        club     = bot._best_effort_club(team_id)
        header   = f"**Manager** : {username or label}\n**Club** : {club or '—'}\n_Source_: `{used_endpoint}`"

        # Construire la liste complète
        lines = []
        for p in players:
            pid = p.get("id")
            n = p.get("name") or f"{p.get('firstname','')} {p.get('lastname','')}".strip() or f"#{pid or ''}"
            pos = p.get("position_name") or p.get("position") or ""
            mv  = p.get("marketvalue") or (p.get("stats_summary") or {}).get("marketvalue")
            if mv is None:
                mv = p.get("value")
            lines.append(f"- {n} ({pos}) — MV: {_fmt_num(mv)}")

        if not lines:
            await interaction.followup.send(
                content=f"✅ {label} — team_id **{team_id}**\n{header}\n\n*(aucun joueur trouvé)*",
                ephemeral=True
            )
            return

        chunks = _chunk_strings(lines, max_chars=1750)
        await interaction.followup.send(
            content=f"✅ {label} — team_id **{team_id}**\n{header}\n\n" + chunks[0],
            ephemeral=True
        )
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

        self.guild_obj = discord.Object(id=DISCORD_GUILD_ID) if DISCORD_GUILD_ID else None
        if DISCORD_GUILD_ID:
            log.info("Scope guilde forcé: %s", DISCORD_GUILD_ID)
        else:
            log.info("Scope global (DISCORD_GUILD_ID non défini)")

        self.other_team_ids   = _parse_ids(OTHER_TEAM_IDS_ENV)
        self.other_team_names = _parse_name_map(OTHER_TEAM_NAMES_ENV)
        log.info("Managers ENV: %s", self.other_team_ids)
        log.info("Managers names ENV: %s", self.other_team_names)

    # -------- TopScorers API helpers --------
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
        if isinstance(j, list):
            return j
        return j.get("data") or []

    def _fetch_team_roster_public(self, team_id: int) -> list[dict]:
        assert self.sess is not None
        r = self.sess.get(f"{BASE}/api/players", params={"team": int(team_id)}, timeout=25)
        r.raise_for_status()
        j = r.json()
        if isinstance(j, list):
            return j
        return j.get("data") or []

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
                u = (
                    d.get("username")
                    or (d.get("user") or {}).get("username")
                    or (d.get("owner") or {}).get("username")
                    or (d.get("account") or {}).get("username")
                )
                if isinstance(u, str) and u.strip():
                    return u.strip()
        except Exception:
            pass
        return f"Équipe {team_id}"

    def _best_effort_club(self, team_id: int) -> str:
        try:
            assert self.sess is not None
            r = self.sess.get(f"{BASE}/api/user/teams/{int(team_id)}", timeout=12)
            if r.status_code == 200:
                j = r.json()
                d = j.get("data") or j
                if isinstance(d, list) and d:
                    d = d[0]
                team_obj = d.get("team") or {}
                club = team_obj.get("acronym") or team_obj.get("name")
                if isinstance(club, str) and club.strip():
                    return club.strip()
        except Exception:
            pass
        return "—"

    def _choices_from_env(self):
        choices = []
        for tid in self.other_team_ids:
            label = self.other_team_names.get(tid) or f"Équipe {tid}"
            desc  = ""
            choices.append((label, desc, tid))
        return choices[:25] if choices else [("Aucun manager", "", 0)]

    # -------- Player brief (pour /details) --------
    def _player_brief(self, player_id: int):
        try:
            assert self.sess is not None
            r = self.sess.get(f"{BASE}/api/players/{int(player_id)}", timeout=20)
            r.raise_for_status()
            j = r.json()
            d = j.get("data") or j
            name = (
                d.get("name")
                or f"{d.get('firstname','')} {d.get('lastname','')}".strip()
                or f"Joueur #{player_id}"
            )
            team = d.get("team") or {}
            team_acr = team.get("acronym") or team.get("name") or "—"
            pos = d.get("position_name") or d.get("position") or "—"
            mv = d.get("marketvalue") or (d.get("stats_summary") or {}).get("marketvalue")
            pts_avg = d.get("points_avg")
            if pts_avg is None:
                pm = d.get("point_metrics") or []
                if pm:
                    try:
                        pm_sorted = sorted(pm, key=lambda x: x.get("season", 0), reverse=True)
                        cur = pm_sorted[0] if pm_sorted else {}
                        pts = cur.get("points"); gms = cur.get("games")
                        if pts is not None and gms:
                            pts_avg = float(pts)/float(gms)
                    except Exception:
                        pass
            return name, team_acr, pos, mv, pts_avg
        except Exception as e:
            log.warning(f"_player_brief fallback for {player_id}: {e!r}")
            return f"Joueur #{player_id}", "—", "—", None, None

    # ==========================
    #  Slash Commands
    # ==========================
    async def _cmd_scan(self, interaction: discord.Interaction):
        log.info("/scan invoked")
        try:
            await interaction.response.defer(ephemeral=False)
        except Exception as e:
            log.warning(f"/scan defer failed: {e!r}")

        try:
            self._ensure_login()
            items = fetch_market(self.sess) or []
            log.info("/scan fetched %d offers", len(items))
            if not items:
                await interaction.followup.send("Aucune offre trouvée pour le moment.")
                return

            for it in items[:10]:
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
                await interaction.followup.send(embed=emb, view=view if view else None)

        except Exception as e:
            log.exception("/scan error")
            try:
                await interaction.followup.send(f"Erreur pendant le scan : `{e}`")
            except Exception:
                pass

    async def _cmd_marche(self, interaction: discord.Interaction):
        log.info("/marche invoked")
        try:
            await interaction.response.defer(ephemeral=False)
        except Exception as e:
            log.warning(f"/marche defer failed: {e!r}")

        try:
            self._ensure_login()
            items = fetch_market(self.sess) or []
            log.info("/marche fetched %d offers", len(items))
            if not items:
                await interaction.followup.send("Marché vide pour le moment.")
                return

            for it in items[:10]:
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
                await interaction.followup.send(embed=emb, view=view if view else None)

        except Exception as e:
            log.exception("/marche error")
            try:
                await interaction.followup.send(f"Erreur : `{e}`")
            except Exception:
                pass

    async def _cmd_equipe(self, interaction: discord.Interaction):
        log.info("/equipe invoked")
        try:
            choices = self._choices_from_env()
            log.info("/equipe choices from env: %s", choices)
            view = TeamSelectView(choices)
            await interaction.response.send_message("Sélectionne un manager :", view=view, ephemeral=True)
        except Exception as e:
            log.exception("/equipe error")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Erreur : `{e}`", ephemeral=True)
                else:
                    await interaction.followup.send(f"Erreur : `{e}`", ephemeral=True)
            except Exception:
                pass

    # ==========================
    #  Setup / Sync
    # ==========================
    async def setup_hook(self):
        # Création explicite des commandes
        scan_cmd   = app_commands.Command(name="scan", description="Scanner immédiatement le marché.", callback=self._cmd_scan)
        marche_cmd = app_commands.Command(name="marche", description="Lister le marché courant (10 offres max).", callback=self._cmd_marche)
        equipe_cmd = app_commands.Command(name="equipe", description="Choisir un manager et afficher tout l’effectif.", callback=self._cmd_equipe)

        if self.guild_obj:
            self.tree.clear_commands(guild=self.guild_obj)
            self.tree.add_command(scan_cmd, guild=self.guild_obj)
            self.tree.add_command(marche_cmd, guild=self.guild_obj)
            self.tree.add_command(equipe_cmd, guild=self.guild_obj)
            cmds = await self.tree.sync(guild=self.guild_obj)
            log.info("Slash commands synchronisées (guild %s) : %s", self.guild_obj.id, [c.name for c in cmds])
        else:
            self.tree.clear_commands()
            self.tree.add_command(scan_cmd)
            self.tree.add_command(marche_cmd)
            self.tree.add_command(equipe_cmd)
            cmds = await self.tree.sync()
            log.info("Slash commands synchronisées (global) : %s", [c.name for c in cmds])

    # ==========================
    #  Events
    # ==========================
    async def on_ready(self):
        log.info("Discord connecté: %s", self.user)
        for g in self.guilds:
            log.info("[GUILD] %s (id=%s)", g.name, g.id)
            for c in g.text_channels[:10]:
                log.info("  - [CHAN] %s (id=%s)", c.name, c.id)
        asyncio.create_task(self.loop_poll())

    async def on_interaction(self, interaction: discord.Interaction):
        try:
            data = interaction.data or {}
            cid = (data.get("custom_id") or "")
            if not cid.startswith("details:"):
                return
            pid = int(cid.split(":", 1)[1])
            await self._send_player_details(interaction, pid)
        except Exception:
            log.exception("on_interaction failed")

    async def _send_player_details(self, interaction: discord.Interaction, player_id: int):
        try:
            await interaction.response.defer(ephemeral=False)
        except Exception as e:
            log.warning(f"details defer failed: {e!r}")

        self._ensure_login()
        name, team_acr, pos, mv, pts_avg = self._player_brief(player_id)
        s = fetch_price_series(self.sess, player_id)
        mv90, mvmax, mvmin, momentum, png = _price_features_from_series(s)

        lines = []
        if mv is not None:
            lines.append(f"**Valeur marchée** : {_fmt_num(mv)}")
        if pts_avg is not None:
            lines.append(f"**Points moy.** : {float(pts_avg):.2f}")
        lines.append(
            "**Historique MV** : " +
            " · ".join([
                f"90j: {_fmt_num(mv90)}" if mv90 is not None else "90j: —",
                f"Min365: {_fmt_num(mvmin)}" if mvmin is not None else "Min365: —",
                f"Max365: {_fmt_num(mvmax)}" if mvmax is not None else "Max365: —",
                f"Mom30: {momentum:.2f}%" if momentum is not None else "Mom30: —",
            ])
        )

        emb = discord.Embed(
            title=f"{name} — {team_acr} ({pos})",
            url=f"{BASE}/players/{player_id}",
            description="\n".join(lines),
            color=0x1F8B4C
        )

        file = None
        if png:
            file = discord.File(io.BytesIO(png), filename=f"player_{player_id}_price.png")
            emb.set_image(url=f"attachment://player_{player_id}_price.png")

        await interaction.followup.send(embed=emb, file=file)

    # ==========================
    #  Poll loop
    # ==========================
    async def loop_poll(self):
        await self.wait_until_ready()
        chan = None
        if DISCORD_CHANNEL_ID:
            try:
                chan = self.get_channel(DISCORD_CHANNEL_ID) or await self.fetch_channel(DISCORD_CHANNEL_ID)
            except Exception:
                chan = None

        while not self.is_closed():
            try:
                self._ensure_login()
                items = fetch_market(self.sess) or []

                # log marché
                new_items = []
                for it in items:
                    iid = it.get("id")
                    if iid and iid not in self.last_seen_ids:
                        new_items.append(it)
                        self.last_seen_ids.add(iid)
                log.info("poll: %d offres (%d nouvelles)", len(items), len(new_items))

                if chan and new_items:
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
                        await chan.send(embed=emb, view=view if view else None)
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
    intents.message_content = False

    bot = TopscorerBot(intents=intents)
    token = DISCORD_TOKEN
    if not token:
        log.error("DISCORD_TOKEN manquant")
        return
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())