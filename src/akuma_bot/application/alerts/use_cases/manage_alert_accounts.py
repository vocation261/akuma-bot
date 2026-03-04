from __future__ import annotations

import asyncio


def _normalize_handle(value: str) -> str:
    return str(value or "").strip().lstrip("@")


async def add_account_to_channel(config_repo, scraper, value: str, channel_id: int | None = None) -> tuple[bool, str]:
    cleaned = _normalize_handle(value)
    config = config_repo.load()
    user_ids = list(config.get("user_ids", []))
    username_map = dict(config.get("username_map", {}))
    user_channels = dict(config.get("user_channels", {}))

    def attach_channel(user_id: str) -> bool:
        if not channel_id:
            return False
        channels = list(user_channels.get(user_id, []))
        if channel_id in channels:
            return False
        channels.append(channel_id)
        user_channels[user_id] = channels
        return True

    if cleaned.isdigit():
        if cleaned in user_ids:
            was_attached = attach_channel(cleaned)
            if was_attached:
                config["user_channels"] = user_channels
                config_repo.save(config)
                return True, f"ID `{cleaned}` ya existia; se agrego este canal para alertas."
            return False, f"El ID `{cleaned}` ya existe."
        user_ids.append(cleaned)
        attach_channel(cleaned)
        config["user_ids"] = user_ids
        config["username_map"] = username_map
        config["user_channels"] = user_channels
        config_repo.save(config)
        return True, f"ID `{cleaned}` agregado."

    user_id, error = await asyncio.to_thread(scraper.get_user_id, cleaned)
    if error:
        return False, f"No se pudo resolver @{cleaned}: {error}"
    if not user_id:
        return False, f"No se pudo resolver @{cleaned}."

    if user_id in user_ids:
        was_attached = attach_channel(user_id)
        if user_id not in username_map:
            username_map[user_id] = cleaned
        config["username_map"] = username_map
        config["user_channels"] = user_channels
        config_repo.save(config)
        if was_attached:
            return True, f"@{cleaned} (ID `{user_id}`) ya existia; se agrego este canal para alertas."
        return False, f"@{cleaned} (ID `{user_id}`) ya está en la lista."

    user_ids.append(user_id)
    username_map[user_id] = cleaned
    attach_channel(user_id)
    config["user_ids"] = user_ids
    config["username_map"] = username_map
    config["user_channels"] = user_channels
    config_repo.save(config)
    return True, f"@{cleaned} agregado con ID `{user_id}`."


def remove_account_from_channel(config_repo, value: str, channel_id: int | None = None) -> tuple[bool, str]:
    cleaned = _normalize_handle(value)
    config = config_repo.load()
    user_ids = list(config.get("user_ids", []))
    username_map = dict(config.get("username_map", {}))
    user_channels = dict(config.get("user_channels", {}))

    if not user_ids:
        return False, "No hay cuentas cargadas."

    if cleaned.isdigit():
        index = int(cleaned)
        if 1 <= index <= len(user_ids):
            target_user_id = user_ids[index - 1]
        else:
            target_user_id = cleaned if cleaned in user_ids else ""
        if not target_user_id:
            return False, "No se encontró ese ID o posición."
    else:
        target_user_id = ""
        for user_id, username in username_map.items():
            if str(username).lower() == cleaned.lower():
                target_user_id = user_id
                break
        if not target_user_id:
            return False, "No se encontró ese handle."

    removed_from_channel = False
    if channel_id:
        channels = list(user_channels.get(target_user_id, []))
        if channel_id in channels:
            channels = [candidate for candidate in channels if candidate != channel_id]
            removed_from_channel = True
            if channels:
                user_channels[target_user_id] = channels
            else:
                user_channels.pop(target_user_id, None)

    if target_user_id in user_channels:
        config["user_ids"] = user_ids
        config["username_map"] = username_map
        config["user_channels"] = user_channels
        config_repo.save(config)
        if removed_from_channel:
            return True, f"Cuenta `{target_user_id}` removida de este canal."
        return False, f"La cuenta `{target_user_id}` sigue activa en otros canales."

    if target_user_id in user_ids:
        user_ids.remove(target_user_id)
    username_map.pop(target_user_id, None)
    user_channels.pop(target_user_id, None)
    config["user_ids"] = user_ids
    config["username_map"] = username_map
    config["user_channels"] = user_channels
    config_repo.save(config)
    return True, f"Cuenta `{target_user_id}` eliminada."


def list_accounts(config_repo) -> tuple[list[str], dict[str, str]]:
    config = config_repo.load()
    return list(config.get("user_ids", [])), dict(config.get("username_map", {}))


def list_accounts_for_guild(config_repo, client, guild_id: int) -> tuple[list[str], dict[str, str]]:
    config = config_repo.load()
    user_ids = list(config.get("user_ids", []))
    username_map = dict(config.get("username_map", {}))
    user_channels = dict(config.get("user_channels", {}))

    if not guild_id:
        return [], username_map

    guild_accounts: list[str] = []
    for user_id in user_ids:
        channels = user_channels.get(user_id, [])
        has_guild_channel = False
        for channel_id in channels:
            channel = client.get_channel(int(channel_id))
            channel_guild = getattr(channel, "guild", None)
            if channel_guild and int(getattr(channel_guild, "id", 0)) == int(guild_id):
                has_guild_channel = True
                break
        if has_guild_channel:
            guild_accounts.append(user_id)

    return guild_accounts, username_map


def map_username(config_repo, user_id: str, username: str) -> tuple[bool, str]:
    normalized_user_id = str(user_id or "").strip()
    normalized_handle = str(username or "").strip().lstrip("@")

    if not normalized_user_id.isdigit():
        return False, "El ID debe ser numérico."
    if not normalized_handle:
        return False, "Debes indicar un @handle válido."

    config = config_repo.load()
    user_ids = list(config.get("user_ids", []))
    if normalized_user_id not in user_ids:
        return False, f"El ID `{normalized_user_id}` no está en vigilancia."

    username_map = dict(config.get("username_map", {}))
    username_map[normalized_user_id] = normalized_handle
    config["username_map"] = username_map
    config_repo.save(config)
    return True, f"Mapeo actualizado: `{normalized_user_id}` -> `@{normalized_handle}`."


def set_interval(config_repo, seconds: int) -> tuple[bool, str]:
    config = config_repo.load()
    config["check_interval"] = max(10, int(seconds))
    config_repo.save(config)
    return True, f"Intervalo de alertas actualizado a {config['check_interval']}s."
