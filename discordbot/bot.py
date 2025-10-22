import os
import logging
from typing import Dict, List, Tuple, Optional

import discord
from discord import app_commands
from discord.ext import commands

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("topscorer-bot")

# ---------- Utils ----------
def parse_team_names_env(env: str) -> List[Tuple[int, str]]:
    """
    Parse OTHER_TEAM_NAMES="506387=Droken,496919=Traxxx76"
    -> [(506387, "Droken"), (496919, "Traxxx76")]
    """
    out: List[Tuple[int, str]] = []
    if not env:
        return out
    parts = [p.strip() for p in env.split(",") if p.strip()]
    for p in parts:
        if "=" not in p:
            continue
        left, right = p.split("=", 1)
        left = left.strip()
        right = right.strip()
        if not left or not right:
            continue
        try:
            tid = int(left)
        except ValueError:
            continue
        out.append((tid, right))
    return out

def lookup_team(manager_arg: str, pairs: List[Tuple[int, str]]) -> Optional[Tuple[int, str]]:
    """
    manager_arg peut être un pseudo exact (case-insensitive) ou un team_id (str/int).
    """
    s = manager_arg.strip()
    if not s:
        return None
    # Essai id
    try:
        as_id = int(s)
        for tid, name in pairs:
            if tid == as_id:
                return (tid, name)
    except ValueError:
        pass

    # Essai pseudo (case-insensitive, exact)
    s_lower = s.lower()
    for tid, name in pairs:
        if name.lower() == s_lower:
            return (tid, name)

    # Essai pseudo (case-insensitive, startswith)
    for tid, name in pairs:
        if name.lower().startswith(s_lower):
            return (tid, name)

    return None


class TopScorersBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

        # ENV
        self.discord_token = os.getenv("DISCORD_TOKEN", "")
        guild_id_str = os.getenv("DISCORD_GUILD_ID", "").strip()
        self.guild_id = int(guild_id_str) if guild_id_str.isdigit() else None

        self.backend_base = os.getenv("BACKEND_BASE_URL", "")
        self.poll_every = int(os.getenv("POLL_EVERY", os.getenv("POLL_INTERVAL_SEC", "120")) or "120")
        self.seen_path = os.getenv("SEEN_PATH", "/data/seen_transfers.json")

        pairs = parse_team_names_env(os.getenv("OTHER_TEAM_NAMES", ""))
        self.manager_pairs: List[Tuple[int, str]] = pairs
        self.manager_map: Dict[int, str] = {tid: name for tid, name in pairs}

        # Command tree
        self.tree = app_commands.CommandTree(self)
        self._register_app_commands()

    # ---------- Slash commands ----------
    def _register_app_commands(self) -> None:
        # /managers  -> affiche la liste disponible
        @self.tree.command(name="managers", description="Liste les managers configurés")
        async def managers_cmd(interaction: discord.Interaction):
            if not self.manager_pairs:
                await interaction.response.send_message(
                    "Aucun manager configuré. Renseigne la variable OTHER_TEAM_NAMES.",
                    ephemeral=True,
                )
                return
            lines = [f"- **{name}** (team_id `{tid}`)" for tid, name in self.manager_pairs]
            await interaction.response.send_message(
                "Managers disponibles :\n" + "\n".join(lines),
                ephemeral=True,
            )

        # /equipe <manager>  -> manager = pseudo OU team_id
        @self.tree.command(name="equipe", description="Voir l'équipe d'un manager (argument = pseudo OU team_id)")
        async def equipe_cmd(interaction: discord.Interaction, manager: str):
            # Pas de @describe / @choices pour éviter le bug de Parameter(...)
            found = lookup_team(manager, self.manager_pairs)
            if not found:
                txt = (
                    "Manager introuvable.\n"
                    "Utilise `/managers` pour voir la liste, puis `/equipe <pseudo>` ou `/equipe <team_id>`."
                )
                await interaction.response.send_message(txt, ephemeral=True)
                return

            team_id, pseudo = found
            # Ici tu peux appeler ton backend/topscorers si tu veux enrichir.
            msg = f"**Manager :** {pseudo}\n**team_id :** `{team_id}`"
            await interaction.response.send_message(msg, ephemeral=True)

        # /marche  (placeholder)
        @self.tree.command(name="marche", description="Voir le marché (placeholder)")
        async def marche_cmd(interaction: discord.Interaction):
            await interaction.response.send_message(
                "Marché : placeholder OK ✅",
                ephemeral=True,
            )

        # /scan (placeholder)
        @self.tree.command(name="scan", description="Scanner maintenant (placeholder)")
        async def scan_cmd(interaction: discord.Interaction):
            await interaction.response.send_message(
                f"Scan lancé (POLL_EVERY={self.poll_every}s, SEEN_PATH={self.seen_path})",
                ephemeral=True,
            )

    # ---------- Hooks ----------
    async def setup_hook(self) -> None:
        try:
            if self.guild_id:
                log.info(f"Scope guilde forcé: {self.guild_id}")
                guild = discord.Object(id=self.guild_id)

                # On copie les commandes globales vers la guilde puis sync
                # (pas de manip exotique qui pourrait toucher Parameter)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info(f"Commandes guildes synchronisées ({len(synced)}).")
            else:
                log.info("Scope global (DISCORD_GUILD_ID vide). Sync global…")
                synced = await self.tree.sync()
                log.info(f"Commandes globales synchronisées ({len(synced)}).")
        except Exception as e:
            log.warning(f"Enregistrement/sync des commandes a échoué: {e}")

    async def on_ready(self) -> None:
        log.info(f"Discord connecté: {self.user}")
        for g in self.guilds:
            log.info(f"[GUILD] {g.name} (id={g.id})")
            for ch in g.text_channels:
                log.info(f"  - [CHAN] {ch.name} (id={ch.id})")

        log.info(f"BACKEND_BASE_URL={self.backend_base}")
        log.info(f"POLL_EVERY={self.poll_every}")
        log.info(f"SEEN_PATH={self.seen_path}")

        if not self.manager_pairs:
            log.warning("Aucun manager trouvé dans OTHER_TEAM_NAMES.")
        else:
            pretty = ", ".join([f"{tid}={name}" for tid, name in self.manager_pairs])
            log.info(f"Managers chargés: {pretty}")


if __name__ == "__main__":
    bot = TopScorersBot()
    if not bot.discord_token:
        log.error("DISCORD_TOKEN manquant.")
        raise SystemExit(1)
    bot.run(bot.discord_token)
