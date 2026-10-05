from fluxer import Embed

import db
from framework import BlanketCog, RoleArg, command
from utils import BLURPLE


class Staff(BlanketCog):

    async def _list(self, ctx, role_type: str, label: str):
        with db.get_db() as conn:
            rows = conn.execute(
                "SELECT role_id FROM staff_roles WHERE guild_id = ? AND role_type = ?",
                (ctx.guild_id, role_type),
            ).fetchall()
        if not rows:
            await ctx.send(f"No {label} roles configured.")
            return
        roles = await self.bot.roles(ctx.guild_id)
        lines = [f"\u2022 <@&{r['role_id']}>" if r["role_id"] in roles else "\u2022 ~~deleted role~~" for r in rows]
        await ctx.send(embed=Embed(title=f"{label.capitalize()} Roles", description="\n".join(lines), color=BLURPLE))

    async def _add(self, ctx, role, role_type: str, label: str):
        with db.get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO staff_roles (guild_id, role_id, role_type) VALUES (?, ?, ?)",
                (ctx.guild_id, role.id, role_type),
            )
        await ctx.send(f"✅ **{role.name}** is now a {label} role.")

    async def _del(self, ctx, role, role_type: str, label: str):
        with db.get_db() as conn:
            conn.execute(
                "DELETE FROM staff_roles WHERE guild_id = ? AND role_id = ? AND role_type = ?",
                (ctx.guild_id, role.id, role_type),
            )
        await ctx.send(f"✅ **{role.name}** removed from {label} roles.")

    @command("staff mod add", level="admin")
    async def mod_add(self, ctx, role: RoleArg):
        await self._add(ctx, role, "mod", "moderator")

    @command("staff mod del", level="admin", aliases=("remove",))
    async def mod_del(self, ctx, role: RoleArg):
        await self._del(ctx, role, "mod", "moderator")

    @command("staff mod list", level="admin")
    async def mod_list(self, ctx):
        await self._list(ctx, "mod", "moderator")

    @command("staff admin add", level="admin")
    async def admin_add(self, ctx, role: RoleArg):
        await self._add(ctx, role, "admin", "admin")

    @command("staff admin del", level="admin", aliases=("remove",))
    async def admin_del(self, ctx, role: RoleArg):
        await self._del(ctx, role, "admin", "admin")

    @command("staff admin list", level="admin")
    async def admin_list(self, ctx):
        await self._list(ctx, "admin", "admin")


async def setup(bot):
    await bot.add_cog(Staff(bot))