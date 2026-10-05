import io
import logging
import os
from collections import OrderedDict
from dataclasses import dataclass

import aiohttp
import fluxer
from fluxer import Embed, File

import db
from framework import BlanketCog
from utils import (
    BLUE, BLURPLE, DARK_GRAY, DARK_ORANGE, DARK_RED, GREEN, GREYPLE, LIGHT_GRAY,
    ORANGE, RED, TEAL, YELLOW, fmt_dt, iso_now, user_label,
)

log = logging.getLogger("blanketbot")

_FALLBACK_LOG_CHANNEL = int(os.getenv("LOG_CHANNEL_ID", 0))
IMAGE_CACHE_MAX = 500
MESSAGE_CACHE_MAX = 5000
MAX_IMAGE_BYTES = 8 * 1024 * 1024

ACTION_COLORS = {
    "kick": ORANGE,
    "ban": RED,
    "unban": GREEN,
    "mute": DARK_ORANGE,
    "unmute": TEAL,
    "warn": YELLOW,
    "softban": DARK_RED,
    "lock": DARK_GRAY,
    "unlock": LIGHT_GRAY,
    "purge": GREYPLE,
    "lockdown_enable": RED,
    "lockdown_disable": GREEN,
}


@dataclass
class Target:
    kind: str  # "user", "channel" or "guild"
    id: int
    label: str


def user_target(user) -> Target:
    return Target("user", getattr(user, "user", user).id, user_label(user))


def log_channel_id(guild_id: int) -> int:
    settings = db.get_guild_settings(guild_id)
    if settings and settings["log_channel"]:
        return settings["log_channel"]
    return _FALLBACK_LOG_CHANNEL


async def post_log(bot, guild_id: int, embed: Embed, files: list | None = None):
    channel_id = log_channel_id(guild_id)
    if not channel_id:
        return
    try:
        await bot.http.send_message(
            channel_id,
            embeds=[embed],
            files=[f.to_dict() for f in files] if files else None,
        )
    except fluxer.HTTPException as e:
        log.warning("Couldn't post to log channel %s: %s", channel_id, e)


async def record_action(bot, guild_id: int, action: str, moderator, target: Target,
                        reason: str | None, duration: str | None = None):
    """Store a case in the database and post it to the log channel."""
    mod_user = getattr(moderator, "user", moderator)
    with db.get_db() as conn:
        case_number = db.next_case_number(conn, guild_id)
        conn.execute(
            "INSERT INTO mod_actions (guild_id, case_number, action, target_id, moderator_id, moderator_display, reason, duration) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, case_number, action, target.id, mod_user.id, None, reason, duration),
        )

    embed = Embed(
        title=f"Case #{case_number} \u2014 {action.replace('_', ' ').capitalize()}",
        color=ACTION_COLORS.get(action, BLURPLE),
        timestamp=iso_now(),
    )
    if target.kind == "user":
        embed.add_field(name="User", value=f"{target.label} ({target.id})", inline=True)
    elif target.kind == "channel":
        embed.add_field(name="Channel", value=f"<#{target.id}> ({target.id})", inline=True)
    elif target.kind == "guild":
        embed.add_field(name="Server", value=f"{target.label} ({target.id})", inline=True)
    else:
        embed.add_field(name="Target", value=target.label, inline=True)

    embed.add_field(name="Moderator", value=f"{user_label(mod_user)} ({mod_user.id})", inline=True)
    if duration:
        embed.add_field(name="Duration", value=duration, inline=True)
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    await post_log(bot, guild_id, embed)
    return case_number


@dataclass
class CachedMessage:
    guild_id: int
    channel_id: int
    author_id: int
    author_label: str
    content: str


class ModLog(BlanketCog):
    """Message and member logging.

    Fluxer only sends ids for deleted messages and only the new version of an
    edited message, so the previous content comes from a small in-memory cache
    of messages seen since the bot started.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self._messages: OrderedDict[int, CachedMessage] = OrderedDict()
        self._image_cache: dict[int, list[tuple[bytes, str]]] = {}

    @fluxer.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        guild_id = await self.bot.guild_id_of(message)
        if not guild_id:
            return

        self._messages[message.id] = CachedMessage(
            guild_id, message.channel_id, message.author.id,
            f"{user_label(message.author)} ({message.author.id})", message.content or "",
        )
        while len(self._messages) > MESSAGE_CACHE_MAX:
            self._messages.popitem(last=False)

        images = [a for a in message.attachments if a.content_type and a.content_type.startswith("image/")]
        if not images:
            return
        cached = []
        try:
            async with aiohttp.ClientSession() as session:
                for att in images:
                    if att.size > MAX_IMAGE_BYTES:
                        continue
                    async with session.get(att.url) as resp:
                        cached.append((await resp.read(), att.filename))
        except aiohttp.ClientError as e:
            log.warning("Image cache download failed: %s", e)
            return
        if len(self._image_cache) >= IMAGE_CACHE_MAX:
            del self._image_cache[next(iter(self._image_cache))]
        self._image_cache[message.id] = cached

    @fluxer.Cog.listener()
    async def on_member_join(self, data):
        user = fluxer.User.from_data(data["user"], self.bot.http)
        guild_id = int(data["guild_id"])
        embed = Embed(
            title="Member joined",
            description=f"{user.mention} ({user})",
            color=GREEN,
            timestamp=iso_now(),
        )
        embed.add_field(name="Account created", value=fmt_dt(user.created_at))
        embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
        await post_log(self.bot, guild_id, embed)

    @fluxer.Cog.listener()
    async def on_member_remove(self, data):
        user = fluxer.User.from_data(data["user"], self.bot.http)
        guild_id = int(data["guild_id"])
        self.bot.invalidate_member(guild_id, user.id)
        embed = Embed(
            title="Member left",
            description=f"{user} ({user.id})",
            color=DARK_GRAY,
            timestamp=iso_now(),
        )
        await post_log(self.bot, guild_id, embed)

    @fluxer.Cog.listener()
    async def on_message_delete(self, data):
        cached = self._messages.pop(int(data["id"]), None)
        if not cached:
            return
        images = self._image_cache.pop(int(data["id"]), None)
        embed = Embed(
            title="Message deleted",
            description=cached.content or "*[no text content]*",
            color=DARK_RED,
            timestamp=iso_now(),
        )
        embed.add_field(name="Author", value=cached.author_label, inline=True)
        embed.add_field(name="Channel", value=f"<#{cached.channel_id}>", inline=True)
        files = [File(io.BytesIO(raw), filename=name) for raw, name in images] if images else None
        await post_log(self.bot, cached.guild_id, embed, files)

    @fluxer.Cog.listener()
    async def on_message_edit(self, message):
        cached = self._messages.get(message.id)
        if not cached or message.author.bot:
            return
        new_content = message.content or ""
        if cached.content == new_content:
            return
        old_content = cached.content
        cached.content = new_content
        embed = Embed(title="Message edited", color=BLUE, timestamp=iso_now())
        embed.add_field(name="Before", value=old_content[:1024] or "*empty*", inline=False)
        embed.add_field(name="After", value=new_content[:1024] or "*empty*", inline=False)
        embed.add_field(name="Author", value=cached.author_label, inline=True)
        embed.add_field(name="Channel", value=f"<#{cached.channel_id}>", inline=True)
        await post_log(self.bot, cached.guild_id, embed)


async def setup(bot):
    await bot.add_cog(ModLog(bot))