from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any

import requests

def _env_csv(name: str) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    values = [value.strip() for value in raw.split(",") if value.strip()]
    return values


def _env_json(name: str) -> dict:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


PUBLIC_BEARER = os.environ.get(
    "X_PUBLIC_BEARER",
    "",
).strip()

BASE_HEADERS = {
    "User-Agent": os.environ.get("X_USER_AGENT", "").strip(),
    "Accept-Language": os.environ.get("X_ACCEPT_LANGUAGE", "").strip(),
    "Origin": os.environ.get("X_ORIGIN", "").strip(),
    "Referer": os.environ.get("X_REFERER", "").strip(),
}

GQL_USER_BY_SCREEN_NAME_IDS = _env_csv("X_GQL_USER_BY_SCREEN_NAME_IDS")

GQL_USER_BY_REST_ID_IDS = _env_csv("X_GQL_USER_BY_REST_ID_IDS")

GQL_USER_TWEETS_QID = os.environ.get("X_GQL_USER_TWEETS_QID", "").strip()
GQL_AUDIO_SPACE_BY_ID_QID = os.environ.get("X_GQL_AUDIO_SPACE_BY_ID_QID", "").strip()

GQL_FEATURES = json.dumps(_env_json("X_GQL_FEATURES_JSON"))

GQL_USER_TWEETS_FEATURES = _env_json("X_GQL_USER_TWEETS_FEATURES_JSON")

GQL_AUDIO_SPACE_FEATURES = _env_json("X_GQL_AUDIO_SPACE_FEATURES_JSON")


def _extract_space_id_from_text(text: str | None) -> str:
    if not text:
        return ""
    match = re.search(r"/i/spaces/([A-Za-z0-9]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"/spaces/([A-Za-z0-9]+)", text)
    if match:
        return match.group(1)
    return ""


def _extract_space_candidates(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        binding_values = obj.get("binding_values")
        if isinstance(binding_values, list):
            for item in binding_values:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key", ""))
                value = item.get("value") or {}
                if key == "id":
                    candidate = str(value.get("string_value") or "").strip()
                    if re.fullmatch(r"[A-Za-z0-9]{12,20}", candidate):
                        out.add(candidate)
                if key == "card_url":
                    candidate = _extract_space_id_from_text(str(value.get("string_value") or ""))
                    if candidate:
                        out.add(candidate)
        for value in obj.values():
            _extract_space_candidates(value, out)
        return

    if isinstance(obj, list):
        for value in obj:
            _extract_space_candidates(value, out)
        return

    if isinstance(obj, str):
        candidate = _extract_space_id_from_text(obj)
        if candidate:
            out.add(candidate)


class XSpacesScraper:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._guest_token = ""
        self._guest_token_ts = 0.0
        self._guest_ttl = max(60, _env_int("X_GUEST_TTL_SECONDS", 1200))
        self._username_cache: dict[str, str] = {}
        self._web_base = os.environ.get("X_WEB_BASE_URL", "").strip().rstrip("/")
        self._api_base = os.environ.get("X_API_BASE_URL", "").strip().rstrip("/")
        self._guest_activation_bases = _env_csv("X_GUEST_ACTIVATION_BASES")
        self._http_timeout_short = max(5, _env_int("X_HTTP_TIMEOUT_SHORT", 10))
        self._http_timeout_medium = max(8, _env_int("X_HTTP_TIMEOUT_MEDIUM", 12))
        self._http_timeout_long = max(10, _env_int("X_HTTP_TIMEOUT_LONG", 15))

    def _missing_env(self) -> list[str]:
        required = {
            "X_PUBLIC_BEARER": bool(PUBLIC_BEARER),
            "X_WEB_BASE_URL": bool(self._web_base),
            "X_API_BASE_URL": bool(self._api_base),
            "X_GUEST_ACTIVATION_BASES": bool(self._guest_activation_bases),
            "X_GQL_USER_BY_SCREEN_NAME_IDS": bool(GQL_USER_BY_SCREEN_NAME_IDS),
            "X_GQL_USER_BY_REST_ID_IDS": bool(GQL_USER_BY_REST_ID_IDS),
            "X_GQL_USER_TWEETS_QID": bool(GQL_USER_TWEETS_QID),
            "X_GQL_AUDIO_SPACE_BY_ID_QID": bool(GQL_AUDIO_SPACE_BY_ID_QID),
        }
        return [name for name, ok in required.items() if not ok]

    def _auth_cookies(self) -> dict[str, str]:
        auth_token = os.environ.get("X_AUTH_TOKEN", "").strip()
        ct0 = os.environ.get("X_CT0", "").strip()
        twid = os.environ.get("X_TWID", "").strip()
        if auth_token and ct0:
            data = {"auth_token": auth_token, "ct0": ct0}
            if twid:
                data["twid"] = twid
            return data
        return {}

    def _cookie_header(self, extra: dict[str, str] | None = None) -> str:
        data = self._auth_cookies()
        if extra:
            data.update(extra)
        return "; ".join(f"{k}={v}" for k, v in data.items() if v)

    def _graphql_headers(self, guest_token: str = "") -> dict[str, str]:
        headers = {
            **BASE_HEADERS,
            "Authorization": f"Bearer {PUBLIC_BEARER}",
            "x-twitter-active-user": "yes",
            "x-twitter-client-language": "es",
            "Content-Type": "application/json",
        }
        if guest_token:
            headers["x-guest-token"] = guest_token
        auth_cookies = self._auth_cookies()
        if auth_cookies:
            cookie = self._cookie_header()
            if cookie:
                headers["Cookie"] = cookie
            ct0 = auth_cookies.get("ct0", "")
            if ct0:
                headers["x-csrf-token"] = ct0
                headers["x-twitter-auth-type"] = "OAuth2Session"
        return headers

    def _get_guest_token(self) -> str:
        if self._missing_env():
            return ""
        if self._guest_token and (time.time() - self._guest_token_ts < self._guest_ttl):
            return self._guest_token

        headers = {
            **BASE_HEADERS,
            "Authorization": f"Bearer {PUBLIC_BEARER}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        for base in self._guest_activation_bases:
            try:
                response = self._session.post(
                    f"{base}/1.1/guest/activate.json",
                    headers=headers,
                    data="",
                    timeout=self._http_timeout_short,
                )
                if response.status_code != 200:
                    continue
                token = str(response.json().get("guest_token") or "")
                if token:
                    self._guest_token = token
                    self._guest_token_ts = time.time()
                    return self._guest_token
            except Exception:
                continue
        return ""

    def _graphql_user_result(self, username: str) -> tuple[dict, str | None]:
        guest_token = self._get_guest_token()
        headers = self._graphql_headers(guest_token)
        for qid in GQL_USER_BY_SCREEN_NAME_IDS:
            try:
                response = self._session.get(
                    f"{self._web_base}/i/api/graphql/{qid}/UserByScreenName",
                    params={
                        "variables": json.dumps(
                            {
                                "screen_name": username,
                                "withSafetyModeUserFields": True,
                                "withLiveInfo": True,
                            }
                        ),
                        "features": GQL_FEATURES,
                    },
                    headers=headers,
                    timeout=self._http_timeout_short,
                )
                if response.status_code == 429:
                    return {}, "rate_limit"
                if response.status_code != 200:
                    continue
                result = response.json().get("data", {}).get("user", {}).get("result", {})
                if result:
                    return result, None
            except Exception:
                continue
        return {}, None

    def get_user_profile(self, username: str) -> dict:
        if self._missing_env():
            return {}
        cleaned = str(username or "").strip().lstrip("@")
        if not cleaned:
            return {}
        result, _ = self._graphql_user_result(cleaned)
        if not result:
            return {}

        legacy = result.get("legacy", {}) if isinstance(result, dict) else {}
        avatar = str(legacy.get("profile_image_url_https", "") or "")
        if avatar:
            avatar = avatar.replace("_normal", "")
        return {
            "username": legacy.get("screen_name") or cleaned,
            "name": legacy.get("name") or "",
            "followers_count": int(legacy.get("followers_count") or 0),
            "profile_image_url": avatar,
        }

    def get_user_id(self, username: str) -> tuple[str | None, str | None]:
        missing = self._missing_env()
        if missing:
            return None, f"Faltan variables env del scraper: {', '.join(missing)}"
        cleaned = str(username or "").strip()
        cleaned = re.sub(r"^https?://(www\.)?(x\.com|twitter\.com)/", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.split("/")[0].split("?")[0].split("#")[0].strip().lstrip("@")
        if not cleaned:
            return None, "Handle vacio. Usa @usuario o URL como https://x.com/usuario"

        result, error = self._graphql_user_result(cleaned)
        if error == "rate_limit":
            return None, "Demasiadas peticiones a Twitter, espera unos minutos."
        uid = str(result.get("rest_id", "") or "")
        if uid:
            return uid, None
        return None, f"No se pudo resolver @{cleaned}. Verifica el handle."

    def _get_usernames_from_ids(self, user_ids: list[str], guest_token: str) -> dict[str, str]:
        result: dict[str, str] = {}
        remaining: list[str] = []
        for uid in user_ids:
            key = str(uid)
            if key in self._username_cache:
                result[key] = self._username_cache[key]
            else:
                remaining.append(key)

        if not remaining:
            return result

        try:
            response = self._session.get(
                f"{self._web_base}/i/api/1.1/users/lookup.json",
                params={"user_id": ",".join(remaining)},
                headers=self._graphql_headers(guest_token),
                timeout=self._http_timeout_short,
            )
            if response.status_code == 200 and isinstance(response.json(), list):
                for user in response.json():
                    uid = str(user.get("id_str", "") or "")
                    username = str(user.get("screen_name", "") or "")
                    if uid and username:
                        result[uid] = username
                        self._username_cache[uid] = username
                remaining = [uid for uid in remaining if uid not in result]
        except Exception:
            pass

        if not remaining:
            return result

        for uid in remaining:
            for qid in GQL_USER_BY_REST_ID_IDS:
                try:
                    response = self._session.get(
                        f"{self._web_base}/i/api/graphql/{qid}/UserByRestId",
                        params={
                            "variables": json.dumps({"userId": str(uid), "withSafetyModeUserFields": True}),
                            "features": GQL_FEATURES,
                        },
                        headers=self._graphql_headers(guest_token),
                        timeout=self._http_timeout_short,
                    )
                    if response.status_code != 200:
                        continue
                    user_result = (response.json().get("data") or {}).get("user", {}).get("result", {})
                    core = user_result.get("core") or {}
                    username = core.get("screen_name") or (user_result.get("legacy") or {}).get("screen_name") or ""
                    if username:
                        result[uid] = username
                        self._username_cache[uid] = username
                        break
                except Exception:
                    continue

        return result

    def fetch_space_metadata(self, space_id: str, guest_token: str) -> dict:
        try:
            response = self._session.get(
                f"{self._api_base}/graphql/{GQL_AUDIO_SPACE_BY_ID_QID}/AudioSpaceById",
                params={
                    "variables": json.dumps(
                        {
                            "id": str(space_id),
                            "isMetatagsQuery": False,
                            "withReplays": True,
                            "withListeners": True,
                        }
                    ),
                    "features": json.dumps(GQL_AUDIO_SPACE_FEATURES),
                },
                headers=self._graphql_headers(guest_token),
                timeout=self._http_timeout_long,
            )
            if response.status_code != 200:
                return {}
            audio_space = (response.json().get("data") or {}).get("audioSpace") or {}
            metadata = audio_space.get("metadata") or {}
            if not metadata:
                return {}

            creator = ((metadata.get("creator_results") or {}).get("result")) or {}
            core = creator.get("core") or {}
            legacy = creator.get("legacy") or {}
            avatar = ((creator.get("avatar") or {}).get("image_url") or "")
            if avatar:
                avatar = avatar.replace("_normal", "")

            listeners = metadata.get("total_live_listeners")
            if listeners is None:
                listeners = ((audio_space.get("participants") or {}).get("total"))
            return {
                "id": str(space_id),
                "title": str(metadata.get("title") or "(Sin título)"),
                "state": str(metadata.get("state") or "").lower(),
                "listener_count": int(listeners or 0),
                "creator_id": str(creator.get("rest_id") or ""),
                "username": str(core.get("screen_name") or ""),
                "name": str(core.get("name") or ""),
                "followers_count": int(legacy.get("followers_count") or 0),
                "profile_image_url": avatar,
            }
        except Exception:
            return {}

    def _get_audio_space_payload(self, space_id: str, guest_token: str) -> dict:
        try:
            response = self._session.get(
                f"{self._api_base}/graphql/{GQL_AUDIO_SPACE_BY_ID_QID}/AudioSpaceById",
                params={
                    "variables": json.dumps(
                        {
                            "id": str(space_id),
                            "isMetatagsQuery": False,
                            "withReplays": True,
                            "withListeners": True,
                        }
                    ),
                    "features": json.dumps(GQL_AUDIO_SPACE_FEATURES),
                },
                headers=self._graphql_headers(guest_token),
                timeout=self._http_timeout_long,
            )
            if response.status_code != 200:
                return {}
            return response.json()
        except Exception:
            return {}

    @staticmethod
    def _parse_user(candidate: Any) -> dict:
        source = candidate if isinstance(candidate, dict) else {}
        item = dict(source)
        user_results = source.get("user_results") if isinstance(source.get("user_results"), dict) else {}
        if user_results:
            nested = user_results.get("result") if isinstance(user_results.get("result"), dict) else {}
            if nested:
                item = nested
        if "result" in item and isinstance(item.get("result"), dict):
            item = item["result"]

        legacy = item.get("legacy") or {}
        core = item.get("core") or {}
        avatar = (
            ((item.get("avatar") or {}).get("image_url"))
            or legacy.get("profile_image_url_https")
            or legacy.get("profile_image_url")
            or source.get("avatar_url")
            or ""
        )
        if avatar:
            avatar = str(avatar).replace("_normal", "")

        user_id = str(
            item.get("rest_id")
            or item.get("id")
            or user_results.get("rest_id")
            or legacy.get("id_str")
            or source.get("rest_id")
            or ""
        )
        username = str(
            core.get("screen_name")
            or legacy.get("screen_name")
            or item.get("screen_name")
            or source.get("twitter_screen_name")
            or ""
        ).strip().lstrip("@")
        name = str(
            core.get("name")
            or legacy.get("name")
            or item.get("name")
            or source.get("display_name")
            or ""
        ).strip()
        if not name:
            name = username or user_id or "unknown"
        return {
            "id": user_id,
            "username": username,
            "name": name,
            "profile_image_url": str(avatar or ""),
        }

    def _coerce_user_list(self, payload: Any) -> list[dict]:
        out: list[dict] = []
        if isinstance(payload, list):
            for item in payload:
                parsed = self._parse_user(item)
                if parsed.get("id") or parsed.get("username"):
                    out.append(parsed)
            return out
        if isinstance(payload, dict):
            for key in ("users", "items"):
                if isinstance(payload.get(key), list):
                    return self._coerce_user_list(payload[key])
            parsed = self._parse_user(payload)
            if parsed.get("id") or parsed.get("username"):
                return [parsed]
        return out

    @staticmethod
    def _dedupe_users(items: list[dict]) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for item in items:
            key = str(item.get("id") or item.get("username") or item.get("name") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def get_space_participants(self, space_ref: str) -> dict:
        missing = self._missing_env()
        if missing:
            return {"ok": False, "error": f"Faltan variables env del scraper: {', '.join(missing)}"}
        space_id = str(space_ref or "").strip()
        if "/" in space_id:
            space_id = _extract_space_id_from_text(space_id)
        if not re.fullmatch(r"[A-Za-z0-9]{12,20}", space_id):
            return {"ok": False, "error": "Space ID/url invalido."}

        guest_token = self._get_guest_token()
        if not guest_token:
            return {"ok": False, "error": "No se pudo obtener guest token de X."}

        payload = self._get_audio_space_payload(space_id, guest_token)
        if not payload:
            return {"ok": False, "error": "No se pudo consultar AudioSpaceById."}

        audio_space = (payload.get("data") or {}).get("audioSpace") or {}
        metadata = audio_space.get("metadata") or {}
        participants = audio_space.get("participants") or {}
        if not metadata:
            return {"ok": False, "error": "Space no encontrado o sin metadata."}

        host = self._parse_user((metadata.get("creator_results") or {}).get("result") or {})
        host_id = str(host.get("id") or "")

        admins = self._coerce_user_list(participants.get("admins"))
        speakers = self._coerce_user_list(participants.get("speakers"))
        listeners = self._coerce_user_list(participants.get("listeners"))

        cohosts = []
        for user in admins:
            if host_id and str(user.get("id") or "") == host_id:
                continue
            cohosts.append(user)

        cohosts = self._dedupe_users(cohosts)
        cohost_keys = {
            str(user.get("id") or user.get("username") or user.get("name") or "").strip().lower()
            for user in cohosts
        }
        speakers = self._dedupe_users(
            [
                user
                for user in speakers
                if str(user.get("id") or "") != host_id
                and str(user.get("id") or user.get("username") or user.get("name") or "").strip().lower() not in cohost_keys
            ]
        )
        speaker_keys = {
            str(user.get("id") or user.get("username") or user.get("name") or "").strip().lower()
            for user in speakers
        }
        listeners = self._dedupe_users(
            [
                user
                for user in listeners
                if str(user.get("id") or "") != host_id
                and str(user.get("id") or user.get("username") or user.get("name") or "").strip().lower() not in cohost_keys
                and str(user.get("id") or user.get("username") or user.get("name") or "").strip().lower() not in speaker_keys
            ]
        )

        listener_count = metadata.get("total_live_listeners")
        if listener_count is None:
            listener_count = participants.get("total")

        return {
            "ok": True,
            "space_id": space_id,
            "title": str(metadata.get("title") or "(Sin título)"),
            "state": str(metadata.get("state") or "").lower(),
            "host": host,
            "cohosts": cohosts,
            "speakers": speakers,
            "listeners": listeners,
            "listener_count": int(listener_count or 0),
            "participant_count": int(participants.get("total") or 0),
        }

    def get_space_timing(self, space_ref: str) -> dict:
        missing = self._missing_env()
        if missing:
            return {"ok": False, "error": f"Faltan variables env del scraper: {', '.join(missing)}"}

        space_id = str(space_ref or "").strip()
        if "/" in space_id:
            space_id = _extract_space_id_from_text(space_id)
        if not re.fullmatch(r"[A-Za-z0-9]{12,20}", space_id):
            return {"ok": False, "error": "Space ID/url invalido."}

        guest_token = self._get_guest_token()
        if not guest_token:
            return {"ok": False, "error": "No se pudo obtener guest token de X."}

        payload = self._get_audio_space_payload(space_id, guest_token)
        if not payload:
            return {"ok": False, "error": "No se pudo consultar AudioSpaceById."}
        metadata = (((payload.get("data") or {}).get("audioSpace") or {}).get("metadata") or {})
        if not metadata:
            return {"ok": False, "error": "Space no encontrado o sin metadata."}

        started_at_ms = metadata.get("started_at")
        if started_at_ms is None:
            started_at_ms = metadata.get("created_at")
        try:
            started_at_ms = int(started_at_ms or 0)
        except Exception:
            started_at_ms = 0

        return {
            "ok": True,
            "space_id": space_id,
            "state": str(metadata.get("state") or "").lower(),
            "title": str(metadata.get("title") or ""),
            "started_at_ms": started_at_ms,
        }

    def collect_space_ids_from_user_tweets(self, user_id: str, guest_token: str) -> list[str]:
        try:
            response = self._session.get(
                f"{self._api_base}/graphql/{GQL_USER_TWEETS_QID}/UserTweets",
                params={
                    "variables": json.dumps(
                        {
                            "userId": str(user_id),
                            "count": 30,
                            "includePromotedContent": True,
                            "withQuickPromoteEligibilityTweetFields": True,
                            "withVoice": True,
                        }
                    ),
                    "features": json.dumps(GQL_USER_TWEETS_FEATURES),
                    "fieldToggles": json.dumps({"withArticlePlainText": False}),
                },
                headers=self._graphql_headers(guest_token),
                timeout=self._http_timeout_long,
            )
            if response.status_code != 200:
                return []
            candidates: set[str] = set()
            _extract_space_candidates(response.json(), candidates)
            return sorted(sid for sid in candidates if re.fullmatch(r"[A-Za-z0-9]{12,20}", sid))
        except Exception:
            return []

    def _get_space_info_ytdlp(self, space_id: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9]{12,20}", str(space_id)):
            return {}
        try:
            process = subprocess.run(
                ["yt-dlp", "--skip-download", "--dump-json", f"https://x.com/i/spaces/{space_id}"],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
            raw = (process.stdout or "").strip()
            if not raw:
                return {}
            data = json.loads(raw.splitlines()[-1])
            live_status = str(data.get("live_status") or "").lower()
            is_live = bool(data.get("is_live", False)) or live_status in {"is_live", "live"}
            return {
                "id": str(data.get("id") or space_id),
                "title": str(data.get("fulltitle") or data.get("title") or "(Sin título)"),
                "state": "running" if is_live else "ended",
                "username": str(data.get("uploader_id") or ""),
                "name": str(data.get("uploader") or ""),
                "profile_image_url": str(data.get("thumbnail") or ""),
                "yt_live": is_live,
            }
        except Exception:
            return {}

    def find_live_spaces_for_username(self, username: str, guest_token: str) -> list[dict]:
        found: list[dict] = []
        headers = self._graphql_headers(guest_token)
        for qid in GQL_USER_BY_SCREEN_NAME_IDS:
            try:
                response = self._session.get(
                    f"{self._web_base}/i/api/graphql/{qid}/UserByScreenName",
                    params={
                        "variables": json.dumps(
                            {
                                "screen_name": username,
                                "withSafetyModeUserFields": True,
                                "withLiveInfo": True,
                            }
                        ),
                        "features": GQL_FEATURES,
                    },
                    headers=headers,
                    timeout=self._http_timeout_short,
                )
                if response.status_code != 200:
                    if response.status_code == 429:
                        return []
                    continue

                result = response.json().get("data", {}).get("user", {}).get("result", {})
                if not result:
                    continue

                core = result.get("core") or {}
                legacy = result.get("legacy") or {}
                rest_id = str(result.get("rest_id") or "")
                uname = str(core.get("screen_name") or legacy.get("screen_name") or username)
                name = str(core.get("name") or legacy.get("name") or "")
                followers = int(legacy.get("followers_count") or 0)
                avatar = str(legacy.get("profile_image_url_https") or "")
                if avatar:
                    avatar = avatar.replace("_normal", "")

                edges = (((result.get("live_info") or {}).get("AudioSpaces") or {}).get("edges") or [])
                for edge in edges:
                    node = edge.get("node") or {}
                    metadata = node.get("metadata") or {}
                    sid = str(node.get("rest_id") or metadata.get("rest_id") or "")
                    state = str(metadata.get("state") or "").lower()
                    if sid and state in {"running", "live"}:
                        found.append(
                            {
                                "id": sid,
                                "title": str(metadata.get("title") or "(Sin título)"),
                                "state": state,
                                "listener_count": int(metadata.get("total_live_listeners") or 0),
                                "creator_id": rest_id,
                                "username": uname,
                                "name": name,
                                "followers_count": followers,
                                "profile_image_url": avatar,
                            }
                        )
                if found:
                    return found

                candidate_ids: set[str] = set()
                _extract_space_candidates(result, candidate_ids)
                for sid in sorted(candidate_ids):
                    if not re.fullmatch(r"[A-Za-z0-9]{12,20}", sid):
                        continue
                    info = self.fetch_space_metadata(sid, guest_token)
                    if not info:
                        continue
                    if str(info.get("state", "")).lower() not in {"running", "live"}:
                        continue
                    if not info.get("creator_id"):
                        info["creator_id"] = rest_id
                    if not info.get("username"):
                        info["username"] = uname
                    if not info.get("name"):
                        info["name"] = name
                    if not info.get("followers_count"):
                        info["followers_count"] = followers
                    if not info.get("profile_image_url"):
                        info["profile_image_url"] = avatar
                    found.append(info)
                return found
            except Exception:
                continue
        return found

    def find_live_spaces_for_accounts(self, user_ids: list[str], username_map: dict[str, str] | None = None) -> list[dict]:
        if self._missing_env():
            return []
        if not user_ids:
            return []
        username_map = username_map or {}
        guest_token = self._get_guest_token()
        if not guest_token:
            return []

        spaces: list[dict] = []
        seen_ids: set[str] = set()

        def merge(items: list[dict]) -> None:
            for item in items:
                sid = str(item.get("id") or "")
                if not sid or sid in seen_ids:
                    continue
                seen_ids.add(sid)
                spaces.append(item)

        for uid in user_ids:
            username = username_map.get(str(uid))
            if not username:
                continue
            found = self.find_live_spaces_for_username(username, guest_token)
            for item in found:
                if not item.get("creator_id"):
                    item["creator_id"] = str(uid)
            merge(found)
        if spaces:
            return spaces

        missing_ids = [str(uid) for uid in user_ids if str(uid) not in username_map]
        if missing_ids:
            username_map = dict(username_map)
            username_map.update(self._get_usernames_from_ids(missing_ids, guest_token))

        for uid in user_ids:
            candidate_ids = self.collect_space_ids_from_user_tweets(str(uid), guest_token)
            for sid in candidate_ids:
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
                info = self.fetch_space_metadata(sid, guest_token)
                ytdlp_info = self._get_space_info_ytdlp(sid)
                if not info and not ytdlp_info:
                    continue
                if not info and ytdlp_info:
                    info = dict(ytdlp_info)

                state = str(info.get("state") or "").lower()
                live_by_graphql = state in {"running", "live"}
                live_by_ytdlp = bool(ytdlp_info.get("yt_live", False))
                if not (live_by_graphql or live_by_ytdlp):
                    continue

                if ytdlp_info:
                    if not info.get("title"):
                        info["title"] = ytdlp_info.get("title", "(Sin título)")
                    if not info.get("username"):
                        info["username"] = ytdlp_info.get("username", "")
                    if not info.get("name"):
                        info["name"] = ytdlp_info.get("name", "")
                    if not info.get("profile_image_url"):
                        info["profile_image_url"] = ytdlp_info.get("profile_image_url", "")
                    if not live_by_graphql and live_by_ytdlp:
                        info["state"] = "running"

                if not info.get("creator_id"):
                    info["creator_id"] = str(uid)
                if not info.get("username"):
                    info["username"] = username_map.get(str(uid), str(uid))
                spaces.append(info)

        return spaces

    # Backward-compatible aliases
    def _get_audio_space_info(self, space_id: str, guest_token: str) -> dict:
        return self.fetch_space_metadata(space_id, guest_token)

    def _collect_space_ids_from_user_tweets(self, user_id: str, guest_token: str) -> list[str]:
        return self.collect_space_ids_from_user_tweets(user_id, guest_token)

    def _live_spaces_for_username(self, username: str, guest_token: str) -> list[dict]:
        return self.find_live_spaces_for_username(username, guest_token)

    def check_spaces(self, user_ids: list[str], username_map: dict[str, str] | None = None) -> list[dict]:
        return self.find_live_spaces_for_accounts(user_ids, username_map)
