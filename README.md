# BlanketBot

A moderation and logging bot for Fluxer, built on fluxer.py

---

## Requirements

- Python 3.12+
- fluxer.py 0.4.2+
- python-dotenv, aiohttp, Pillow, pytesseract, python-Levenshtein
- Tesseract OCR installed on the host (scam detection; the Docker image includes it)

```
pip install -r requirements.txt
```

---
## Setup (Docker)

1. Create a bot application on Fluxer and copy its token
2. Enable the privileged intents the bot requests: **Server Members** and **Message Content**
3. Invite the bot with the permissions listed under Permissions Required below
4. Copy `.env.example` to `.env` and fill in your token
5. Run: `docker compose up -d`

## Setup

Steps 1 to 4 are the same as above, then run: `python3 bot.py`

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `FLUXER_TOKEN` | Yes | Your bot token |
| `FLUXER_API_URL` | No | API base URL for a self-hosted Fluxer instance |
| `COMMAND_PREFIX` | No | Command prefix (default `?`) |
| `LOG_CHANNEL_ID` | No | Fallback log channel ID if a guild hasn't run `?settings logchannel` |
| `DB_PATH` | No | SQLite path (default `bot.db`) |

---

## First-Time Setup

Run these after inviting the bot.

```
?settings logchannel #mod-log        set log channel
?muterole create                     create the Muted role
?staff mod add @Moderator            give a role access to mod commands
?staff admin add @Admin              give a role access to admin commands
?lockdown channel add #general       add channels to the lockdown list (repeat as needed)
?automod on                          enable automod (off by default)
```

---

## Command Reference

Prefix: `?` (configurable). All commands are prefix commands.

---

### Moderation

| Command | Description |
|---|---|
| `?kick @user [reason]` | Kick a member |
| `?ban @user [reason]` | Ban a member |
| `?unban <user_id> [reason]` | Unban a user by ID |
| `?softban @user [reason]` | Ban + immediately unban (deletes 7 days of messages) |
| `?mute @user [duration] [reason]` | Mute using the mute role. |
| `?unmute @user` | Remove mute role (and clear timeout if present) |
| `?warn @user <reason>` | Issue a warning |
| `?warndel <#id>` | Delete a warning by its ID |
| `?warnings @user` | View all warnings for a member |
| `?clearwarnings @user` | Clear all warnings (admin only) |

Duration format: `10s`, `5m`, `2h`, `1d`, `1day`, `30mins`, etc.

---

### Notes & Tools

| Command | Description |
|---|---|
| `?note add @user <text>` | Add a staff note |
| `?note list @user` | List notes for a member |
| `?note edit <#id> <text>` | Edit a note |
| `?note del <#id>` | Delete a note |
| `?purge [filter] [args]` | Bulk delete messages (see filters below) |
| `?channel lock [#channel]` | Lock a channel (deny @everyone send messages) |
| `?channel unlock [#channel]` | Unlock a channel |
| `?channel slowmode <seconds> [#channel]` | Set slowmode (0 to disable) |

**Purge filters:** `user @user`, `match <text>`, `not <text>`, `startswith <text>`, `endswith <text>`, `links`, `invites`, `images`, `mentions`, `embeds`, `bots`, `humans`, `text`  
Default (no filter): deletes up to 100 recent messages.

---

### Case History

| Command | Description |
|---|---|
| `?modlogs @user [page]` | View mod history for a user (5 cases per page) |
| `?modstats [@mod]` | Mod action stats. Omit mod for server-wide stats. |
| `?case <number>` | Look up a specific case by number |
| `?whois [@user]` | User profile: roles, join date, warning count, recent cases (any member) |

---

### Info

| Command | Description |
|---|---|
| `?info server` | Server info (member count, channels, roles, creation date) |
| `?info channel [#channel]` | Channel info |
| `?help` | Command list |
| `?about` | Bot info |

---

### Admin - Settings

| Command | Description |
|---|---|
| `?settings` | View current guild settings |
| `?settings logchannel #channel` | Set the mod log channel |
| `?settings logchannel off` | Clear the mod log channel |

---

### Admin - Mute Role

| Command | Description |
|---|---|
| `?muterole` | View current mute role |
| `?muterole create` | Create a Muted role and apply deny permissions to all text channels |
| `?muterole set @role` | Use an existing role as the mute role |
| `?muterole off` | Clear mute role (mutes fall back to timeout) |

---

### Admin - Staff Roles

Staff roles grant members access to mod/admin commands even without the corresponding Discord permission.

| Command | Description |
|---|---|
| `?staff mod add @role` | Add a moderator role |
| `?staff mod del @role` | Remove a moderator role |
| `?staff mod list` | List moderator roles |
| `?staff admin add @role` | Add an admin role |
| `?staff admin del @role` | Remove an admin role |
| `?staff admin list` | List admin roles |

---

### Admin - Automod

Automod is disabled by default. Enable it with `?automod on`.

| Command | Description |
|---|---|
| `?automod` | View automod status |
| `?automod on / off` | Enable or disable automod |
| `?automod antispam on/off` | Toggle spam detection |
| `?automod anticaps on/off` | Toggle caps filter |
| `?automod antiinvite on/off` | Toggle Discord invite blocking |
| `?automod antimention on/off` | Toggle mass mention protection |
| `?automod word add contains\|exact <word,...>` | Add banned words (comma-separated) |
| `?automod word del <#id or text>` | Remove a banned word by ID or value |
| `?automod word list` | List banned words |
| `?automod blacklist add <domain,...>` | Block domains/URLs |
| `?automod blacklist remove <domain>` | Remove a blacklisted domain |
| `?automod blacklist list` | List blacklisted domains |
| `?automod whitelist add <domain,...>` | Whitelist domains (bypass blacklist) |
| `?automod whitelist remove <domain>` | Remove a whitelisted domain |
| `?automod whitelist list` | List whitelisted domains |
| `?automod ignore channel add #channel` | Exclude a channel from automod |
| `?automod ignore channel remove #channel` | Re-include a channel |
| `?automod ignore channel list` | List ignored channels |
| `?automod ignore role add @role` | Exclude a role from automod |
| `?automod ignore role remove @role` | Re-include a role |
| `?automod ignore role list` | List ignored roles |
| `?automod ignored` | View all ignored channels and roles |
| `?automod threshold show` | View current thresholds |
| `?automod threshold reset caps\|spam\|mentions\|all` | Reset thresholds to defaults |
| `?automod threshold spam-count <n>` | Messages before spam trigger (3–20) |
| `?automod threshold spam-window <s>` | Spam detection window in seconds (1–60) |
| `?automod threshold caps <n>` | Caps percentage to trigger filter (50–100) |
| `?automod threshold mentions <n>` | Mention count to trigger filter (2–50) |

---

### Admin - Lockdown

| Command | Description |
|---|---|
| `?lockdown enable [reason]` | Deny @everyone send messages in all configured channels |
| `?lockdown disable [reason]` | Restore send messages in all configured channels |
| `?lockdown status` | Show locked/unlocked state per channel |
| `?lockdown channel add #channel` | Add a channel to the lockdown list |
| `?lockdown channel remove #channel` | Remove a channel from the lockdown list |
| `?lockdown channel list` | List all lockdown channels |

---

## Permissions Required

| Permission | Used for |
|---|---|
| Manage Roles | Mute role assignment |
| Manage Channels | Channel lock, lockdown, slowmode, mute role setup |
| Kick Members | Kick |
| Ban Members | Ban, unban, softban |
| Moderate Members | Timeout fallback and scam auto-timeout |
| Manage Messages | Purge, automod message deletion |
| Read Message History | Purge |

---

# Credits

- **K1ngblanket**
- **LaiZBoi**
- **Tilley8**