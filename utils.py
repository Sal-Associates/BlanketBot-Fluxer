import asyncio
import re
from datetime import datetime, timedelta, timezone

import fluxer

LINK_RE = re.compile(r"https?://\S+", re.IGNORECASE)
INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"(?:"
    r"fluxer\.gg"
    r"|discord\.(?:gg|io|me|li)"
    r"|discordapp\.com/invite"
    r"|discord\.com/invite"
    r"|t\.me"
    r"|telegram\.(?:me|dog)"
    r")/\S+",
    re.IGNORECASE,
)

_DURATION_RE = re.compile(
    r"^(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$",
    re.IGNORECASE,
)

# embed colours (fluxer.Embed takes plain ints)
BLURPLE = 0x5865F2
RED = 0xED4245
GREEN = 0x57F287
ORANGE = 0xE67E22
DARK_ORANGE = 0xA84300
YELLOW = 0xFEE75C
TEAL = 0x1ABC9C
DARK_RED = 0x992D22
DARK_GRAY = 0x607D8B
LIGHT_GRAY = 0x979C9F
GREYPLE = 0x99AAB5
BLUE = 0x3498DB
PINK = 0xEB459E


def parse_duration(s: str | None) -> timedelta | None:
    if not s:
        return None
    match = _DURATION_RE.match(s.strip())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2).lower()
    if unit.startswith("s"):
        return timedelta(seconds=value)
    if unit.startswith("m"):
        return timedelta(minutes=value)
    if unit.startswith("h"):
        return timedelta(hours=value)
    return timedelta(days=value)


def format_duration(td: timedelta) -> str:
    total = int(td.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds and not days:
        parts.append(f"{seconds}s")
    return " ".join(parts) or "0s"


def success(msg: str) -> str:
    return f"✅ {msg}"


def error(msg: str) -> str:
    return f"❌ {msg}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_in(td: timedelta) -> str:
    """ISO 8601 timestamp td from now, as used by member timeouts."""
    return (utcnow() + td).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_now() -> str:
    return utcnow().isoformat()


def fmt_dt(value) -> str:
    """Format a datetime or ISO string as 'YYYY-MM-DD HH:MM UTC'."""
    if not value:
        return "Unknown"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def user_label(user) -> str:
    """Readable name for a fluxer User or GuildMember."""
    user = getattr(user, "user", user)
    return str(user)


def is_timed_out(member) -> bool:
    until = getattr(member, "communication_disabled_until", None)
    if not until:
        return False
    try:
        return datetime.fromisoformat(until.replace("Z", "+00:00")) > utcnow()
    except ValueError:
        return False


def embed_color_for(member_role_ids, roles: dict) -> int:
    """Colour of the highest role that has one, like a member list would show."""
    best, best_pos = 0, -1
    for rid in member_role_ids:
        r = roles.get(rid)
        if r and r.get("color") and int(r.get("position", 0)) > best_pos:
            best, best_pos = int(r["color"]), int(r.get("position", 0))
    return best or BLURPLE


async def auto_unmute(bot, mute_id: int, guild_id: int, user_id: int, role_id: int, delay: float):
    """Shared timed-mute expiry logic used by moderation.py and bot.py."""
    import db
    await asyncio.sleep(delay)
    with db.get_db() as conn:
        row = conn.execute("SELECT id FROM timed_mutes WHERE id = ?", (mute_id,)).fetchone()
        if not row:
            return
        conn.execute("DELETE FROM timed_mutes WHERE id = ?", (mute_id,))
    try:
        await bot.http.remove_guild_member_role(guild_id, user_id, role_id, reason="Mute expired")
    except fluxer.HTTPException:
        pass
    finally:
        bot.invalidate_member(guild_id, user_id)