from fluxer import Embed

import db
from framework import BlanketCog, ChannelArg, UserError, command
from utils import BLURPLE


class Settings(BlanketCog):

    @command("settings", level="admin")
    async def settings(self, ctx):
        row = db.get_guild_settings(ctx.guild_id)
        if not row:
            await ctx.send("No settings configured yet. Use `?settings logchannel #channel` to get started.")
            return
        log_ch = f"<#{row['log_channel']}>" if row["log_channel"] else "Not set"
        automod = "Enabled" if row["automod_enabled"] else "Disabled"
        guild = ctx.guild
        embed = Embed(title=f"Settings \u2014 {guild.name if guild else ctx.guild_id}", color=BLURPLE)
        embed.add_field(name="Log channel", value=log_ch, inline=True)
        embed.add_field(name="Automod", value=automod, inline=True)
        await ctx.send(embed=embed)

    @command("settings logchannel", level="admin")
    async def settings_logchannel(self, ctx, channel: str = None):
        db.ensure_guild_settings(ctx.guild_id)
        if channel is None or channel.lower() == "off":
            with db.get_db() as conn:
                conn.execute("UPDATE guild_settings SET log_channel = NULL WHERE guild_id = ?", (ctx.guild_id,))
            await ctx.send("✅ Log channel cleared.")
            return
        try:
            target = await ctx.convert(ChannelArg, channel)
        except UserError:
            await ctx.send("❌ Usage: `?settings logchannel #channel` or `?settings logchannel off`")
            return
        if target.type not in (0, 5):
            await ctx.send("❌ The log channel must be a text channel.")
            return
        with db.get_db() as conn:
            conn.execute("UPDATE guild_settings SET log_channel = ? WHERE guild_id = ?", (target.id, ctx.guild_id))
        await ctx.send(f"✅ Log channel set to {target.mention}.")


async def setup(bot):
    await bot.add_cog(Settings(bot))