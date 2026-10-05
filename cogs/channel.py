import fluxer
from fluxer import Permissions

import db
from cogs.mod_log import Target, record_action
from framework import BlanketCog, ChannelArg, command, is_text_channel


class Channel(BlanketCog):

    async def _target(self, ctx, channel):
        """Resolve the optional channel argument, defaulting to the current channel."""
        channels = await self.bot.guild_channels(ctx.guild_id)
        raw = channels.get(channel.id if channel else ctx.channel_id)
        return raw

    async def _lock(self, ctx, raw):
        if not raw or not is_text_channel(raw):
            return "Can only lock text channels."
        cid, everyone = int(raw["id"]), ctx.guild_id
        previous = await self.bot.get_perm_state(cid, everyone, Permissions.SEND_MESSAGES)
        db.save_permission_snapshot(ctx.guild_id, cid, "lock", previous)
        try:
            await self.bot.set_perm_state(cid, everyone, {Permissions.SEND_MESSAGES: False})
        except fluxer.Forbidden:
            return "I don't have permission to lock that channel."
        await record_action(self.bot, ctx.guild_id, "lock", ctx.author, Target("channel", cid, raw.get("name") or str(cid)), None)
        return f"🔒 Locked <#{cid}>."

    async def _unlock(self, ctx, raw):
        if not raw or not is_text_channel(raw):
            return "Can only unlock text channels."
        cid, everyone = int(raw["id"]), ctx.guild_id
        restore = db.pop_permission_snapshot(ctx.guild_id, cid, "lock")
        try:
            await self.bot.set_perm_state(cid, everyone, {Permissions.SEND_MESSAGES: restore})
        except fluxer.Forbidden:
            return "I don't have permission to unlock that channel."
        await record_action(self.bot, ctx.guild_id, "unlock", ctx.author, Target("channel", cid, raw.get("name") or str(cid)), None)
        return f"🔓 Unlocked <#{cid}>."

    @command("channel", level="mod")
    async def channel(self, ctx):
        await ctx.send("❌ Usage: `?channel lock|unlock|slowmode`")

    @command("channel lock", level="mod")
    async def channel_lock(self, ctx, channel: ChannelArg = None):
        await ctx.send(await self._lock(ctx, await self._target(ctx, channel)))

    @command("channel unlock", level="mod")
    async def channel_unlock(self, ctx, channel: ChannelArg = None):
        await ctx.send(await self._unlock(ctx, await self._target(ctx, channel)))

    @command("channel slowmode", level="mod")
    async def channel_slowmode(self, ctx, seconds: int, channel: ChannelArg = None):
        if not (0 <= seconds <= 21600):
            await ctx.send("Seconds must be between 0 and 21600.")
            return
        raw = await self._target(ctx, channel)
        if not raw or not is_text_channel(raw):
            await ctx.send("❌ Slowmode only applies to text channels.")
            return
        cid = int(raw["id"])
        await self.bot.http.modify_channel(cid, rate_limit_per_user=seconds)
        self.bot.invalidate_channels(ctx.guild_id)
        if seconds == 0:
            await ctx.send(f"Slowmode disabled in <#{cid}>.")
        else:
            await ctx.send(f"Slowmode set to **{seconds}s** in <#{cid}>.")


async def setup(bot):
    await bot.add_cog(Channel(bot))