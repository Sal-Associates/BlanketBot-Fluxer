import asyncio
import time
from datetime import timedelta

import fluxer
from fluxer import Embed

import db
from cogs.mod_log import record_action, user_target
from framework import BlanketCog, IdArg, MemberArg, UserArg, command
from utils import (
    ORANGE, format_duration, is_timed_out, iso_in, parse_duration, user_label,
    auto_unmute,
)


class Moderation(BlanketCog):

    async def _mute_role_id(self, guild_id: int) -> int | None:
        settings = db.get_guild_settings(guild_id)
        if not settings or not settings["mute_role_id"]:
            return None
        if settings["mute_role_id"] not in await self.bot.roles(guild_id):
            return None
        return settings["mute_role_id"]

    async def _outranks(self, ctx, target) -> bool:
        actor = await self.bot.member(ctx.guild_id, ctx.author.id)
        return await self.bot.can_act_on(ctx.guild_id, actor, target)

    async def _kick(self, ctx, member, reason):
        if not await self._outranks(ctx, member):
            return "You can't kick someone with a higher or equal role."
        try:
            await self.bot.http.kick_guild_member(ctx.guild_id, member.user.id, reason=reason)
        except fluxer.Forbidden:
            return "I don't have permission to kick that member."
        await record_action(self.bot, ctx.guild_id, "kick", ctx.author, user_target(member), reason)
        return f"Kicked **{user_label(member)}**." + (f" Reason: {reason}" if reason else "")

    async def _ban(self, ctx, user, reason, *, member=None):
        if member is not None and not await self._outranks(ctx, member):
            return "You can't ban someone with a higher or equal role."
        guild = ctx.guild
        try:
            await user.send(f"You have been banned from **{guild.name if guild else 'the server'}**. Reason: {reason or 'No reason provided'}")
        except Exception:
            pass
        try:
            await self.bot.http.ban_guild_member(ctx.guild_id, user.id, delete_message_seconds=43200, reason=reason)
        except fluxer.Forbidden:
            return "I don't have permission to ban that user."
        except fluxer.HTTPException as e:
            return f"Ban failed: {e}"
        await record_action(self.bot, ctx.guild_id, "ban", ctx.author, user_target(user), reason)
        return f"Banned **{user_label(user)}**." + (f" Reason: {reason}" if reason else "")

    async def _mute(self, ctx, member, duration_str, reason):
        gid, uid = ctx.guild_id, member.user.id
        mute_role = await self._mute_role_id(gid)
        td = parse_duration(duration_str) if duration_str else None
        name = user_label(member)

        if mute_role:
            roles = await self.bot.roles(gid)
            bot_member = await self.bot.me(gid)
            if int(roles[mute_role]["position"]) >= await self.bot.top_position(gid, bot_member):
                return "The mute role is above my highest role. Move it below my role in the hierarchy."
            try:
                await self.bot.http.add_guild_member_role(gid, uid, mute_role, reason=reason)
            except fluxer.Forbidden:
                return "I don't have permission to assign the mute role."
            self.bot.invalidate_member(gid, uid)

            label = format_duration(td) if td else None
            if td:
                expires_at = int(time.time() + td.total_seconds())
                with db.get_db() as conn:
                    conn.execute("DELETE FROM timed_mutes WHERE guild_id = ? AND user_id = ?", (gid, uid))
                    mute_id = conn.execute(
                        "INSERT INTO timed_mutes (guild_id, user_id, role_id, expires_at) VALUES (?, ?, ?, ?)",
                        (gid, uid, mute_role, expires_at),
                    ).lastrowid
                asyncio.create_task(auto_unmute(self.bot, mute_id, gid, uid, mute_role, td.total_seconds()))

            await record_action(self.bot, gid, "mute", ctx.author, user_target(member), reason, label)
            msg = f"Muted **{name}**" + (f" for {label}" if label else " permanently") + "."
            return msg + (f" Reason: {reason}" if reason else "")

        if not td:
            return "No mute role configured. Run `?muterole create`, or provide a duration to use a temporary timeout."
        if td > timedelta(days=28):
            return "Timeouts can't exceed 28 days."
        try:
            await self.bot.http.timeout_guild_member(gid, uid, until=iso_in(td), reason=reason)
        except fluxer.Forbidden:
            return "I don't have permission to timeout that member."
        self.bot.invalidate_member(gid, uid)
        label = format_duration(td)
        await record_action(self.bot, gid, "mute", ctx.author, user_target(member), reason, label)
        return f"Timed out **{name}** for {label} (no mute role set)." + (f" Reason: {reason}" if reason else "")

    async def _unmute(self, ctx, member):
        gid, uid = ctx.guild_id, member.user.id
        mute_role = await self._mute_role_id(gid)
        actions = []
        if mute_role and mute_role in member.roles:
            try:
                await self.bot.http.remove_guild_member_role(gid, uid, mute_role, reason="Unmuted")
                actions.append("role removed")
            except fluxer.Forbidden:
                return "I don't have permission to remove the mute role."
            with db.get_db() as conn:
                conn.execute("DELETE FROM timed_mutes WHERE guild_id = ? AND user_id = ?", (gid, uid))
        if is_timed_out(member):
            try:
                await self.bot.http.timeout_guild_member(gid, uid, until=None, reason="Unmuted")
                actions.append("timeout cleared")
            except fluxer.Forbidden:
                pass
        self.bot.invalidate_member(gid, uid)
        if not actions:
            return f"**{user_label(member)}** doesn't appear to be muted."
        await record_action(self.bot, gid, "unmute", ctx.author, user_target(member), None)
        return f"Unmuted **{user_label(member)}** ({', '.join(actions)})."

    @command("kick", level="mod")
    async def kick(self, ctx, member: MemberArg, *, reason: str = None):
        await ctx.send(await self._kick(ctx, member, reason))

    @command("ban", level="mod")
    async def ban(self, ctx, target: str, *, reason: str = None):
        from framework import parse_user_id
        uid = parse_user_id(target)
        if uid is None:
            await ctx.send("❌ User not found. Use a mention or a user ID.")
            return
        member = await self.bot.member(ctx.guild_id, uid)
        if member is not None:
            user = member.user
        else:
            try:
                user = await self.bot.fetch_user(str(uid))
            except fluxer.NotFound:
                await ctx.send("❌ User not found.")
                return
        await ctx.send(await self._ban(ctx, user, reason, member=member))

    @command("unban", level="mod")
    async def unban(self, ctx, user_id: str, *, reason: str = None):
        try:
            user = await self.bot.fetch_user(str(int(user_id)))
        except (ValueError, fluxer.NotFound):
            await ctx.send("❌ Couldn't find a user with that ID.")
            return
        try:
            await self.bot.http.unban_guild_member(ctx.guild_id, user.id, reason=reason)
        except fluxer.NotFound:
            await ctx.send("❌ That user isn't banned.")
            return
        except fluxer.Forbidden:
            await ctx.send("❌ I don't have permission to unban users.")
            return
        await record_action(self.bot, ctx.guild_id, "unban", ctx.author, user_target(user), reason)
        await ctx.send(f"Unbanned **{user_label(user)}**.")

    @command("mute", level="mod")
    async def mute(self, ctx, member: MemberArg, *, args: str = ""):
        parts = args.split(None, 1)
        if parts and parse_duration(parts[0]) is not None:
            duration, reason = parts[0], parts[1] if len(parts) > 1 else None
        else:
            duration, reason = None, args or None
        await ctx.send(await self._mute(ctx, member, duration, reason))

    @command("unmute", level="mod")
    async def unmute(self, ctx, member: MemberArg):
        await ctx.send(await self._unmute(ctx, member))

    @command("softban", level="mod")
    async def softban(self, ctx, member: MemberArg, *, reason: str = None):
        if not await self._outranks(ctx, member):
            await ctx.send("❌ You can't softban someone with a higher or equal role.")
            return
        gid, uid = ctx.guild_id, member.user.id
        try:
            await self.bot.http.ban_guild_member(gid, uid, delete_message_days=7, reason=f"Softban: {reason}")
            await self.bot.http.unban_guild_member(gid, uid, reason="Softban complete")
        except fluxer.Forbidden:
            await ctx.send("❌ I don't have permission to softban that member.")
            return
        await record_action(self.bot, gid, "softban", ctx.author, user_target(member), reason)
        await ctx.send(f"Softbanned **{user_label(member)}** (7 days of messages deleted)." + (f" Reason: {reason}" if reason else ""))

    @command("warn", level="mod")
    async def warn(self, ctx, member: MemberArg, *, reason: str):
        reason = reason[:1000]
        with db.get_db() as conn:
            conn.execute(
                "INSERT INTO warnings (guild_id, user_id, reason, moderator_id) VALUES (?, ?, ?, ?)",
                (ctx.guild_id, member.user.id, reason, ctx.author.id),
            )
        await record_action(self.bot, ctx.guild_id, "warn", ctx.author, user_target(member), reason)
        await ctx.send(f"Warned **{user_label(member)}**: {reason}")

    @command("warndel", level="mod")
    async def warndel(self, ctx, warning_id: IdArg):
        with db.get_db() as conn:
            row = conn.execute("SELECT id FROM warnings WHERE id = ? AND guild_id = ?", (warning_id, ctx.guild_id)).fetchone()
            if not row:
                await ctx.send("Warning not found.")
                return
            conn.execute("DELETE FROM warnings WHERE id = ?", (warning_id,))
        await ctx.send(f"Deleted warning `#{warning_id}`.")

    @command("warnings", level="mod")
    async def warnings(self, ctx, user: UserArg):
        with db.get_db() as conn:
            rows = conn.execute(
                "SELECT id, reason, moderator_id, created_at FROM warnings "
                "WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
                (ctx.guild_id, user.id),
            ).fetchall()
        if not rows:
            await ctx.send(f"**{user_label(user)}** has no warnings.")
            return
        lines = [f"`#{r['id']}` {r['reason']} \u2014 <@{r['moderator_id']}> on {r['created_at'][:10]}" for r in rows]
        await ctx.send(embed=Embed(title=f"Warnings for {user_label(user)}", description="\n".join(lines)[:4000], color=ORANGE))

    @command("clearwarnings", level="admin")
    async def clearwarnings(self, ctx, user: UserArg):
        with db.get_db() as conn:
            conn.execute("DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (ctx.guild_id, user.id))
        await ctx.send(f"Cleared all warnings for **{user_label(user)}**.")


async def setup(bot):
    await bot.add_cog(Moderation(bot))