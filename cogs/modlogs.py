from datetime import datetime

from fluxer import Embed

import db
from framework import BlanketCog, UserArg, command
from utils import BLURPLE, user_label

CASES_PER_PAGE = 5


def _mod_str(row) -> str:
    if row["moderator_id"]:
        return f"<@{row['moderator_id']}>"
    return row["moderator_display"] or "Unknown"


def build_modlogs_pages(user, rows) -> list[Embed] | str:
    name = user_label(user)
    if not rows:
        return f"No recorded mod actions for **{name}**."
    chunks = [rows[i:i + CASES_PER_PAGE] for i in range(0, len(rows), CASES_PER_PAGE)]
    pages = []
    for page_num, chunk in enumerate(chunks, 1):
        lines = []
        for row in chunk:
            try:
                date_str = datetime.fromisoformat(row["created_at"]).strftime("%b %d %Y %H:%M:%S")
            except (ValueError, TypeError):
                date_str = str(row["created_at"])
            case_label = f"Case {row['case_number']}" if row["case_number"] else "Case -"
            reason = row["reason"] or "No reason provided"
            duration_str = f" \u00b7 {row['duration']}" if row["duration"] else ""
            lines.append(
                f"**{case_label}**\n"
                f"Type: {row['action'].capitalize()}\n"
                f"User: {name} ({user.id})\n"
                f"Moderator: {_mod_str(row)}\n"
                f"Reason: {reason}{duration_str} \u2014 {date_str}"
            )
        pages.append(Embed(
            title=f"Modlogs for {name} (Page {page_num} of {len(chunks)})",
            description="\n\n".join(lines),
            color=BLURPLE,
        ))
    return pages


def build_modstats_embed(label: str, target_id: int, avatar_url: str | None, rows) -> Embed | str:
    if not rows:
        return f"No recorded mod actions for **{label}**."
    data = {row["action"]: {"d7": row["d7"], "d30": row["d30"], "total": row["total"]} for row in rows}
    embed = Embed(description="Moderation Statistics", color=BLURPLE)
    embed.set_author(name=label, icon_url=avatar_url)
    for action_key, name in [("mute", "Mutes"), ("ban", "Bans"), ("kick", "Kicks"), ("warn", "Warns")]:
        s = data.get(action_key, {"d7": 0, "d30": 0, "total": 0})
        embed.add_field(name=f"{name} (7d)", value=str(s["d7"]), inline=True)
        embed.add_field(name=f"{name} (30d)", value=str(s["d30"]), inline=True)
        embed.add_field(name=f"{name} (all)", value=str(s["total"]), inline=True)
    embed.add_field(name="Total (7d)", value=str(sum(d["d7"] for d in data.values())), inline=True)
    embed.add_field(name="Total (30d)", value=str(sum(d["d30"] for d in data.values())), inline=True)
    embed.add_field(name="Total (all)", value=str(sum(d["total"] for d in data.values())), inline=True)
    embed.set_footer(text=f"ID: {target_id}")
    return embed


class ModLogs(BlanketCog):

    def _fetch_modlogs(self, guild_id, user_id):
        with db.get_db() as conn:
            return conn.execute(
                "SELECT case_number, action, moderator_id, moderator_display, reason, duration, created_at "
                "FROM mod_actions WHERE guild_id = ? AND target_id = ? ORDER BY created_at DESC",
                (guild_id, user_id),
            ).fetchall()

    def _fetch_modstats(self, guild_id, moderator_id=None):
        where, params = "guild_id = ?", [guild_id]
        if moderator_id:
            where += " AND moderator_id = ?"
            params.append(moderator_id)
        with db.get_db() as conn:
            return conn.execute(f"""
                SELECT action,
                    SUM(CASE WHEN created_at >= datetime('now', '-7 days')  THEN 1 ELSE 0 END) as d7,
                    SUM(CASE WHEN created_at >= datetime('now', '-30 days') THEN 1 ELSE 0 END) as d30,
                    COUNT(*) as total
                FROM mod_actions WHERE {where}
                GROUP BY action
            """, params).fetchall()

    def _fetch_case(self, guild_id, case_number):
        with db.get_db() as conn:
            return conn.execute(
                "SELECT case_number, action, target_id, moderator_id, moderator_display, reason, duration, created_at "
                "FROM mod_actions WHERE guild_id = ? AND case_number = ?",
                (guild_id, case_number),
            ).fetchone()

    @command("modlogs", level="mod")
    async def modlogs(self, ctx, user: UserArg, page: int = 1):
        result = build_modlogs_pages(user, self._fetch_modlogs(ctx.guild_id, user.id))
        if isinstance(result, str):
            await ctx.send(result)
            return
        page = max(1, min(page, len(result)))
        embed = result[page - 1]
        if len(result) > 1:
            embed.set_footer(text=f"Use ?modlogs <user> <page> to see other pages ({len(result)} total)")
        await ctx.send(embed=embed)

    @command("modstats", level="mod")
    async def modstats(self, ctx, moderator: UserArg = None):
        rows = self._fetch_modstats(ctx.guild_id, moderator.id if moderator else None)
        if moderator:
            result = build_modstats_embed(user_label(moderator), moderator.id, moderator.avatar_url, rows)
        else:
            guild = ctx.guild
            result = build_modstats_embed(guild.name if guild else "Server", ctx.guild_id, guild.icon_url if guild else None, rows)
        await ctx.send(result) if isinstance(result, str) else await ctx.send(embed=result)

    @command("case", level="mod")
    async def case(self, ctx, number: int):
        row = self._fetch_case(ctx.guild_id, number)
        if not row:
            await ctx.send(f"Case #{number} not found.")
            return
        embed = Embed(title=f"Case #{row['case_number']} \u2014 {row['action'].capitalize()}", color=BLURPLE)
        embed.add_field(name="User", value=f"<@{row['target_id']}> ({row['target_id']})", inline=True)
        embed.add_field(name="Moderator", value=_mod_str(row), inline=True)
        if row["duration"]:
            embed.add_field(name="Duration", value=row["duration"], inline=True)
        embed.add_field(name="Reason", value=row["reason"] or "No reason provided", inline=False)
        embed.add_field(name="Date", value=str(row["created_at"])[:10], inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ModLogs(bot))