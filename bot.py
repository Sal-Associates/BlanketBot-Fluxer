import asyncio
import logging
import os
import time

import fluxer
from dotenv import load_dotenv

import db
from framework import BlanketBot
from utils import auto_unmute

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

COGS = [
    "cogs.general",
    "cogs.settings",
    "cogs.staff",
    "cogs.moderation",
    "cogs.muterole",
    "cogs.mod_log",
    "cogs.modlogs",
    "cogs.notes",
    "cogs.purge",
    "cogs.whois",
    "cogs.info",
    "cogs.channel",
    "cogs.automod",
    "cogs.lockdown",
    "cogs.scam_detection",
]

# GUILD_MEMBERS and MESSAGE_CONTENT are privileged intents
intents = fluxer.Intents.default() | fluxer.Intents.GUILD_MEMBERS | fluxer.Intents.MESSAGE_CONTENT


class Bot(BlanketBot):
    def __init__(self):
        super().__init__(intents=intents, api_url=os.getenv("FLUXER_API_URL") or None)
        self._ready_once = False
        self.on("ready")(self._on_ready)

    async def setup_hook(self):
        db.init_db()
        for cog in COGS:
            await self.load_extension(cog)

    async def _on_ready(self):
        print(f"logged in as {self.user.username} ({self.user.id})")
        if self._ready_once:
            return  # READY fires again after a full reconnect
        self._ready_once = True
        await self._restore_timed_mutes()

    async def _restore_timed_mutes(self):
        now = time.time()
        with db.get_db() as conn:
            rows = conn.execute("SELECT * FROM timed_mutes").fetchall()

        for row in rows:
            guild_id, user_id, role_id = row["guild_id"], row["user_id"], row["role_id"]
            if self.get_guild(guild_id) is None:
                continue
            if role_id not in await self.roles(guild_id):
                with db.get_db() as conn:
                    conn.execute("DELETE FROM timed_mutes WHERE id = ?", (row["id"],))
                continue
            member = await self.member(guild_id, user_id)
            if member is None:
                with db.get_db() as conn:
                    conn.execute("DELETE FROM timed_mutes WHERE id = ?", (row["id"],))
                continue
            delay = row["expires_at"] - now
            if delay <= 0:
                if role_id in member.roles:
                    try:
                        await self.http.remove_guild_member_role(guild_id, user_id, role_id, reason="Mute expired (bot restart)")
                    except fluxer.HTTPException:
                        pass
                    self.invalidate_member(guild_id, user_id)
                with db.get_db() as conn:
                    conn.execute("DELETE FROM timed_mutes WHERE id = ?", (row["id"],))
            else:
                asyncio.create_task(auto_unmute(self, row["id"], guild_id, user_id, role_id, delay))


def main():
    token = os.getenv("FLUXER_TOKEN")
    if not token:
        raise RuntimeError("FLUXER_TOKEN is not set. Copy .env.example to .env and fill in your token.")
    Bot().run(token)


if __name__ == "__main__":
    main()