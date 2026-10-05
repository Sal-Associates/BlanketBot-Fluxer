import fluxer
from fluxer import Embed, Permissions

import db
from cogs.mod_log import Target, record_action
from framework import BlanketCog, ChannelArg, command
from utils import BLURPLE


class Lockdown(BlanketCog):

    def _channel_ids(self, guild_id: int) -> list[int]:
        with db.get_db() as conn:
            rows = conn.execute("SELECT channel_id FROM lockdown_channels WHERE guild_id = ?", (guild_id,)).fetchall()
        return [r["channel_id"] for r in rows]

    async def _guild_target(self, ctx) -> Target:
        guild = ctx.guild
        return Target("guild", ctx.guild_id, guild.name if guild else str(ctx.guild_id))

    @command("lockdown", level="admin")
    async def lockdown(self, ctx):
        await ctx.send("❌ Usage: `?lockdown enable|disable|status|channel`")

    @command("lockdown enable", level="admin")
    async def lockdown_enable(self, ctx, *, reason: str = ""):
        ids = self._channel_ids(ctx.guild_id)
        if not ids:
            await ctx.send("❌ No lockdown channels configured. Use `?lockdown channel add #channel` first.")
            return
        bot_member = await self.bot.me(ctx.guild_id)
        if not await self.bot.perms(ctx.guild_id, bot_member) & Permissions.MANAGE_CHANNELS:
            await ctx.send("❌ I need **Manage Channels** permission to lock channels.")
            return

        existing = await self.bot.guild_channels(ctx.guild_id)
        locked, failed = [], []
        for cid in ids:
            if cid not in existing:
                continue
            previous = await self.bot.get_perm_state(cid, ctx.guild_id, Permissions.SEND_MESSAGES)
            db.save_permission_snapshot(ctx.guild_id, cid, "lockdown", previous)
            try:
                await self.bot.set_perm_state(cid, ctx.guild_id, {Permissions.SEND_MESSAGES: False})
                locked.append(f"<#{cid}>")
            except fluxer.HTTPException:
                failed.append(f"<#{cid}>")

        await record_action(self.bot, ctx.guild_id, "lockdown_enable", ctx.author, await self._guild_target(ctx), reason or None)
        msg = f"🔒 Server locked. Channels: {', '.join(locked) or 'none'}"
        if failed:
            msg += f"\n⚠️ Failed: {', '.join(failed)}"
        await ctx.send(msg)

    @command("lockdown disable", level="admin")
    async def lockdown_disable(self, ctx, *, reason: str = ""):
        ids = self._channel_ids(ctx.guild_id)
        if not ids:
            await ctx.send("❌ No lockdown channels configured.")
            return

        existing = await self.bot.guild_channels(ctx.guild_id)
        unlocked, failed = [], []
        for cid in ids:
            if cid not in existing:
                continue
            restore = db.pop_permission_snapshot(ctx.guild_id, cid, "lockdown")
            try:
                await self.bot.set_perm_state(cid, ctx.guild_id, {Permissions.SEND_MESSAGES: restore})
                unlocked.append(f"<#{cid}>")
            except fluxer.HTTPException:
                failed.append(f"<#{cid}>")

        await record_action(self.bot, ctx.guild_id, "lockdown_disable", ctx.author, await self._guild_target(ctx), reason or None)
        msg = f"🔓 Server unlocked. Channels: {', '.join(unlocked) or 'none'}"
        if failed:
            msg += f"\n⚠️ Failed: {', '.join(failed)}"
        await ctx.send(msg)

    @command("lockdown status", level="admin")
    async def lockdown_status(self, ctx):
        ids = self._channel_ids(ctx.guild_id)
        if not ids:
            await ctx.send("No lockdown channels configured. Use `?lockdown channel add #channel`.")
            return
        existing = await self.bot.guild_channels(ctx.guild_id)
        lines = []
        for cid in ids:
            if cid not in existing:
                lines.append(f"~~{cid}~~ (deleted)")
                continue
            state = await self.bot.get_perm_state(cid, ctx.guild_id, Permissions.SEND_MESSAGES)
            lines.append(f"{'🔒 Locked' if state is False else '🔓 Open'} <#{cid}>")
        await ctx.send(embed=Embed(title="Lockdown Status", description="\n".join(lines), color=BLURPLE))

    @command("lockdown channel", level="admin")
    async def lockdown_channel(self, ctx):
        await ctx.send("❌ Usage: `?lockdown channel add|remove|list [#channel]`")

    @command("lockdown channel add", level="admin")
    async def lockdown_channel_add(self, ctx, channel: ChannelArg):
        with db.get_db() as conn:
            conn.execute("INSERT OR IGNORE INTO lockdown_channels (guild_id, channel_id) VALUES (?, ?)", (ctx.guild_id, channel.id))
        await ctx.send(f"✅ {channel.mention} added to lockdown channels.")

    @command("lockdown channel remove", level="admin", aliases=("del",))
    async def lockdown_channel_remove(self, ctx, channel: ChannelArg):
        with db.get_db() as conn:
            conn.execute("DELETE FROM lockdown_channels WHERE guild_id = ? AND channel_id = ?", (ctx.guild_id, channel.id))
        await ctx.send(f"✅ {channel.mention} removed from lockdown channels.")

    @command("lockdown channel list", level="admin")
    async def lockdown_channel_list(self, ctx):
        ids = self._channel_ids(ctx.guild_id)
        if not ids:
            await ctx.send("No lockdown channels configured.")
            return
        await ctx.send("Lockdown channels: " + ", ".join(f"<#{cid}>" for cid in ids))


async def setup(bot):
    await bot.add_cog(Lockdown(bot))