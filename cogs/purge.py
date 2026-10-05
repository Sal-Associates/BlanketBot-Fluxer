from datetime import timedelta

import fluxer

from cogs.mod_log import Target, record_action
from framework import BlanketCog, command, parse_user_id
from utils import INVITE_RE, LINK_RE, utcnow

MAX_PURGE = 100
MAX_AGE = timedelta(days=14)
FILTERS = frozenset({"user", "match", "not", "startswith", "endswith", "links",
                     "invites", "images", "mentions", "embeds", "bots", "humans", "text"})


def _too_old(msg) -> bool:
    return (utcnow() - msg.created_at) > MAX_AGE


def _filter_messages(candidates, filter_name, arg, count) -> list:
    if filter_name == "user":
        return [m for m in candidates if m.author.id == arg][:count]
    if filter_name == "match":
        return [m for m in candidates if arg and arg in m.content][:count]
    if filter_name == "not":
        return [m for m in candidates if arg and arg not in m.content][:count]
    if filter_name == "startswith":
        return [m for m in candidates if arg and m.content.startswith(arg)][:count]
    if filter_name == "endswith":
        return [m for m in candidates if arg and m.content.endswith(arg)][:count]
    if filter_name == "links":
        return [m for m in candidates if LINK_RE.search(m.content)][:count]
    if filter_name == "invites":
        return [m for m in candidates if INVITE_RE.search(m.content)][:count]
    if filter_name == "images":
        return [m for m in candidates if any(
            a.content_type and a.content_type.startswith("image/") for a in m.attachments
        )][:count]
    if filter_name == "mentions":
        return [m for m in candidates if m.mentions][:count]
    if filter_name == "embeds":
        return [m for m in candidates if m.embeds][:count]
    if filter_name == "bots":
        return [m for m in candidates if m.author.bot][:count]
    if filter_name == "humans":
        return [m for m in candidates if not m.author.bot][:count]
    if filter_name == "text":
        return [m for m in candidates if m.content and not m.attachments and not m.embeds][:count]
    return candidates[:count]


async def _fetch_history(http, channel_id, limit=200) -> list:
    """Newest first, in pages of 100."""
    messages, before = [], None
    while len(messages) < limit:
        page = await http.get_messages(channel_id, limit=min(100, limit - len(messages)), before=before)
        if not page:
            break
        batch = [fluxer.Message.from_data(d, http) for d in page]
        messages.extend(batch)
        before = min(m.id for m in batch)
        if len(page) < 100:
            break
    messages.sort(key=lambda m: m.id, reverse=True)
    return messages


class Purge(BlanketCog):

    def _parse_args(self, args: str):
        """Returns (filter_name, arg, count, error_str)."""
        parts = args.split()
        if not parts:
            return "any", None, MAX_PURGE, None

        first = parts[0].lower()
        if first.isdigit():
            return "any", None, min(int(first), MAX_PURGE), None
        if first not in FILTERS and first != "any":
            return None, None, 0, f"Unknown filter `{first}`. Valid filters: {', '.join(sorted(FILTERS))}"

        rest = parts[1:]
        count = min(int(rest[-1]), MAX_PURGE) if rest and rest[-1].isdigit() else MAX_PURGE
        arg_parts = rest[:-1] if rest and rest[-1].isdigit() else rest

        if first == "user":
            user_id = parse_user_id(arg_parts[0] if arg_parts else None)
            if not user_id:
                return None, None, 0, "User not found. Use a mention or a user ID."
            return first, user_id, count, None
        return first, " ".join(arg_parts), count, None

    @command("purge", level="mod")
    async def purge(self, ctx, *, args: str = ""):
        filter_name, arg, count, err = self._parse_args(args)
        if err:
            await ctx.send(f"❌ {err}")
            return

        fetched = await _fetch_history(self.bot.http, ctx.channel_id)
        candidates = [m for m in fetched if m.id != ctx.message.id and not _too_old(m)]
        to_delete = _filter_messages(candidates, filter_name, arg, count)

        if len(to_delete) == 1:
            await to_delete[0].delete()
        elif to_delete:
            await self.bot.http.delete_messages(ctx.channel_id, [m.id for m in to_delete])

        if to_delete:
            await record_action(
                self.bot, ctx.guild_id, "purge", ctx.author,
                Target("channel", ctx.channel_id, str(ctx.channel_id)),
                f"Purged {len(to_delete)} messages (filter: {filter_name})",
            )
        await ctx.send(f"✅ Deleted **{len(to_delete)}** message(s).", delete_after=5)


async def setup(bot):
    await bot.add_cog(Purge(bot))