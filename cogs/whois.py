from fluxer import Embed

import db
from framework import BlanketCog, MemberArg, command
from utils import embed_color_for, fmt_dt, user_label


class Whois(BlanketCog):

    @command("whois")
    async def whois(self, ctx, member: MemberArg = None):
        if member is None:
            member = await self.bot.member(ctx.guild_id, ctx.author.id)
        target = member.user
        gid = ctx.guild_id
        with db.get_db() as conn:
            warning_count = conn.execute(
                "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?", (gid, target.id)
            ).fetchone()[0]
            note_count = conn.execute(
                "SELECT COUNT(*) FROM notes WHERE guild_id = ? AND user_id = ?", (gid, target.id)
            ).fetchone()[0]
            recent_cases = conn.execute(
                "SELECT case_number, action, reason, created_at FROM mod_actions "
                "WHERE guild_id = ? AND target_id = ? ORDER BY created_at DESC LIMIT 5",
                (gid, target.id),
            ).fetchall()

        roles = await self.bot.roles(gid)
        embed = Embed(title=user_label(target), color=embed_color_for(member.roles, roles))
        embed.set_thumbnail(url=target.avatar_url or target.default_avatar_url)
        embed.add_field(name="ID", value=str(target.id), inline=True)
        embed.add_field(name="Joined", value=fmt_dt(member.joined_at), inline=True)
        embed.add_field(name="Created", value=fmt_dt(target.created_at), inline=True)

        role_mentions = [f"<@&{r}>" for r in member.roles if r in roles and r != gid]
        embed.add_field(name="Roles", value=" ".join(role_mentions) if role_mentions else "None", inline=False)
        embed.add_field(name="Warnings", value=str(warning_count), inline=True)
        embed.add_field(name="Notes", value=str(note_count), inline=True)

        if recent_cases:
            lines = [
                f"**#{c['case_number']}** {c['action']} \u2014 {c['reason'] or 'No reason'} ({c['created_at'][:10]})"
                for c in recent_cases
            ]
            embed.add_field(name="Recent Cases", value="\n".join(lines), inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Whois(bot))