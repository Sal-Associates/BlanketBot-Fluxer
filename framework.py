"""Thin command framework on top of fluxer.py.

fluxer.py only matches flat prefix commands and has no member/role/channel
caches, so this module adds:

* space separated command paths ("staff mod add") with automatic group usage
* argument converters (member, user, role, channel)
* TTL caches for roles, members and channels (everything else is REST)
* permission and role hierarchy helpers
* channel permission overwrite helpers
"""
import asyncio
import inspect
import logging
import os
import re
import time
import typing
from dataclasses import dataclass

import fluxer
from fluxer import Permissions

log = logging.getLogger("blanketbot")

PREFIX = os.getenv("COMMAND_PREFIX", "?")
ALL_PERMS = (1 << 64) - 1
ROLE_TTL = 30
MEMBER_TTL = 60
CHANNEL_TTL = 30

MENTION_RE = re.compile(r"^<@!?(\d+)>$")
ROLE_MENTION_RE = re.compile(r"^<@&(\d+)>$")
CHANNEL_MENTION_RE = re.compile(r"^<#(\d+)>$")
ID_RE = re.compile(r"^\d{15,22}$")


# --- argument annotation markers -------------------------------------------------
class MemberArg: ...
class UserArg: ...
class RoleArg: ...
class ChannelArg: ...
class IdArg: ...  # integer that tolerates a leading '#'


class UserError(Exception):
    """Raised to show a friendly message to the person who ran the command."""

    def __init__(self, message: str, plain: bool = False):
        super().__init__(message)
        self.plain = plain  # plain=True skips the leading cross mark


@dataclass
class Command:
    path: str
    func: typing.Callable
    cog: object
    level: str | None
    params: list
    hints: dict


def command(path: str, *, level: str | None = None, aliases: tuple = ()):
    """Mark a cog method as a command. level is None, 'mod' or 'admin'."""
    def deco(func):
        func.__blanket_cmd__ = (path, level, tuple(aliases))
        return func
    return deco


class Context:
    def __init__(self, bot, message, guild_id, command):
        self.bot = bot
        self.message = message
        self.author = message.author
        self.guild_id = guild_id
        self.channel_id = message.channel_id
        self.command = command

    @property
    def guild(self):
        return self.bot.get_guild(self.guild_id)

    async def send(self, content=None, *, embed=None, delete_after=None, files=None):
        msg = await self.message.send(content, embed=embed, files=files)
        if delete_after:
            asyncio.create_task(_delete_later(msg, delete_after))
        return msg

    async def convert(self, annotation, token: str):
        return await _convert(self, annotation, token)


async def _delete_later(msg, seconds):
    await asyncio.sleep(seconds)
    try:
        await msg.delete()
    except fluxer.HTTPException:
        pass


async def send_temp(message, content, seconds=5):
    """Send a message to the same channel and delete it after a few seconds."""
    msg = await message.send(content)
    asyncio.create_task(_delete_later(msg, seconds))
    return msg


# --- converters ------------------------------------------------------------------
def parse_user_id(token: str | None) -> int | None:
    if not token:
        return None
    token = token.strip()
    m = MENTION_RE.match(token)
    if m:
        return int(m.group(1))
    if ID_RE.match(token):
        return int(token)
    return None


async def _convert(ctx: Context, ann, token: str):
    bot = ctx.bot
    if ann is MemberArg:
        uid = parse_user_id(token)
        if uid is None:
            raise UserError("Member not found. Use a mention or a user ID.")
        member = await bot.member(ctx.guild_id, uid)
        if member is None:
            raise UserError("Member not found.")
        return member
    if ann is UserArg:
        uid = parse_user_id(token)
        if uid is None:
            raise UserError("User not found. Use a mention or a user ID.")
        for u in ctx.message.mentions:
            if u.id == uid:
                return u
        try:
            return await bot.fetch_user(str(uid))
        except fluxer.NotFound:
            raise UserError("User not found.")
    if ann is RoleArg:
        roles = await bot.roles(ctx.guild_id)
        m = ROLE_MENTION_RE.match(token)
        rid = int(m.group(1)) if m else int(token) if token.isdigit() else None
        if rid is None:
            lowered = token.lower().lstrip("@")
            for r in roles.values():
                if r["name"].lower() == lowered:
                    rid = int(r["id"])
                    break
        if rid is None or rid not in roles:
            raise UserError("Role not found.")
        return fluxer.Role.from_data(roles[rid], bot.http, guild_id=ctx.guild_id)
    if ann is ChannelArg:
        channels = await bot.guild_channels(ctx.guild_id)
        m = CHANNEL_MENTION_RE.match(token)
        cid = int(m.group(1)) if m else int(token) if token.isdigit() else None
        if cid is None:
            lowered = token.lower().lstrip("#")
            for c in channels.values():
                if (c.get("name") or "").lower() == lowered:
                    cid = int(c["id"])
                    break
        if cid is None or cid not in channels:
            raise UserError("Channel not found.")
        return fluxer.Channel.from_data(channels[cid], bot.http)
    if ann is IdArg:
        try:
            return int(token.replace("#", ""))
        except ValueError:
            raise UserError("Expected a number.")
    if ann is int:
        try:
            return int(token)
        except ValueError:
            raise UserError(f"`{token}` is not a number.")
    return token


async def _bind(ctx: Context, cmd: Command, rest: str):
    """Turn the remaining text into positional args and kwargs for cmd."""
    args, kwargs = [], {}
    for p in cmd.params:
        ann = cmd.hints.get(p.name, str)
        optional = p.default is not inspect.Parameter.empty
        if p.kind is inspect.Parameter.KEYWORD_ONLY or p.kind is inspect.Parameter.VAR_POSITIONAL:
            value = rest.strip()
            rest = ""
            if not value:
                if optional:
                    continue
                raise UserError(f"Missing argument: `{p.name}`.")
            kwargs[p.name] = await _convert(ctx, ann, value)
            continue
        rest = rest.lstrip()
        if not rest:
            if optional:
                args.append(p.default)
                continue
            raise UserError(f"Missing argument: `{p.name}`.")
        m = re.match(r"(\S+)\s*(.*)", rest, re.S)
        token, rest = m.group(1), m.group(2)
        args.append(await _convert(ctx, ann, token))
    return args, kwargs


# --- bot -------------------------------------------------------------------------
class BlanketBot(fluxer.Bot):
    def __init__(self, **kwargs):
        super().__init__(command_prefix=PREFIX, **kwargs)
        self.commands: dict[str, Command] = {}
        self._roles: dict[int, tuple[float, dict]] = {}
        self._members: dict[tuple[int, int], tuple[float, fluxer.GuildMember | None]] = {}
        self._channels_cache: dict[int, tuple[float, dict]] = {}
        self._channel_guilds: dict[int, int | None] = {}
        self.on("message")(self._route_message)

    @property
    def http(self):
        return self._http

    # command registration -----------------------------------------------------
    def register_cog_commands(self, cog):
        for name in dir(cog):
            if name.startswith("_"):
                continue
            method = getattr(cog, name, None)
            meta = getattr(method, "__blanket_cmd__", None)
            if not meta:
                continue
            path, level, aliases = meta
            sig = inspect.signature(method)
            params = list(sig.parameters.values())[1:]  # drop ctx
            try:
                hints = typing.get_type_hints(method)
            except Exception:
                hints = {}
            names = [path] + [" ".join(path.split()[:-1] + [a]) for a in aliases]
            for n in names:
                self.commands[n.lower()] = Command(n.lower(), method, cog, level, params, hints)

    # routing ------------------------------------------------------------------
    async def guild_id_of(self, message) -> int | None:
        if message.guild_id:
            return message.guild_id
        cid = message.channel_id
        if cid not in self._channel_guilds:
            try:
                data = await self.http.get_channel(cid)
                self._channel_guilds[cid] = int(data["guild_id"]) if data.get("guild_id") else None
            except fluxer.HTTPException:
                self._channel_guilds[cid] = None
        return self._channel_guilds[cid]

    async def _route_message(self, message):
        if message.author.bot or not message.content or not message.content.startswith(PREFIX):
            return
        body = message.content[len(PREFIX):]
        tokens = body.split()
        if not tokens:
            return
        cmd, used = None, 0
        for n in range(min(len(tokens), 4), 0, -1):
            key = " ".join(t.lower() for t in tokens[:n])
            if key in self.commands:
                cmd, used = self.commands[key], n
                break
        guild_id = await self.guild_id_of(message)
        if guild_id is None:
            return  # commands only work in servers
        if cmd is None:
            for n in range(min(len(tokens), 3), 0, -1):
                key = " ".join(t.lower() for t in tokens[:n])
                children = [c for p, c in self.commands.items() if p.startswith(key + " ")]
                if not children:
                    continue
                levels = {c.level for c in children}
                required = None if None in levels else "mod" if "mod" in levels else "admin"
                ctx = Context(self, message, guild_id, None)
                if required and not await self._allowed(ctx, required):
                    return
                subs = sorted({c.path[len(key) + 1:].split()[0] for c in children})
                await message.send(f"❌ Usage: `{PREFIX}{key} {'|'.join(subs)}`")
                return
            return

        ctx = Context(self, message, guild_id, cmd)
        try:
            if cmd.level and not await self._allowed(ctx, cmd.level):
                raise UserError("You don't have permission to use this command.", plain=True)
            rest = re.sub(r"^\s*(\S+\s*){%d}" % used, "", body, count=1)
            args, kwargs = await _bind(ctx, cmd, rest)
            await cmd.func(ctx, *args, **kwargs)
        except UserError as e:
            await message.send(str(e) if e.plain else f"❌ {e}")
        except fluxer.Forbidden:
            await message.send("❌ I don't have permission to do that.")
        except fluxer.HTTPException as e:
            log.warning("HTTP error in %s: %s", cmd.path, e)
            await message.send(f"❌ Request failed: {e}")
        except Exception:
            log.exception("Error in command %s", cmd.path)
            await message.send("Something went wrong. Please try again.")

    async def _allowed(self, ctx: Context, level: str) -> bool:
        import checks
        member = await self.member(ctx.guild_id, ctx.author.id)
        if member is None:
            return False
        if level == "admin":
            return await checks.is_admin(self, ctx.guild_id, member)
        return await checks.is_mod(self, ctx.guild_id, member)

    # cached REST --------------------------------------------------------------
    async def roles(self, guild_id: int) -> dict[int, dict]:
        hit = self._roles.get(guild_id)
        if hit and time.monotonic() - hit[0] < ROLE_TTL:
            return hit[1]
        data = await self.http.get_guild_roles(guild_id)
        roles = {int(r["id"]): r for r in data}
        self._roles[guild_id] = (time.monotonic(), roles)
        return roles

    def invalidate_roles(self, guild_id: int):
        self._roles.pop(guild_id, None)

    async def member(self, guild_id: int, user_id: int, *, fresh: bool = False):
        key = (guild_id, user_id)
        hit = self._members.get(key)
        if hit and not fresh and time.monotonic() - hit[0] < MEMBER_TTL:
            return hit[1]
        try:
            data = await self.http.get_guild_member(guild_id, user_id)
            member = fluxer.GuildMember.from_data(data, self.http, guild_id=guild_id)
        except fluxer.NotFound:
            member = None
        if len(self._members) > 5000:
            self._members.clear()
        self._members[key] = (time.monotonic(), member)
        return member

    def invalidate_member(self, guild_id: int, user_id: int):
        self._members.pop((guild_id, user_id), None)

    async def guild_channels(self, guild_id: int) -> dict[int, dict]:
        hit = self._channels_cache.get(guild_id)
        if hit and time.monotonic() - hit[0] < CHANNEL_TTL:
            return hit[1]
        data = await self.http.get_guild_channels(guild_id)
        channels = {int(c["id"]): c for c in data}
        self._channels_cache[guild_id] = (time.monotonic(), channels)
        return channels

    def invalidate_channels(self, guild_id: int):
        self._channels_cache.pop(guild_id, None)

    # permissions --------------------------------------------------------------
    async def owner_id(self, guild_id: int) -> int | None:
        guild = self.get_guild(guild_id)
        if guild and guild.owner_id:
            return guild.owner_id
        try:
            return int((await self.http.get_guild(guild_id))["owner_id"])
        except (fluxer.HTTPException, KeyError):
            return None

    async def perms(self, guild_id: int, member) -> int:
        if member.user.id == await self.owner_id(guild_id):
            return ALL_PERMS
        roles = await self.roles(guild_id)
        total = int(roles.get(guild_id, {}).get("permissions", 0))
        for rid in member.roles:
            if rid in roles:
                total |= int(roles[rid]["permissions"])
        if total & Permissions.ADMINISTRATOR:
            return ALL_PERMS
        return total

    async def top_position(self, guild_id: int, member) -> int:
        roles = await self.roles(guild_id)
        return max((int(roles[r]["position"]) for r in member.roles if r in roles), default=0)

    async def can_act_on(self, guild_id: int, actor, target) -> bool:
        """True if actor outranks target (administrators and the owner always do)."""
        if await self.perms(guild_id, actor) & Permissions.ADMINISTRATOR:
            return True
        if target.user.id == await self.owner_id(guild_id):
            return False
        return await self.top_position(guild_id, actor) > await self.top_position(guild_id, target)

    async def me(self, guild_id: int):
        return await self.member(guild_id, self.user.id)

    # channel permission overwrites -------------------------------------------
    async def overwrite_bits(self, channel_id: int, target_id: int) -> tuple[int, int]:
        data = await self.http.get_channel(channel_id)
        for ow in data.get("permission_overwrites") or []:
            if int(ow["id"]) == target_id:
                return int(ow.get("allow", 0)), int(ow.get("deny", 0))
        return 0, 0

    async def get_perm_state(self, channel_id: int, target_id: int, perm: Permissions):
        """True (allowed), False (denied) or None (inherited) for a role overwrite."""
        allow, deny = await self.overwrite_bits(channel_id, target_id)
        if deny & perm:
            return False
        if allow & perm:
            return True
        return None

    async def set_perm_state(self, channel_id: int, target_id: int, changes: dict):
        """changes maps Permissions -> True/False/None, other bits are preserved."""
        allow, deny = await self.overwrite_bits(channel_id, target_id)
        for perm, value in changes.items():
            allow &= ~int(perm)
            deny &= ~int(perm)
            if value is True:
                allow |= int(perm)
            elif value is False:
                deny |= int(perm)
        await self.http.edit_channel_permissions(channel_id, target_id, allow=allow, deny=deny, type=0)


class BlanketCog(fluxer.Cog):
    """fluxer.Cog that also registers @command methods with the bot."""

    def __init__(self, bot):
        super().__init__(bot)
        bot.register_cog_commands(self)


def is_text_channel(raw: dict) -> bool:
    return raw.get("type") in (0, 5)
