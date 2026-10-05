from fluxer import Embed

import db
from framework import BlanketCog, IdArg, UserArg, command
from utils import PINK, user_label


class Notes(BlanketCog):

    @command("note add", level="mod")
    async def note_add(self, ctx, user: UserArg, *, content: str):
        with db.get_db() as conn:
            note_id = conn.execute(
                "INSERT INTO notes (guild_id, user_id, author_id, content) VALUES (?, ?, ?, ?)",
                (ctx.guild_id, user.id, ctx.author.id, content),
            ).lastrowid
        await ctx.send(f"Added note `#{note_id}` for **{user_label(user)}**.")

    @command("note list", level="mod")
    async def note_list(self, ctx, user: UserArg):
        with db.get_db() as conn:
            rows = conn.execute(
                "SELECT id, author_id, content, created_at FROM notes "
                "WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
                (ctx.guild_id, user.id),
            ).fetchall()
        if not rows:
            await ctx.send(f"No notes for **{user_label(user)}**.")
            return
        lines = [f"`#{r['id']}` {r['content']} \u2014 <@{r['author_id']}> on {r['created_at'][:10]}" for r in rows]
        await ctx.send(embed=Embed(title=f"Notes for {user_label(user)}", description="\n".join(lines)[:4000], color=PINK))

    @command("note edit", level="mod")
    async def note_edit(self, ctx, note_id: IdArg, *, content: str):
        with db.get_db() as conn:
            row = conn.execute("SELECT id FROM notes WHERE id = ? AND guild_id = ?", (note_id, ctx.guild_id)).fetchone()
            if not row:
                await ctx.send("Note not found.")
                return
            conn.execute("UPDATE notes SET content = ? WHERE id = ?", (content, note_id))
        await ctx.send(f"Updated note `#{note_id}`.")

    @command("note del", level="mod")
    async def note_del(self, ctx, note_id: IdArg):
        with db.get_db() as conn:
            row = conn.execute("SELECT id FROM notes WHERE id = ? AND guild_id = ?", (note_id, ctx.guild_id)).fetchone()
            if not row:
                await ctx.send("Note not found.")
                return
            conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        await ctx.send(f"Deleted note `#{note_id}`.")


async def setup(bot):
    await bot.add_cog(Notes(bot))