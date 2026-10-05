from fluxer import Embed, snowflake_to_datetime

from framework import BlanketCog, ChannelArg, command
from utils import BLURPLE, fmt_dt


class Info(BlanketCog):

    @command("info")
    async def info(self, ctx):
        await self.info_server(ctx)

    @command("info server")
    async def info_server(self, ctx):
        gid = ctx.guild_id
        guild = ctx.guild
        roles = await self.bot.roles(gid)
        channels = await self.bot.guild_channels(gid)

        embed = Embed(title=guild.name if guild else str(gid), color=BLURPLE)
        if guild and guild.icon_url:
            embed.set_thumbnail(url=guild.icon_url)
        owner = guild.owner_id if guild and guild.owner_id else await self.bot.owner_id(gid)
        embed.add_field(name="Owner", value=f"<@{owner}>", inline=True)
        embed.add_field(name="Members", value=str(guild.member_count if guild else "Unknown"), inline=True)
        embed.add_field(name="Channels", value=str(len(channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(roles)), inline=True)
        embed.add_field(name="Created", value=fmt_dt(guild.created_at) if guild else "Unknown", inline=True)
        embed.set_footer(text=f"ID: {gid}")
        await ctx.send(embed=embed)

    @command("info channel")
    async def info_channel(self, ctx, channel: ChannelArg = None):
        channels = await self.bot.guild_channels(ctx.guild_id)
        raw = channels.get(channel.id if channel else ctx.channel_id)
        if raw is None:
            await ctx.send("❌ Channel not found.")
            return
        embed = Embed(title=f"#{raw.get('name')}", color=BLURPLE)
        embed.add_field(name="ID", value=str(raw["id"]), inline=True)
        parent = channels.get(int(raw["parent_id"])) if raw.get("parent_id") else None
        embed.add_field(name="Category", value=parent["name"] if parent else "None", inline=True)
        embed.add_field(name="Created", value=fmt_dt(snowflake_to_datetime(raw["id"])), inline=True)
        if raw.get("topic"):
            embed.add_field(name="Topic", value=raw["topic"], inline=False)
        if raw.get("rate_limit_per_user"):
            embed.add_field(name="Slowmode", value=f"{raw['rate_limit_per_user']}s", inline=True)
        embed.set_footer(text=f"ID: {raw['id']}")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Info(bot))