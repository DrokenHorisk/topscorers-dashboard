import os
import time
import asyncio
import logging
import discord
from discord import app_commands

from topscorers import login_session, fetch_market, BASE, POLL_EVERY, DISCORD_CHANNEL_ID

logging.basicConfig(level=logging.INFO)

class TopscorerBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.bg_task = None
        self.sess = None
        self.last_seen_ids = set()
        self.last_fetch_at = 0
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        logging.info(f"Discord connecté: {self.user}")

        # Diagnostic guildes/salons
        try:
            for g in self.guilds:
                logging.info(f"[GUILD] {g.name} (id={g.id})")
                for c in g.text_channels[:10]:
                    logging.info(f"  - [CHAN] {c.name} (id={c.id})")
        except Exception as e:
            logging.warning(f"Impossible de lister guildes/salons: {e}")

        # Sync des slash commands
        try:
            await self.tree.sync()
            logging.info("Slash commands synchronisées.")
        except Exception as e:
            logging.warning(f"Sync slash commands a échoué: {e}")

        self.bg_task = asyncio.create_task(self.loop_poll())

    def _ensure_login(self):
        if self.sess is None:
            logging.info("Connexion à TopScorers…")
            self.sess = login_session()
            logging.info("Connecté à TopScorers")

    def _build_offer_embed(self, item):
        try:
            p = item.get("player", {}) if isinstance(item, dict) else {}
            team = p.get("team") or {}
            pid = p.get("id")
            name = p.get("name") or f"{p.get('firstname','')} {p.get('lastname','')}".strip() or "Joueur"
            pos = p.get("position_name") or "—"
            team_acr = team.get("acronym") or team.get("name") or "—"
            mv = p.get("marketvalue") or item.get("marketvalue")
            price = item.get("price")
            disc_pct = item.get("discount_pct") or item.get("discount") or 0
            pts_avg = p.get("points_avg")
            link = f"{BASE}/players/{pid}" if pid else BASE
        except Exception:
            name, pos, team_acr, mv, price, disc_pct, pts_avg, link = "Joueur","—","—",None,None,None,None,BASE

        title = f"{name} — {team_acr} ({pos})"
        desc = []
        if price is not None: desc.append(f"**Prix**: {int(price):,}".replace(",", " "))
        if mv is not None: desc.append(f"**Valeur marché**: {int(mv):,}".replace(",", " "))
        if disc_pct is not None:
            try:
                desc.append(f"**Décote**: {float(disc_pct):.1f}%")
            except Exception:
                pass
        if pts_avg is not None:
            try:
                desc.append(f"**Pts moy.**: {float(pts_avg):.2f}")
            except Exception:
                pass

        embed = discord.Embed(
            title=title,
            url=link,
            description="\n".join(desc) if desc else "Nouvelle offre détectée.",
            color=0xC8102E
        )
        return embed

    async def loop_poll(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                self._ensure_login()
                items = fetch_market(self.sess)
                chan = self.get_channel(DISCORD_CHANNEL_ID)
                if chan is None:
                    try:
                        chan = await self.fetch_channel(DISCORD_CHANNEL_ID)
                        logging.info(f"Salon résolu via fetch_channel: {getattr(chan, 'name', chan)} ({chan.id})")
                    except Exception as e:
                        logging.warning(f"Channel Discord introuvable (ID={DISCORD_CHANNEL_ID}) : {e}")
                        await asyncio.sleep(POLL_EVERY)
                        continue

                new_items = []
                for it in items:
                    iid = it.get("id")
                    if iid and iid not in self.last_seen_ids:
                        new_items.append(it)
                        self.last_seen_ids.add(iid)

                if new_items:
                    embeds = [self._build_offer_embed(it) for it in new_items]
                    await chan.send(content=f"🆕 **{len(new_items)} nouvelle(s) offre(s)** détectée(s) :", embeds=embeds[:10])

                await asyncio.sleep(POLL_EVERY)
            except Exception as e:
                logging.exception(f"Erreur dans loop_poll: {e}")
                await asyncio.sleep(5)

    @app_commands.command(name="scan", description="Scanner immédiatement le marché et poster les offres récentes.")
    async def scan(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        try:
            self._ensure_login()
            items = fetch_market(self.sess)

            def keyf(x):
                try:
                    return float(x.get("discount_pct") or 0)
                except Exception:
                    return 0.0

            top = sorted(items, key=keyf, reverse=True)[:5]
            if not top:
                await interaction.followup.send("Aucune offre trouvée pour le moment.")
                return

            embeds = [self._build_offer_embed(it) for it in top]
            await interaction.followup.send(content="📊 **Scan terminé — Top offres actuelles :**", embeds=embeds[:10])
        except Exception as e:
            logging.exception("Erreur /scan")
            await interaction.followup.send(f"Erreur pendant le scan : `{e}`")

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
