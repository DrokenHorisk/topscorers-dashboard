import os, io, asyncio, logging
import discord
from discord import app_commands
from discord.ui import View, Button, Select

from topscorers import (
    login_session, fetch_market, fetch_price_series,
    _price_features_from_series, BASE, POLL_EVERY, DISCORD_CHANNEL_ID
)

logging.basicConfig(level=logging.INFO)

def _fmt_num(x):
    try:
        return f"{int(x):,}".replace(",", " ")
    except Exception:
        return "—"

# -------- Views / UI --------

class OfferView(View):
    def __init__(self, player_id: int, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.player_id = player_id
        self.add_item(Button(label="Détails", style=discord.ButtonStyle.primary, custom_id=f"details:{player_id}"))

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
        sel = self.values[0]
        # simple ack; pas de defer ici
        if not interaction.response.is_done():
            await interaction.response.edit_message(
                content=f"✅ Manager sélectionné — team_id **{sel}** (à brancher sur ton endpoint équipe).",
                view=None
            )
        else:
            await interaction.followup.edit_message(
                interaction.message.id,
                content=f"✅ Manager sélectionné — team_id **{sel}** (à brancher sur ton endpoint équipe).",
                view=None
            )

class TeamSelectView(View):
    def __init__(self, choices, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.add_item(TeamSelect(choices))


# -------- Bot --------

class TopscorerBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.sess = None
        self.last_seen_ids = set()
        self.guild_obj = None

        gid = os.getenv("DISCORD_GUILD_ID")
        if gid:
            try:
                self.guild_obj = discord.Object(id=int(gid))
            except Exception:
                logging.warning("DISCORD_GUILD_ID invalide; sync global en secours.")

        self.league_id = os.getenv("TOPS_LEAGUE_ID", "92556")
        self.other_team_ids = self._parse_ids(os.getenv("OTHER_TEAM_IDS",""))

    # ---- Helpers ----
    @staticmethod
    def _parse_ids(s):
        out = []
        for tok in (s or "").replace(";", ",").split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                out.append(int(tok))
            except Exception:
                pass
        # dédup en gardant l’ordre
        seen, dedup = set(), []
        for x in out:
            if x not in seen:
                seen.add(x); dedup.append(x)
        return dedup

    def _ensure_login(self):
        if self.sess is None:
            logging.info("Connexion à TopScorers…")
            self.sess = login_session()
            logging.info("Connecté à TopScorers")

    # ====== helpers “dashboard-like” pour managers/club ======
    @staticmethod
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

    def _get_team_username(self, team_id: int):
        """Essaye /stats puis /teams pour récupérer le username."""
        for path in (f"{BASE}/api/user/teams/{int(team_id)}/stats",
                     f"{BASE}/api/user/teams/{int(team_id)}"):
            try:
                r = self.sess.get(path, timeout=15)
                if r.status_code != 200:
                    continue
                j = r.json()
                d = j.get("data", j)
                if isinstance(d, list) and d:
                    d = d[0]
                u = self._extract_username_from_payload(d)
                if u:
                    return u
            except Exception:
                continue
        return ""

    def _get_team_club(self, team_id: int):
        """Récupère acronym / name du club associé à ce manager."""
        try:
            r = self.sess.get(f"{BASE}/api/user/teams/{int(team_id)}", timeout=15)
            if r.status_code != 200:
                return ""
            j = r.json()
            d = j.get("data", j)
            if isinstance(d, list) and d:
                d = d[0]
            team_obj = d.get("team") or {}
            return (team_obj.get("acronym") or team_obj.get("name") or "").strip()
        except Exception:
            return ""

    def _get_league_managers(self):
        """
        Construit la liste (label=username, desc=club, value=team_id)
         - à partir de OTHER_TEAM_IDS (toujours)
         - + tente d’ajouter ceux de la ligue si l’endpoint fonctionne
        """
        choices = []

        # 1) From OTHER_TEAM_IDS (fiable selon ton .env)
        for tid in self.other_team_ids:
            uname = self._get_team_username(tid) or f"Équipe {tid}"
            club  = self._get_team_club(tid)
            choices.append((uname, club, tid))

        # 2) Ligue (best-effort)
        try:
            r = self.sess.get(f"{BASE}/api/user/leagues/{int(self.league_id)}/teams", timeout=20)
            r.raise_for_status()
            data = (r.json().get("data") or [])
            for t in data:
                tid = t.get("id")
                if not isinstance(tid, int):
                    continue
                uname = (
                    t.get("username")
                    or (t.get("user") or {}).get("username")
                    or (t.get("user") or {}).get("name")
                    or f"Équipe {tid}"
                )
                team_obj = t.get("team") or {}
                club = team_obj.get("acronym") or team_obj.get("name") or ""
                choices.append((str(uname).strip(), str(club).strip(), tid))
        except Exception as e:
            logging.warning(f"Managers ligue: {e}")

        # dédup par team_id en gardant le 1er
        seen, dedup = set(), []
        for (lab, desc, tid) in choices:
            if tid in seen:
                continue
            seen.add(tid); dedup.append((lab, desc, tid))

        return dedup[:25] or [("Aucun manager", "", 0)]

    def _get_player_brief(self, player_id: int):
        """Retourne (name, team_acr, pos, marketvalue, points_avg)."""
        try:
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
        except Exception:
            return f"Joueur #{player_id}", "—", "—", None, None

    # ---------- Commands ----------
    async def setup_hook(self):
        async def cmd_scan(interaction: discord.Interaction):
            try:
                self._ensure_login()
                items = fetch_market(self.sess) or []
                if not items:
                    await interaction.response.send_message("Aucune offre trouvée pour le moment.")
                    return

                # première réponse
                it0 = items[0]
                p0 = it0.get("player", {}) if isinstance(it0, dict) else {}
                team0 = p0.get("team") or {}
                pid0 = p0.get("id")
                name0 = p0.get("name") or f"{p0.get('firstname','')} {p0.get('lastname','')}".strip() or "Joueur"
                pos0 = p0.get("position_name") or "—"
                team_acr0 = team0.get("acronym") or team0.get("name") or "—"
                mv0 = p0.get("marketvalue") or it0.get("marketvalue")
                price0 = it0.get("price")
                link0 = f"{BASE}/players/{pid0}" if pid0 else BASE
                emb0 = discord.Embed(
                    title=f"{name0} — {team_acr0} ({pos0})",
                    url=link0,
                    description=f"**Prix**: {_fmt_num(price0)}\n**Valeur marchée**: {_fmt_num(mv0)}",
                    color=0xC8102E
                )
                view0 = OfferView(pid0) if pid0 else None
                await interaction.response.send_message(embed=emb0, view=view0 if view0 else None)

                # suite
                for it in items[1:5]:
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
                    await interaction.followup.send(embed=emb, view=view if view else None)
            except Exception as e:
                logging.exception("/scan")
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Erreur pendant le scan : `{e}`")
                else:
                    await interaction.followup.send(f"Erreur pendant le scan : `{e}`")

        async def cmd_marche(interaction: discord.Interaction):
            try:
                self._ensure_login()
                items = fetch_market(self.sess) or []
                if not items:
                    await interaction.response.send_message("Marché vide pour le moment.")
                    return

                it0 = items[0]
                p0 = it0.get("player", {}) if isinstance(it0, dict) else {}
                team0 = p0.get("team") or {}
                pid0 = p0.get("id")
                name0 = p0.get("name") or f"{p0.get('firstname','')} {p0.get('lastname','')}".strip() or "Joueur"
                pos0 = p0.get("position_name") or "—"
                team_acr0 = team0.get("acronym") or team0.get("name") or "—"
                mv0 = p0.get("marketvalue") or it0.get("marketvalue")
                price0 = it0.get("price")
                link0 = f"{BASE}/players/{pid0}" if pid0 else BASE
                emb0 = discord.Embed(
                    title=f"{name0} — {team_acr0} ({pos0})",
                    url=link0,
                    description=f"**Prix**: {_fmt_num(price0)}\n**Valeur marchée**: {_fmt_num(mv0)}",
                    color=0x5865F2
                )
                view0 = OfferView(pid0) if pid0 else None
                await interaction.response.send_message(embed=emb0, view=view0 if view0 else None)

                for it in items[1:10]:
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
                        color=0x5865F2
                    )
                    view = OfferView(pid) if pid else None
                    await interaction.followup.send(embed=emb, view=view if view else None)
            except Exception as e:
                logging.exception("/marche")
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Erreur : `{e}`")
                else:
                    await interaction.followup.send(f"Erreur : `{e}`")

        async def cmd_equipe(interaction: discord.Interaction):
            try:
                self._ensure_login()
                choices = self._get_league_managers()
                view = TeamSelectView(choices)
                await interaction.response.send_message("Sélectionne un manager :", view=view, ephemeral=True)
            except Exception as e:
                logging.exception("/equipe")
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Erreur : `{e}`", ephemeral=True)
                else:
                    await interaction.followup.send(f"Erreur : `{e}`", ephemeral=True)

        if self.guild_obj:
            try:
                self.tree.clear_commands(guild=self.guild_obj)
            except Exception:
                pass
            self.tree.add_command(app_commands.Command(name="scan", description="Scanner immédiatement le marché.", callback=cmd_scan), guild=self.guild_obj)
            self.tree.add_command(app_commands.Command(name="marche", description="Lister le marché courant (10 offres).", callback=cmd_marche), guild=self.guild_obj)
            self.tree.add_command(app_commands.Command(name="equipe", description="Choisir un manager de la ligue.", callback=cmd_equipe), guild=self.guild_obj)
            cmds_g = await self.tree.sync(guild=self.guild_obj)
            logging.info(f"Slash commands synchronisées (guild {self.guild_obj.id}) : {[c.name for c in cmds_g]}")
        else:
            self.tree.clear_commands()
            self.tree.add_command(app_commands.Command(name="scan", description="Scanner immédiatement le marché.", callback=cmd_scan))
            self.tree.add_command(app_commands.Command(name="marche", description="Lister le marché courant (10 offres).", callback=cmd_marche))
            self.tree.add_command(app_commands.Command(name="equipe", description="Choisir un manager de la ligue.", callback=cmd_equipe))
            cmds = await self.tree.sync()
            logging.info(f"Slash commands synchronisées (global) : {[c.name for c in cmds]}")

    # ---------- Events ----------
    async def on_ready(self):
        logging.info(f"Discord connecté: {self.user}")
        for g in self.guilds:
            logging.info(f"[GUILD] {g.name} (id={g.id})")
            for c in g.text_channels[:10]:
                logging.info(f"  - [CHAN] {c.name} (id={c.id})")
        asyncio.create_task(self.loop_poll())

    async def on_interaction(self, interaction: discord.Interaction):
        try:
            data = interaction.data or {}
            cid = data.get("custom_id")
            if not cid or not cid.startswith("details:"):
                return
            pid = int(cid.split(":", 1)[1])
            await self._send_player_details(interaction, pid)
        except Exception:
            logging.exception("on_interaction failed")

    async def _send_player_details(self, interaction: discord.Interaction, player_id: int):
        # ❌ pas de defer ici pour éviter "Unknown interaction"
        self._ensure_login()

        name, team_acr, pos, mv, pts_avg = self._get_player_brief(player_id)
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
                f"90j: {_fmt_num(round(mv90))}" if mv90 is not None else "90j: —",
                f"Min365: {_fmt_num(round(mvmin))}" if mvmin is not None else "Min365: —",
                f"Max365: {_fmt_num(round(mvmax))}" if mvmax is not None else "Max365: —",
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

        if not interaction.response.is_done():
            await interaction.response.send_message(embed=emb, file=file)
        else:
            await interaction.followup.send(embed=emb, file=file)

    async def loop_poll(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                self._ensure_login()
                items = fetch_market(self.sess) or []

                chan = None
                if DISCORD_CHANNEL_ID:
                    chan = self.get_channel(DISCORD_CHANNEL_ID) or await self.fetch_channel(DISCORD_CHANNEL_ID)

                new_items = []
                for it in items:
                    iid = it.get("id")
                    if iid and iid not in self.last_seen_ids:
                        new_items.append(it)
                        self.last_seen_ids.add(iid)

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

                await asyncio.sleep(POLL_EVERY)
            except Exception:
                logging.exception("loop_poll")
                await asyncio.sleep(5)

# -------- Entrypoint --------

async def main():
    intents = discord.Intents.none()
    intents.guilds = True
    intents.messages = True
    intents.message_content = False
    bot = TopscorerBot(intents=intents)
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logging.error("DISCORD_TOKEN manquant")
        return
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
