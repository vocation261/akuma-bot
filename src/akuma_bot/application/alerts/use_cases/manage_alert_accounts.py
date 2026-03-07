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
                return True, f"ID `{cleaned}` already existed; this channel was added for alerts."
            return False, f"ID `{cleaned}` already exists."
        user_ids.append(cleaned)
        attach_channel(cleaned)
        config["user_ids"] = user_ids
        config["username_map"] = username_map
        config["user_channels"] = user_channels
        config_repo.save(config)
        return True, f"ID `{cleaned}` added."

    user_id, error = await asyncio.to_thread(scraper.get_user_id, cleaned)
    if error:
        return False, f"Could not resolve @{cleaned}: {error}"
    if not user_id:
        return False, f"Could not resolve @{cleaned}."

    if user_id in user_ids:
        was_attached = attach_channel(user_id)
        if user_id not in username_map:
            username_map[user_id] = cleaned
        config["username_map"] = username_map
        config["user_channels"] = user_channels
        config_repo.save(config)
        if was_attached:
            return True, f"@{cleaned} (ID `{user_id}`) already existed; this channel was added for alerts."
        return False, f"@{cleaned} (ID `{user_id}`) is already in the list."

    user_ids.append(user_id)
    username_map[user_id] = cleaned
    attach_channel(user_id)
    config["user_ids"] = user_ids
    config["username_map"] = username_map
    config["user_channels"] = user_channels
    config_repo.save(config)
    return True, f"@{cleaned} added with ID `{user_id}`."


def remove_account_from_channel(config_repo, value: str, channel_id: int | None = None) -> tuple[bool, str]:
    cleaned = _normalize_handle(value)
    config = config_repo.load()
    user_ids = list(config.get("user_ids", []))
    username_map = dict(config.get("username_map", {}))
    user_channels = dict(config.get("user_channels", {}))

    if not user_ids:
        return False, "No accounts configured."

    if cleaned.isdigit():
        index = int(cleaned)
        if 1 <= index <= len(user_ids):
            target_user_id = user_ids[index - 1]
        else:
            target_user_id = cleaned if cleaned in user_ids else ""
        if not target_user_id:
            return False, "ID or position not found."
    else:
        target_user_id = ""
        for user_id, username in username_map.items():
            if str(username).lower() == cleaned.lower():
                target_user_id = user_id
                break
        if not target_user_id:
            return False, "Handle not found."

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
            return True, f"Account `{target_user_id}` removed from this channel."
        return False, f"Account `{target_user_id}` is still active in other channels."

    if target_user_id in user_ids:
        user_ids.remove(target_user_id)
    username_map.pop(target_user_id, None)
    user_channels.pop(target_user_id, None)
    config["user_ids"] = user_ids
    config["username_map"] = username_map
    config["user_channels"] = user_channels
    config_repo.save(config)
    return True, f"Account `{target_user_id}` removed."


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
        return False, "ID must be numeric."
    if not normalized_handle:
        return False, "You must provide a valid @handle."

    config = config_repo.load()
    user_ids = list(config.get("user_ids", []))
    if normalized_user_id not in user_ids:
        return False, f"ID `{normalized_user_id}` is not being monitored."

    username_map = dict(config.get("username_map", {}))
    username_map[normalized_user_id] = normalized_handle
    config["username_map"] = username_map
    config_repo.save(config)
    return True, f"Mapping updated: `{normalized_user_id}` -> `@{normalized_handle}`."


def set_interval(config_repo, seconds: int) -> tuple[bool, str]:
    config = config_repo.load()
    config["check_interval"] = max(10, int(seconds))
    config_repo.save(config)
    return True, f"Alert interval updated to {config['check_interval']}s."
