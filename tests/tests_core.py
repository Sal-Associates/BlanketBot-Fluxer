"""Tests for pure logic and database functions."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fluxer
from fluxer import Permissions

GUILD = 1000
CHAN = 2000
LOG_CHAN = 2001
OWNER, MOD, USER, TARGET, BOT_ID = 1, 2, 3, 4, 99
R_EVERYONE, R_ADMIN, R_MOD, R_TOP = GUILD, 501, 502, 503

ROLES = [
    {"id": str(R_EVERYONE), "name": "@everyone", "permissions": str(int(Permissions.SEND_MESSAGES)), "position": 0, "color": 0},
    {"id": str(R_ADMIN), "name": "Admin", "permissions": str(int(Permissions.ADMINISTRATOR)), "position": 5, "color": 0},
    {"id": str(R_MOD), "name": "Mod", "permissions": str(int(Permissions.KICK_MEMBERS | Permissions.MANAGE_MESSAGES)), "position": 3, "color": 0},
    {"id": str(R_TOP), "name": "BotRole", "permissions": str(int(Permissions.MANAGE_ROLES)), "position": 10, "color": 0},
]
MEMBER_ROLES = {OWNER: [], MOD: [R_MOD], USER: [], TARGET: [R_MOD], BOT_ID: [R_TOP]}


def user_dict(uid):
    return {"id": str(uid), "username": f"user{uid}", "bot": uid == BOT_ID}


class FakeHTTP:
    def __init__(self):
        self.sent = []
        self.calls = []
        self.overwrites = {}
        self.next_id = 9000

    def _rec(self, name, *a, **kw):
        self.calls.append((name, a, kw))

    async def send_message(self, channel_id, **kw):
        self.sent.append((int(channel_id), kw))
        self.next_id += 1
        return {"id": str(self.next_id), "channel_id": str(channel_id), "content": kw.get("content") or "",
                "author": user_dict(BOT_ID), "timestamp": "2026-01-01T00:00:00+00:00"}

    async def get_guild_roles(self, gid):
        return ROLES

    async def get_guild(self, gid):
        return {"id": str(GUILD), "name": "Test", "owner_id": str(OWNER)}

    async def get_guild_member(self, gid, uid):
        uid = int(uid)
        if uid not in MEMBER_ROLES:
            raise fluxer.NotFound(404, "unknown member") if False else _not_found()
        return {"user": user_dict(uid), "roles": [str(r) for r in MEMBER_ROLES[uid]], "joined_at": "2025-01-01T00:00:00+00:00"}

    async def get_user(self, uid):
        return user_dict(int(uid))

    async def get_guild_channels(self, gid):
        return [{"id": str(CHAN), "type": 0, "name": "general"}, {"id": str(LOG_CHAN), "type": 0, "name": "log"}]

    async def get_channel(self, cid):
        cid = int(cid)
        return {"id": str(cid), "type": 0, "guild_id": str(GUILD),
                "permission_overwrites": self.overwrites.get(cid, [])}

    async def edit_channel_permissions(self, cid, target, *, allow=None, deny=None, type=0, **kw):
        self._rec("edit_channel_permissions", cid, target, allow=allow, deny=deny)
        self.overwrites[int(cid)] = [{"id": str(target), "type": 0, "allow": str(allow), "deny": str(deny)}]

    async def edit_message(self, *a, **kw):
        self._rec("edit_message", *a, **kw)
        return {"id": "1", "channel_id": str(CHAN), "content": kw.get("content", ""), "author": user_dict(BOT_ID),
                "timestamp": "2026-01-01T00:00:00+00:00"}

    def __getattr__(self, name):
        async def call(*a, **kw):
            self._rec(name, *a, **kw)
            return {}
        return call


def _not_found():
    err = fluxer.NotFound.__new__(fluxer.NotFound)
    Exception.__init__(err, "not found")
    return err


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    import importlib
    import db
    importlib.reload(db)
    import bot as botmod
    importlib.reload(botmod)

    async def build():
        bot = botmod.Bot()
        bot._http = FakeHTTP()
        bot._user = fluxer.User.from_data(user_dict(BOT_ID), bot._http)
        bot._guilds[GUILD] = fluxer.Guild.from_data({"id": str(GUILD), "name": "Test", "owner_id": str(OWNER)}, bot._http)
        bot._channels[CHAN] = fluxer.Channel.from_data({"id": str(CHAN), "type": 0, "guild_id": str(GUILD)}, bot._http)
        await bot.setup_hook()
        return bot

    return asyncio.run, build


def say(bot, author, content, mentions=()):
    data = {"id": str(bot.http.next_id + 1), "channel_id": str(CHAN), "content": content,
            "author": user_dict(author), "timestamp": "2026-01-01T00:00:00+00:00",
            "mentions": [user_dict(m) for m in mentions]}
    bot.http.next_id += 1
    return bot._dispatch("MESSAGE_CREATE", data)


def embed_of(bot):
    """Last sent embed as a dict (message.send converts, direct http sends may not)."""
    e = bot.http.sent[-1][1]["embeds"][0]
    return e.to_dict() if hasattr(e, "to_dict") else e


def replies(bot):
    return [kw.get("content") or kw.get("embeds") for _, kw in bot.http.sent]


def test_permissions_and_usage(env):
    run, build = env

    async def go():
        bot = await build()
        await say(bot, USER, "?kick <@4>")
        assert "don't have permission" in replies(bot)[-1]
        await say(bot, OWNER, "?staff")
        assert replies(bot)[-1] == "❌ Usage: `?staff admin|mod`"
        await say(bot, OWNER, "?kick")
        assert replies(bot)[-1] == "❌ Missing argument: `member`."
        await say(bot, OWNER, "?nonexistent")
        assert len(bot.http.sent) == 3
    run(go())


def test_kick_hierarchy_and_success(env):
    run, build = env

    async def go():
        bot = await build()
        # MOD and TARGET share the same top role, so the kick must be refused
        await say(bot, MOD, "?kick <@4> spam")
        assert "higher or equal" in replies(bot)[-1]
        # the owner outranks everybody
        await say(bot, OWNER, "?kick <@4> spam")
        assert replies(bot)[-1].startswith("Kicked **user4**")
        assert any(c[0] == "kick_guild_member" for c in bot.http.calls)
        await say(bot, OWNER, "?case 1")
        assert embed_of(bot)["title"] == "Case #1 \u2014 Kick"
    run(go())


def test_warn_flow(env):
    run, build = env

    async def go():
        bot = await build()
        await say(bot, OWNER, "?warn <@3> being rude to people")
        assert replies(bot)[-1] == "Warned **user3**: being rude to people"
        await say(bot, OWNER, "?warnings <@3>")
        assert "being rude" in embed_of(bot)["description"]
        await say(bot, OWNER, "?warndel #1")
        assert replies(bot)[-1] == "Deleted warning `#1`."
        await say(bot, USER, "?clearwarnings <@3>")
        assert "don't have permission" in replies(bot)[-1]
    run(go())


def test_mute_timeout_fallback_and_role(env):
    run, build = env

    async def go():
        bot = await build()
        await say(bot, OWNER, "?mute <@3>")
        assert "No mute role configured" in replies(bot)[-1]
        await say(bot, OWNER, "?mute <@3> 10m too loud")
        assert replies(bot)[-1].startswith("Timed out **user3** for 10m")
        assert any(c[0] == "timeout_guild_member" for c in bot.http.calls)
        await say(bot, OWNER, "?muterole set <@&503>")
        assert "at or above my highest role" in replies(bot)[-1]
    run(go())


def test_channel_lock_unlock_restores_state(env):
    run, build = env

    async def go():
        bot = await build()
        await say(bot, OWNER, "?channel lock")
        assert replies(bot)[-1] == f"🔒 Locked <#{CHAN}>."
        deny = int(bot.http.overwrites[CHAN][0]["deny"])
        assert deny & Permissions.SEND_MESSAGES
        await say(bot, OWNER, "?channel unlock")
        assert not int(bot.http.overwrites[CHAN][0]["deny"]) & Permissions.SEND_MESSAGES
    run(go())


def test_staff_role_grants_mod(env):
    run, build = env

    async def go():
        bot = await build()
        await say(bot, OWNER, "?staff mod add <@&502>")
        assert "is now a moderator role" in replies(bot)[-1]
        await say(bot, OWNER, "?staff mod list")
        assert "<@&502>" in embed_of(bot)["description"]
    run(go())


def test_automod_deletes_banned_word(env):
    run, build = env

    async def go():
        bot = await build()
        await say(bot, OWNER, "?automod on")
        await say(bot, OWNER, "?automod word add contains badword")
        assert replies(bot)[-1].startswith("✅ Added 1 banned word")
        await say(bot, USER, "this has a BadWord inside")
        assert any(c[0] == "delete_message" for c in bot.http.calls)
        before = len([c for c in bot.http.calls if c[0] == "delete_message"])
        await say(bot, MOD, "badword but from a moderator")
        assert len([c for c in bot.http.calls if c[0] == "delete_message"]) == before
    run(go())


def test_settings_logchannel_and_case_log(env):
    run, build = env

    async def go():
        bot = await build()
        await say(bot, OWNER, f"?settings logchannel <#{LOG_CHAN}>")
        assert replies(bot)[-1] == f"✅ Log channel set to <#{LOG_CHAN}>."
        await say(bot, OWNER, "?warn <@3> test reason")
        assert any(cid == LOG_CHAN for cid, _ in bot.http.sent)
    run(go())