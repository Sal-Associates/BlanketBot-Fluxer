import fluxer
from fluxer import Permissions

import db
from framework import BlanketCog, RoleArg, command, is_text_channel


class MuteRole(BlanketCog):

    async def _get_role(self, guild_id: int) -> dict | None:
        settings = db.get_guild_settings(guild_id)
        if not settings or not settings["mute_role_id"]:
            return None
        return (await self.bot.roles(guild_id)).get(settings["mute_role_id"])

    def _save(self, guild_id: int, role_id: int | None):
        db.ensure_guild_settings(guild_id)
        with db.get_db() as conn:
            conn.execute("UPDATE guild_settings SET mute_role_id = ? WHERE guild_id = ?", (role_id, guild_id))

    @command("muterole", level="admin")
    async def muterole(self, ctx):
        role = await self._get_role(ctx.guild_id)
        if role:
            await ctx.send(f"Mute role: **{role['name']}** (`{role['id']}`)\nUse `?muterole set @role`, `?muterole create`, or `?muterole off`.")
        else:
            await ctx.send("No mute role configured. Use `?muterole create` to create one, or `?muterole set @role` to assign an existing role.")

    @command("muterole set", level="admin")
    async def muterole_set(self, ctx, role: RoleArg):
        bot_member = await self.bot.me(ctx.guild_id)
        if role.position >= await self.bot.top_position(ctx.guild_id, bot_member):
            await ctx.send("❌ That role is at or above my highest role. Move it below my role in the hierarchy.")
            return
        self._save(ctx.guild_id, role.id)
        await ctx.send(f"✅ Mute role set to **{role.name}**.")

    @command("muterole create", level="admin")
    async def muterole_create(self, ctx):
        gid = ctx.guild_id
        for rid, r in (await self.bot.roles(gid)).items():
            if r["name"] == "Muted":
                self._save(gid, rid)
                await ctx.send("✅ Found existing **Muted** role and set it as the mute role.")
                return

        msg = await ctx.send("⏳ Creating **Muted** role and applying channel permissions...")
        try:
            raw = await self.bot.http.create_guild_role(gid, name="Muted")
        except fluxer.Forbidden:
            await msg.edit(content="❌ I don't have permission to create roles.")
            return
        role_id = int(raw["id"])
        self.bot.invalidate_roles(gid)

        text_channels = [c for c in (await self.bot.guild_channels(gid)).values() if is_text_channel(c)]
        failed = []
        for channel in text_channels:
            try:
                await self.bot.set_perm_state(
                    int(channel["id"]), role_id,
                    {Permissions.SEND_MESSAGES: False, Permissions.ADD_REACTIONS: False},
                )
            except fluxer.Forbidden:
                failed.append(channel.get("name") or channel["id"])

        self._save(gid, role_id)
        reply = f"✅ Created **Muted** role and applied permissions to {len(text_channels) - len(failed)} channel(s)."
        if failed:
            reply += f"\n⚠️ Couldn't set permissions in: {', '.join(failed)}"
        await msg.edit(content=reply)

    @command("muterole off", level="admin")
    async def muterole_off(self, ctx):
        self._save(ctx.guild_id, None)
        await ctx.send("✅ Mute role cleared. Mutes will fall back to timeout.")


async def setup(bot):
    await bot.add_cog(MuteRole(bot))