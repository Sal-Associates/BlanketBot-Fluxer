from fluxer import Permissions
import db

MOD_PERMS = (
    Permissions.ADMINISTRATOR
    | Permissions.KICK_MEMBERS
    | Permissions.BAN_MEMBERS
    | Permissions.MODERATE_MEMBERS
    | Permissions.MANAGE_MESSAGES
)


def _staff_role_ids(guild_id: int, role_types: tuple[str, ...]) -> set[int]:
    marks = ",".join("?" * len(role_types))
    with db.get_db() as conn:
        rows = conn.execute(
            f"SELECT role_id FROM staff_roles WHERE guild_id = ? AND role_type IN ({marks})",
            (guild_id, *role_types),
        ).fetchall()
    return {row["role_id"] for row in rows}


async def is_mod(bot, guild_id: int, member) -> bool:
    if await bot.perms(guild_id, member) & MOD_PERMS:
        return True
    return bool(set(member.roles) & _staff_role_ids(guild_id, ("mod", "admin")))


async def is_admin(bot, guild_id: int, member) -> bool:
    if await bot.perms(guild_id, member) & Permissions.ADMINISTRATOR:
        return True
    return bool(set(member.roles) & _staff_role_ids(guild_id, ("admin",)))