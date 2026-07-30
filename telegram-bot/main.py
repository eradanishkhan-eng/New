"""
Telegram Premium Referral Bot — Single File Version
All code merged into one file for easy deployment.
"""

# ══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import firebase_admin
from firebase_admin import credentials, db as firebase_db
from cachetools import TTLCache
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, BaseMiddleware, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import BaseFilter, Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, TelegramObject,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ContentType,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

load_dotenv()

# ══════════════════════════════════════════════════════════════════════════════
# LOGGER
# ══════════════════════════════════════════════════════════════════════════════

def setup_logger(name: str = "bot", log_level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(log_level)
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    return logger

logger = setup_logger()

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "YourBot").lstrip("@")
    FIREBASE_CREDENTIALS_PATH: str = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase_credentials.json")
    FIREBASE_DATABASE_URL: str = os.getenv("FIREBASE_DATABASE_URL", "")
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "")
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8443"))
    USE_POLLING: bool = os.getenv("USE_POLLING", "true").lower() == "true"
    DEFAULT_MIN_REFERRALS: int = 10
    DEFAULT_REFERRAL_REWARD: int = 1
    DEFAULT_CLAIM_REWARD_NAME: str = "Telegram Premium"
    THROTTLE_RATE: float = 0.5
    BROADCAST_DELAY: float = 0.05
    CACHE_USER_TTL: int = 60
    CACHE_SETTINGS_TTL: int = 300
    CACHE_CHANNELS_TTL: int = 120

    @staticmethod
    def get_initial_admin_ids() -> List[int]:
        raw = os.getenv("ADMIN_IDS", "")
        ids: List[int] = []
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        return ids

    @classmethod
    def validate(cls) -> None:
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is not set in environment variables.")
        if not cls.FIREBASE_DATABASE_URL:
            raise ValueError("FIREBASE_DATABASE_URL is not set in environment variables.")

config = Config()

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

BTN_PREMIUM = "⭐ Telegram Premium Free"
BTN_REFER = "👥 Refer"
BTN_PROFILE = "👤 Profile"
BTN_CLAIM = "🎁 Claim Telegram Premium"
BTN_ADMIN_DASHBOARD = "📊 Dashboard"
BTN_ADMIN_REQUESTS = "🎁 Premium Requests"
BTN_ADMIN_BROADCAST = "📢 Broadcast"
BTN_ADMIN_FORCE_JOIN = "📌 Force Join"
BTN_ADMIN_STATISTICS = "📈 Statistics"
BTN_ADMIN_SETTINGS = "⚙️ Settings"
BTN_ADMIN_ADMINS = "👑 Admins"
BTN_ADMIN_USERS = "👥 User Management"
BTN_ADMIN_BACK = "🔙 Back"
BTN_ADMIN_PANEL = "🔧 Admin Panel"
BTN_APPROVE = "✅ Approve"
BTN_REJECT = "❌ Reject"
BTN_DELETE = "🗑 Delete"
BTN_CANCEL = "❌ Cancel"
BTN_CONFIRM = "✅ Confirm"
BTN_NEXT = "⏩ Next"
BTN_PREV = "⏪ Prev"
BTN_ADD_CHANNEL = "➕ Add Channel"
BTN_REMOVE_CHANNEL = "➖ Remove Channel"
BTN_VIEW_CHANNELS = "📋 View Channels"
BTN_ADD_ADMIN = "➕ Add Admin"
BTN_REMOVE_ADMIN = "➖ Remove Admin"
BTN_VIEW_ADMINS = "📋 View Admins"
BTN_BROADCAST_ALL = "📢 All Users"
BTN_BROADCAST_CANCEL = "❌ Cancel Broadcast"
BTN_BLOCK_USER = "🚫 Block User"
BTN_UNBLOCK_USER = "✅ Unblock User"

DB_USERS = "users"
DB_ADMINS = "admins"
DB_REFERRALS = "referrals"
DB_CLAIMS = "claims"
DB_SETTINGS = "settings"
DB_FORCE_JOIN = "force_join"
DB_STATISTICS = "statistics"
DB_LOGS = "logs"
DB_BROADCAST_HISTORY = "broadcast_history"

CLAIM_PENDING = "pending"
CLAIM_APPROVED = "approved"
CLAIM_REJECTED = "rejected"
USER_ACTIVE = "active"
USER_BLOCKED = "blocked"

DEFAULT_SETTINGS = {
    "minimum_referral": 10,
    "referral_reward": 1,
    "claim_reward_name": "Telegram Premium",
    "welcome_message": "",
    "bot_name": "Telegram Premium Referral Bot",
    "maintenance": False,
    "bot_status": True,
    "bot_version": "1.0.0",
}

MSG_ACCESS_DENIED = "🚫 <b>Access Denied</b>\n\nYou don't have permission to use this command."
MSG_MAINTENANCE = "🔧 <b>Bot Under Maintenance</b>\n\nWe're currently performing maintenance.\nPlease try again later. 🙏"
MSG_BLOCKED = "🚫 <b>Account Blocked</b>\n\nYour account has been blocked.\nContact an admin if you believe this is an error."
MSG_BOT_OFF = "🔴 <b>Bot is currently offline</b>\n\nPlease try again later."

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)

def format_datetime(dt_str: Optional[str]) -> str:
    if not dt_str:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M UTC")
    except (ValueError, AttributeError):
        return dt_str

def generate_request_id() -> str:
    return str(uuid.uuid4()).replace("-", "")[:16].upper()

def get_user_display_name(user) -> str:
    name = user.full_name or ""
    return name.strip() if name.strip() else "Unknown User"

def build_referral_link(bot_username: str, user_id: int) -> str:
    clean_username = bot_username.lstrip("@")
    return f"https://t.me/{clean_username}?start={user_id}"

def extract_referrer_id(start_param: str) -> Optional[int]:
    if start_param and start_param.isdigit():
        return int(start_param)
    return None

def sanitize_firebase_key(text: str) -> str:
    for ch in [".", "$", "#", "[", "]", "/", "@"]:
        text = text.replace(ch, "_")
    return text

def progress_bar(current: int, total: int, length: int = 10) -> str:
    if total == 0:
        return f"{'░' * length} 0/{total}"
    filled = min(int((current / total) * length), length)
    return f"{'█' * filled}{'░' * (length - filled)} {current}/{total}"

def format_number(n: int) -> str:
    return f"{n:,}"

# ══════════════════════════════════════════════════════════════════════════════
# FIREBASE
# ══════════════════════════════════════════════════════════════════════════════

_firebase_initialized = False

def initialize_firebase() -> None:
    global _firebase_initialized
    if _firebase_initialized or firebase_admin._apps:
        _firebase_initialized = True
        return
    if not config.FIREBASE_DATABASE_URL:
        raise ValueError("FIREBASE_DATABASE_URL is required but not set.")
    cred_obj = None
    cred_path = config.FIREBASE_CREDENTIALS_PATH
    if cred_path and os.path.isfile(cred_path):
        try:
            cred_obj = credentials.Certificate(cred_path)
            logger.info("Firebase credentials loaded from file: %s", cred_path)
        except Exception as e:
            logger.error("Failed to load Firebase credentials from file: %s", e)
            raise
    if cred_obj is None:
        raw_json = os.getenv("FIREBASE_CREDENTIALS_JSON", "")
        if raw_json:
            try:
                cred_dict = json.loads(raw_json)
                cred_obj = credentials.Certificate(cred_dict)
                logger.info("Firebase credentials loaded from FIREBASE_CREDENTIALS_JSON env var.")
            except Exception as e:
                logger.error("Failed to parse FIREBASE_CREDENTIALS_JSON: %s", e)
                raise
    if cred_obj is None:
        raise ValueError("No Firebase credentials found. Set FIREBASE_CREDENTIALS_PATH or FIREBASE_CREDENTIALS_JSON.")
    firebase_admin.initialize_app(cred_obj, {"databaseURL": config.FIREBASE_DATABASE_URL})
    _firebase_initialized = True
    logger.info("Firebase initialized. Database URL: %s", config.FIREBASE_DATABASE_URL)

def get_ref(path: str):
    return firebase_db.reference(path)

def fb_get(path: str) -> Any:
    try:
        return firebase_db.reference(path).get()
    except Exception as e:
        logger.error("Firebase GET error [%s]: %s", path, e)
        return None

def fb_set(path: str, value: Any) -> bool:
    try:
        firebase_db.reference(path).set(value)
        return True
    except Exception as e:
        logger.error("Firebase SET error [%s]: %s", path, e)
        return False

def fb_update(path: str, data: Dict[str, Any]) -> bool:
    try:
        firebase_db.reference(path).update(data)
        return True
    except Exception as e:
        logger.error("Firebase UPDATE error [%s]: %s", path, e)
        return False

def fb_push(path: str, value: Any) -> Optional[str]:
    try:
        ref = firebase_db.reference(path).push(value)
        return ref.key
    except Exception as e:
        logger.error("Firebase PUSH error [%s]: %s", path, e)
        return None

def fb_delete(path: str) -> bool:
    try:
        firebase_db.reference(path).delete()
        return True
    except Exception as e:
        logger.error("Firebase DELETE error [%s]: %s", path, e)
        return False

def fb_transaction(path: str, update_fn) -> bool:
    try:
        firebase_db.reference(path).transaction(update_fn)
        return True
    except Exception as e:
        logger.error("Firebase TRANSACTION error [%s]: %s", path, e)
        return False

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

_user_cache: TTLCache = TTLCache(maxsize=1000, ttl=config.CACHE_USER_TTL)
_settings_cache: TTLCache = TTLCache(maxsize=1, ttl=config.CACHE_SETTINGS_TTL)
_channels_cache: TTLCache = TTLCache(maxsize=1, ttl=config.CACHE_CHANNELS_TTL)
_admins_cache: TTLCache = TTLCache(maxsize=1, ttl=60)
_user_locks: Dict[int, asyncio.Lock] = {}

def _get_user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]

async def get_settings() -> Dict[str, Any]:
    if "settings" in _settings_cache:
        return _settings_cache["settings"]
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, DB_SETTINGS)
    if not data:
        await loop.run_in_executor(None, fb_set, DB_SETTINGS, DEFAULT_SETTINGS)
        data = dict(DEFAULT_SETTINGS)
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    _settings_cache["settings"] = merged
    return merged

async def update_settings(updates: Dict[str, Any]) -> bool:
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, fb_update, DB_SETTINGS, updates)
    if ok:
        _settings_cache.pop("settings", None)
    return ok

async def get_all_admin_ids() -> List[int]:
    if "admins" in _admins_cache:
        return _admins_cache["admins"]
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, DB_ADMINS)
    ids: List[int] = list(config.get_initial_admin_ids())
    if data and isinstance(data, dict):
        for uid_str in data.keys():
            try:
                uid = int(uid_str)
                if uid not in ids:
                    ids.append(uid)
            except ValueError:
                pass
    _admins_cache["admins"] = ids
    return ids

async def is_admin(user_id: int) -> bool:
    admins = await get_all_admin_ids()
    return user_id in admins

async def add_admin(user_id: int, added_by: int) -> bool:
    loop = asyncio.get_event_loop()
    now = get_utc_now().isoformat()
    ok = await loop.run_in_executor(None, fb_set, f"{DB_ADMINS}/{user_id}", {"added_by": added_by, "added_at": now})
    if ok:
        _admins_cache.pop("admins", None)
        await _log_action("admin_added", {"target_id": user_id, "by": added_by})
    return ok

async def remove_admin(user_id: int, removed_by: int) -> bool:
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, fb_delete, f"{DB_ADMINS}/{user_id}")
    if ok:
        _admins_cache.pop("admins", None)
        await _log_action("admin_removed", {"target_id": user_id, "by": removed_by})
    return ok

async def get_admins_data() -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, DB_ADMINS)
    return data or {}

async def get_force_join_channels() -> List[Dict[str, Any]]:
    if "channels" in _channels_cache:
        return _channels_cache["channels"]
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, DB_FORCE_JOIN)
    channels: List[Dict[str, Any]] = []
    if data and isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, dict):
                val["_key"] = key
                channels.append(val)
    _channels_cache["channels"] = channels
    return channels

async def get_all_force_join_channels() -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, DB_FORCE_JOIN)
    channels: List[Dict[str, Any]] = []
    if data and isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, dict):
                val["_key"] = key
                channels.append(val)
    return channels

async def add_force_join_channel(channel_id: str, channel_username: str, invite_link: str, added_by: int) -> bool:
    loop = asyncio.get_event_loop()
    now = get_utc_now().isoformat()
    safe_key = sanitize_firebase_key(channel_id.lstrip("-"))
    data = {"channel_id": channel_id, "channel_username": channel_username, "invite_link": invite_link, "status": True, "added_date": now, "added_by": added_by}
    ok = await loop.run_in_executor(None, fb_set, f"{DB_FORCE_JOIN}/{safe_key}", data)
    if ok:
        _channels_cache.pop("channels", None)
        await _log_action("channel_added", {"channel_id": channel_id, "by": added_by})
    return ok

async def remove_force_join_channel(channel_key: str) -> bool:
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, fb_delete, f"{DB_FORCE_JOIN}/{channel_key}")
    if ok:
        _channels_cache.pop("channels", None)
    return ok

async def toggle_force_join_channel(channel_key: str, enabled: bool) -> bool:
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, fb_update, f"{DB_FORCE_JOIN}/{channel_key}", {"status": enabled})
    if ok:
        _channels_cache.pop("channels", None)
    return ok

def _build_user_path(user_id: int) -> str:
    return f"{DB_USERS}/{user_id}"

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    cache_key = f"user_{user_id}"
    if cache_key in _user_cache:
        return _user_cache[cache_key]
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, _build_user_path(user_id))
    if data:
        _user_cache[cache_key] = data
    return data

async def user_exists(user_id: int) -> bool:
    return await get_user(user_id) is not None

async def create_user(user_id: int, username: Optional[str], full_name: str) -> Dict[str, Any]:
    now = get_utc_now().isoformat()
    user_data: Dict[str, Any] = {
        "user_id": user_id, "username": username or "", "full_name": full_name,
        "join_date": now, "last_active": now, "referral_count": 0, "referral_points": 0,
        "claim_count": 0, "total_claims": 0, "status": USER_ACTIVE, "blocked": False,
        "language": "en", "premium_claim_history_count": 0,
    }
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, fb_set, _build_user_path(user_id), user_data)
    _user_cache[f"user_{user_id}"] = user_data
    await _increment_stat("total_users", 1)
    today_key = get_utc_now().strftime("%Y-%m-%d")
    await _increment_stat(f"daily_users/{today_key}", 1)
    await _log_action("user_joined", {"user_id": user_id, "name": full_name})
    logger.info("New user registered: %s (%s)", full_name, user_id)
    return user_data

async def update_user_profile(user_id: int, username: Optional[str], full_name: str) -> None:
    loop = asyncio.get_event_loop()
    updates = {"username": username or "", "full_name": full_name, "last_active": get_utc_now().isoformat()}
    await loop.run_in_executor(None, fb_update, _build_user_path(user_id), updates)
    _user_cache.pop(f"user_{user_id}", None)

async def update_user_last_active(user_id: int) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, fb_update, _build_user_path(user_id), {"last_active": get_utc_now().isoformat()})
    _user_cache.pop(f"user_{user_id}", None)

async def block_user(user_id: int, blocked_by: int) -> bool:
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, fb_update, _build_user_path(user_id), {"blocked": True, "status": USER_BLOCKED})
    if ok:
        _user_cache.pop(f"user_{user_id}", None)
        await _log_action("user_blocked", {"user_id": user_id, "by": blocked_by})
    return ok

async def unblock_user(user_id: int, unblocked_by: int) -> bool:
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, fb_update, _build_user_path(user_id), {"blocked": False, "status": USER_ACTIVE})
    if ok:
        _user_cache.pop(f"user_{user_id}", None)
        await _log_action("user_unblocked", {"user_id": user_id, "by": unblocked_by})
    return ok

async def get_all_user_ids() -> List[int]:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, DB_USERS)
    if not data or not isinstance(data, dict):
        return []
    return [int(uid) for uid in data.keys()]

async def get_user_count() -> int:
    return len(await get_all_user_ids())

async def save_pending_referral(invitee_id: int, referrer_id: int) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, fb_set, f"pending_referrals/{invitee_id}", {"referrer_id": referrer_id, "ts": get_utc_now().isoformat()})

async def pop_pending_referral(invitee_id: int) -> Optional[int]:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, f"pending_referrals/{invitee_id}")
    if not data or not isinstance(data, dict):
        return None
    await loop.run_in_executor(None, fb_delete, f"pending_referrals/{invitee_id}")
    try:
        return int(data["referrer_id"])
    except (KeyError, ValueError, TypeError):
        return None

async def referral_exists(inviter_id: int, invitee_id: int) -> bool:
    loop = asyncio.get_event_loop()
    val = await loop.run_in_executor(None, fb_get, f"{DB_REFERRALS}/{inviter_id}/{invitee_id}")
    return val is not None

async def record_referral(inviter_id: int, invitee_id: int) -> bool:
    if await referral_exists(inviter_id, invitee_id):
        logger.warning("Duplicate referral blocked: inviter=%s invitee=%s", inviter_id, invitee_id)
        return False
    loop = asyncio.get_event_loop()
    now = get_utc_now().isoformat()
    # Step 1: save the referral record (used for deduplication)
    ok = await loop.run_in_executor(None, fb_set, f"{DB_REFERRALS}/{inviter_id}/{invitee_id}", {"invitee_id": invitee_id, "date": now})
    if not ok:
        return False
    settings = await get_settings()
    reward = int(settings.get("referral_reward", 1))
    # Step 2: atomically increment referrer's counters
    ok = await loop.run_in_executor(None, _atomic_increment_referral, inviter_id, reward)
    if ok:
        _user_cache.pop(f"user_{inviter_id}", None)
        await _increment_stat("total_referrals", 1)
        await _log_action("referral_success", {"inviter": inviter_id, "invitee": invitee_id, "reward": reward})
        logger.info("Referral recorded: inviter=%s invitee=%s reward=%s", inviter_id, invitee_id, reward)
    else:
        # Step 2 failed — rollback Step 1 so this referral can be retried later.
        # Without rollback, referral_exists() would always return True for this pair
        # and the referrer would permanently lose their point.
        await loop.run_in_executor(None, fb_delete, f"{DB_REFERRALS}/{inviter_id}/{invitee_id}")
        logger.error(
            "Referral point increment failed for inviter=%s invitee=%s — rolled back referral record so it can be retried",
            inviter_id, invitee_id,
        )
    return ok

def _atomic_increment_referral(user_id: int, reward: int) -> bool:
    try:
        ref = firebase_db.reference(f"{DB_USERS}/{user_id}")
        aborted = [False]
        def updater(current):
            if current is None:
                # User not found in DB — abort transaction safely
                aborted[0] = True
                return None
            current["referral_count"] = int(current.get("referral_count", 0)) + 1
            current["referral_points"] = int(current.get("referral_points", 0)) + reward
            return current
        ref.transaction(updater)
        if aborted[0]:
            logger.error("Referral transaction aborted: user %s not found in DB at time of update", user_id)
            return False
        return True
    except Exception as e:
        logger.error("Atomic referral increment failed for %s: %s", user_id, e)
        return False

async def has_pending_claim(user_id: int) -> bool:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, DB_CLAIMS)
    if not data or not isinstance(data, dict):
        return False
    for claim in data.values():
        if isinstance(claim, dict) and int(claim.get("user_id", 0)) == user_id and claim.get("status") == CLAIM_PENDING:
            return True
    return False

def _atomic_reset_and_increment_claims(user_id: int) -> bool:
    """Atomically reset referral counters and increment total_claims after a claim is submitted."""
    try:
        ref = firebase_db.reference(f"{DB_USERS}/{user_id}")
        def updater(current):
            if current is None:
                return None
            current["referral_count"] = 0
            current["referral_points"] = 0
            current["total_claims"] = int(current.get("total_claims", 0)) + 1
            return current
        ref.transaction(updater)
        return True
    except Exception as e:
        logger.error("Claim reset/increment failed for %s: %s", user_id, e)
        return False

async def create_claim_request(user_id: int, username: Optional[str], full_name: str, points_used: int) -> Optional[str]:
    if await has_pending_claim(user_id):
        logger.warning("Duplicate claim attempt blocked for user %s", user_id)
        return None
    loop = asyncio.get_event_loop()
    now = get_utc_now()
    request_id = generate_request_id()
    claim_data = {
        "request_id": request_id, "user_id": user_id, "username": username or "", "full_name": full_name,
        "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S UTC"), "timestamp": now.isoformat(),
        "points_used": points_used, "status": CLAIM_PENDING,
    }
    ok = await loop.run_in_executor(None, fb_set, f"{DB_CLAIMS}/{request_id}", claim_data)
    if not ok:
        return None
    # Atomically reset referral counters and increment total_claims
    await loop.run_in_executor(None, _atomic_reset_and_increment_claims, user_id)
    _user_cache.pop(f"user_{user_id}", None)
    await _increment_stat("claims/pending", 1)
    await _increment_stat("claims/total", 1)
    await _log_action("claim_created", {"user_id": user_id, "request_id": request_id})
    logger.info("Claim request created: %s for user %s", request_id, user_id)
    return request_id

async def get_pending_claims() -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, DB_CLAIMS)
    if not data or not isinstance(data, dict):
        return []
    return [v for v in data.values() if isinstance(v, dict) and v.get("status") == CLAIM_PENDING]

async def get_all_claims() -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, DB_CLAIMS)
    if not data or not isinstance(data, dict):
        return []
    claims = [v for v in data.values() if isinstance(v, dict)]
    claims.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return claims

async def update_claim_status(request_id: str, status: str, admin_id: int) -> bool:
    loop = asyncio.get_event_loop()
    now = get_utc_now().isoformat()
    ok = await loop.run_in_executor(None, fb_update, f"{DB_CLAIMS}/{request_id}", {"status": status, "reviewed_by": admin_id, "reviewed_at": now})
    if ok:
        stat_key = "approved" if status == CLAIM_APPROVED else "rejected"
        await _increment_stat(f"claims/{stat_key}", 1)
        await _increment_stat("claims/pending", -1)
        await _log_action(f"claim_{status}", {"request_id": request_id, "by": admin_id})
    return ok

async def delete_claim(request_id: str) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fb_delete, f"{DB_CLAIMS}/{request_id}")

async def get_statistics() -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fb_get, DB_STATISTICS)
    return data or {}

async def get_dashboard_stats() -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    stats_raw, users_raw, claims_raw = await asyncio.gather(
        loop.run_in_executor(None, fb_get, DB_STATISTICS),
        loop.run_in_executor(None, fb_get, DB_USERS),
        loop.run_in_executor(None, fb_get, DB_CLAIMS),
    )
    now = get_utc_now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    daily = (stats_raw or {}).get("daily_users", {})
    today_count = int((daily or {}).get(today, 0))
    yesterday_count = int((daily or {}).get(yesterday, 0))
    weekly = sum(int(v) for k, v in (daily or {}).items() if k >= (now - timedelta(days=7)).strftime("%Y-%m-%d"))
    monthly = sum(int(v) for k, v in (daily or {}).items() if k >= (now - timedelta(days=30)).strftime("%Y-%m-%d"))
    total_users = len(users_raw) if users_raw else 0
    blocked_users = sum(1 for u in (users_raw or {}).values() if isinstance(u, dict) and u.get("blocked"))
    pending = approved = rejected = 0
    if claims_raw and isinstance(claims_raw, dict):
        for c in claims_raw.values():
            if not isinstance(c, dict):
                continue
            s = c.get("status", "")
            if s == CLAIM_PENDING: pending += 1
            elif s == CLAIM_APPROVED: approved += 1
            elif s == CLAIM_REJECTED: rejected += 1
    return {
        "total_users": total_users, "today_users": today_count, "yesterday_users": yesterday_count,
        "weekly_users": weekly, "monthly_users": monthly, "blocked_users": blocked_users,
        "total_referrals": int((stats_raw or {}).get("total_referrals", 0)),
        "claims_pending": pending, "claims_approved": approved, "claims_rejected": rejected,
        "claims_total": pending + approved + rejected,
        "force_join_channels": len(await get_all_force_join_channels()),
    }

async def save_broadcast_record(admin_id: int, total: int, delivered: int, failed: int, blocked: int, message_type: str) -> None:
    loop = asyncio.get_event_loop()
    now = get_utc_now()
    record = {
        "admin_id": admin_id, "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S UTC"),
        "timestamp": now.isoformat(), "total": total, "delivered": delivered, "failed": failed,
        "blocked": blocked, "success_pct": round((delivered / total * 100) if total else 0, 1), "message_type": message_type,
    }
    await loop.run_in_executor(None, fb_push, DB_BROADCAST_HISTORY, record)

async def _log_action(action: str, data: Dict[str, Any]) -> None:
    try:
        loop = asyncio.get_event_loop()
        entry = {"action": action, "timestamp": get_utc_now().isoformat(), **data}
        await loop.run_in_executor(None, fb_push, DB_LOGS, entry)
    except Exception as e:
        logger.error("Log write failed [%s]: %s", action, e)

async def _increment_stat(key: str, delta: int) -> None:
    try:
        loop = asyncio.get_event_loop()
        path = f"{DB_STATISTICS}/{key}"
        def updater(current):
            return max(0, int(current or 0) + delta)
        await loop.run_in_executor(None, get_ref(path).transaction, updater)
    except Exception as e:
        logger.debug("Stat increment failed [%s]: %s", key, e)

# ══════════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════════════════════════════════════

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_PREMIUM)], [KeyboardButton(text=BTN_REFER), KeyboardButton(text=BTN_PROFILE)]],
        resize_keyboard=True, persistent=True,
    )

def claim_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CLAIM)], [KeyboardButton(text=BTN_REFER), KeyboardButton(text=BTN_PROFILE)]],
        resize_keyboard=True, persistent=True,
    )

def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()

def admin_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADMIN_DASHBOARD)],
            [KeyboardButton(text=BTN_ADMIN_REQUESTS), KeyboardButton(text=BTN_ADMIN_BROADCAST)],
            [KeyboardButton(text=BTN_ADMIN_FORCE_JOIN), KeyboardButton(text=BTN_ADMIN_STATISTICS)],
            [KeyboardButton(text=BTN_ADMIN_SETTINGS), KeyboardButton(text=BTN_ADMIN_ADMINS)],
            [KeyboardButton(text=BTN_ADMIN_USERS)],
            [KeyboardButton(text=BTN_ADMIN_BACK)],
        ],
        resize_keyboard=True, persistent=True,
    )

def admin_back_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_ADMIN_BACK)]], resize_keyboard=True, persistent=True)

def admin_force_join_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD_CHANNEL), KeyboardButton(text=BTN_REMOVE_CHANNEL)],
            [KeyboardButton(text=BTN_VIEW_CHANNELS)],
            [KeyboardButton(text=BTN_ADMIN_BACK)],
        ],
        resize_keyboard=True, persistent=True,
    )

def admin_admins_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD_ADMIN), KeyboardButton(text=BTN_REMOVE_ADMIN)],
            [KeyboardButton(text=BTN_VIEW_ADMINS)],
            [KeyboardButton(text=BTN_ADMIN_BACK)],
        ],
        resize_keyboard=True, persistent=True,
    )

def admin_broadcast_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_BROADCAST_ALL)], [KeyboardButton(text=BTN_BROADCAST_CANCEL)], [KeyboardButton(text=BTN_ADMIN_BACK)]],
        resize_keyboard=True, persistent=True,
    )

def admin_confirm_broadcast_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CONFIRM), KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True, one_time_keyboard=True)

def admin_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True, one_time_keyboard=True)

def admin_settings_keyboard(maintenance: bool = False, bot_status: bool = True) -> ReplyKeyboardMarkup:
    maintenance_btn = "✅ Maintenance OFF" if maintenance else "🔧 Maintenance ON"
    bot_btn = "🔴 Bot OFF" if bot_status else "🟢 Bot ON"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔢 Min Referrals"), KeyboardButton(text="⭐ Points Per Refer")],
            [KeyboardButton(text="📝 Welcome Msg"), KeyboardButton(text="🤖 Bot Name")],
            [KeyboardButton(text="🏆 Reward Name")],
            [KeyboardButton(text=maintenance_btn), KeyboardButton(text=bot_btn)],
            [KeyboardButton(text=BTN_ADMIN_BACK)],
        ],
        resize_keyboard=True, persistent=True,
    )

def admin_users_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚫 Block User"), KeyboardButton(text="✅ Unblock User")],
            [KeyboardButton(text="⭐ Edit Points"), KeyboardButton(text="🔍 View User")],
            [KeyboardButton(text=BTN_ADMIN_BACK)],
        ],
        resize_keyboard=True, persistent=True,
    )

async def _settings_keyboard_current() -> ReplyKeyboardMarkup:
    s = await get_settings()
    return admin_settings_keyboard(maintenance=bool(s.get("maintenance", False)), bot_status=bool(s.get("bot_status", True)))

# ══════════════════════════════════════════════════════════════════════════════
# FILTERS
# ══════════════════════════════════════════════════════════════════════════════

class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        user = event.from_user
        if user is None:
            return False
        result = await is_admin(user.id)
        if not result:
            logger.warning("Unauthorized admin access attempt by user_id=%s", user.id)
        return result

MEMBER_STATUSES = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}

async def check_user_joined_channel(bot: Bot, user_id: int, channel_id: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in MEMBER_STATUSES
    except Exception as e:
        logger.debug("Could not check membership for user=%s channel=%s: %s", user_id, channel_id, e)
        return False

async def get_unjoined_channels(bot: Bot, user_id: int) -> List[Dict[str, Any]]:
    channels = await get_force_join_channels()
    enabled = [ch for ch in channels if ch.get("status", True)]
    unjoined: List[Dict[str, Any]] = []
    for ch in enabled:
        cid = ch.get("channel_id", "")
        if not cid:
            continue
        if not await check_user_joined_channel(bot, user_id, cid):
            unjoined.append(ch)
    return unjoined

# ══════════════════════════════════════════════════════════════════════════════
# MIDDLEWARES
# ══════════════════════════════════════════════════════════════════════════════

_last_seen: TTLCache = TTLCache(maxsize=10_000, ttl=max(config.THROTTLE_RATE * 10, 10))
THROTTLE_WARN_AFTER = 5

class ThrottlingMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: Dict[str, Any]) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        message: Message = event
        user = message.from_user
        if user is None:
            return await handler(event, data)
        user_id = user.id
        now = time.monotonic()
        last_time, drop_count = _last_seen.get(user_id, (0.0, 0))
        elapsed = now - last_time
        if elapsed < config.THROTTLE_RATE:
            drop_count += 1
            _last_seen[user_id] = (last_time, drop_count)
            if drop_count == THROTTLE_WARN_AFTER:
                try:
                    await message.answer("⚠️ <b>Slow down!</b>\n\nYou're sending messages too fast. Please wait a moment.", parse_mode="HTML")
                except Exception:
                    pass
            return None
        _last_seen[user_id] = (now, 0)
        return await handler(event, data)

class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: Dict[str, Any]) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        message: Message = event
        user = message.from_user
        if user is None:
            return await handler(event, data)
        user_id = user.id
        try:
            settings = await get_settings()
            if not settings.get("bot_status", True):
                if not await is_admin(user_id):
                    await message.answer(MSG_BOT_OFF)
                    return None
            if settings.get("maintenance", False):
                if not await is_admin(user_id):
                    await message.answer(MSG_MAINTENANCE)
                    return None
            db_user = await get_user(user_id)
            if db_user and db_user.get("blocked", False):
                await message.answer(MSG_BLOCKED)
                return None
        except Exception as e:
            logger.error("AuthMiddleware error for user %s: %s", user_id, e)
        return await handler(event, data)

# ══════════════════════════════════════════════════════════════════════════════
# ROUTERS / HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

# ── Start Handler ─────────────────────────────────────────────────────────────
start_router = Router(name="start")

async def send_force_join_message(message: Message, unjoined: list) -> None:
    lines = ["🔒 <b>Join Required Channels</b>\n\nYou must join all channels below before using this bot.\n"]
    buttons = []
    for i, ch in enumerate(unjoined, 1):
        username = ch.get("channel_username", "")
        invite = ch.get("invite_link", "")
        name = f"📢 @{username}" if username else f"📢 Channel {i}"
        link = invite or (f"https://t.me/{username}" if username else "")
        if link:
            buttons.append([InlineKeyboardButton(text=name, url=link)])
    buttons.append([InlineKeyboardButton(text="✅ I've Joined — Check", callback_data="check_join")])
    await message.answer("".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

async def _process_referral(referrer_id: int, invitee_id: int, bot: Bot) -> None:
    if referrer_id == invitee_id:
        return
    referrer = await get_user(referrer_id)
    if not referrer:
        return
    if await referral_exists(referrer_id, invitee_id):
        return
    success = await record_referral(referrer_id, invitee_id)
    if success:
        try:
            settings = await get_settings()
            reward = int(settings.get("referral_reward", 1))
            point_word = "Points" if reward != 1 else "Point"
            await bot.send_message(
                chat_id=referrer_id,
                text=f"🎉 <b>New Referral!</b>\n\nSomeone joined using your referral link!\n\n<b>+{reward} {point_word} added to your account.</b> 🌟\n\nKeep sharing to earn more points!",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.debug("Could not notify referrer %s: %s", referrer_id, e)

@start_router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, command: CommandObject) -> None:
    user = message.from_user
    if not user:
        return
    user_id = user.id
    full_name = get_user_display_name(user)
    username = user.username
    unjoined = await get_unjoined_channels(bot, user_id)
    if unjoined:
        start_param_early = command.args or ""
        referrer_id_early = extract_referrer_id(start_param_early)
        if referrer_id_early and referrer_id_early != user_id:
            await save_pending_referral(user_id, referrer_id_early)
        await send_force_join_message(message, unjoined)
        return
    is_new_user = not await user_exists(user_id)
    if is_new_user:
        await create_user(user_id, username, full_name)
    else:
        await update_user_profile(user_id, username, full_name)
    start_param = command.args or ""
    referrer_id = extract_referrer_id(start_param)
    if referrer_id and is_new_user:
        await _process_referral(referrer_id, user_id, bot)
    admin = await is_admin(user_id)
    settings = await get_settings()
    custom_welcome = settings.get("welcome_message", "")
    bot_name = settings.get("bot_name", "Telegram Premium Referral Bot")
    if custom_welcome:
        text = custom_welcome.replace("{name}", full_name)
    else:
        greeting = "Welcome back" if not is_new_user else "Welcome"
        text = (
            f"👋 <b>{greeting}, {full_name}!</b>\n\n🌟 <b>{bot_name}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n📌 <b>How It Works:</b>\n"
            f"  • Invite friends using your referral link\n"
            f"  • Every successful referral = <b>+1 Point</b>\n"
            f"  • Collect <b>10 Points</b> to claim <b>Telegram Premium</b>\n\n"
            f"🚀 Start sharing your link now!\n━━━━━━━━━━━━━━━━━━━"
        )
    if admin:
        text += f"\n\n🔧 <b>Admin:</b> Send <code>/admin</code> to open Admin Panel."
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
    logger.info("User %s (%s) started bot. New=%s", full_name, user_id, is_new_user)

# ── User Handler ──────────────────────────────────────────────────────────────
user_router = Router(name="user")

@user_router.message(F.text == BTN_PROFILE)
async def show_profile(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    db_user = await get_user(user.id)
    if not db_user:
        await message.answer("⚠️ Profile not found. Please send /start to register.", parse_mode="HTML")
        return
    settings = await get_settings()
    min_ref = int(settings.get("minimum_referral", 10))
    name = db_user.get("full_name", "Unknown")
    username = db_user.get("username", "")
    user_id = db_user.get("user_id", user.id)
    join_date = format_datetime(db_user.get("join_date"))
    referral_count = int(db_user.get("referral_count", 0))
    points = int(db_user.get("referral_points", 0))
    total_claims = int(db_user.get("total_claims", 0))
    username_display = f"@{username}" if username else "Not set"
    progress = progress_bar(points, min_ref, length=10)
    text = (
        f"👤 <b>Your Profile</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"📛 <b>Name:</b>  {name}\n🔖 <b>Username:</b>  {username_display}\n"
        f"🆔 <b>User ID:</b>  <code>{user_id}</code>\n📅 <b>Joined:</b>  {join_date}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n👥 <b>Total Invited:</b>  {referral_count}\n"
        f"⭐ <b>Points:</b>  {points} / {min_ref}\n📊 <b>Progress:</b>  {progress}\n"
        f"🎁 <b>Total Claims:</b>  {total_claims}\n━━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard())

@user_router.callback_query(F.data == "check_join")
async def callback_check_join(callback: CallbackQuery, bot: Bot) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    await callback.answer("🔍 Checking your membership...", show_alert=False)
    unjoined = await get_unjoined_channels(bot, user.id)
    if unjoined:
        channel_names = [f"@{ch.get('channel_username', '')}" if ch.get("channel_username") else "a required channel" for ch in unjoined]
        names_str = "\n".join(f"  • {n}" for n in channel_names)
        try:
            await callback.message.answer(f"❌ <b>You haven't joined all channels yet!</b>\n\nStill missing:\n{names_str}\n\nPlease join them and try again.", parse_mode="HTML")
        except Exception:
            pass
        return
    is_new = not await get_user(user.id)
    full_name = get_user_display_name(user)
    if is_new:
        await create_user(user.id, user.username, full_name)
    else:
        await update_user_profile(user.id, user.username, full_name)
    referrer_id = await pop_pending_referral(user.id)
    if referrer_id and is_new:
        await _process_referral(referrer_id, user.id, bot)
    try:
        await callback.message.answer(f"✅ <b>All channels joined!</b>\n\nWelcome, {full_name}! You can now use the bot. 🎉", parse_mode="HTML", reply_markup=main_menu_keyboard())
        await callback.message.delete()
    except Exception as e:
        logger.debug("Could not edit force-join message: %s", e)

# ── Referral Handler ──────────────────────────────────────────────────────────
referral_router = Router(name="referral")

@referral_router.message(F.text == BTN_REFER)
async def show_referral(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    db_user = await get_user(user.id)
    if not db_user:
        await message.answer("⚠️ Please send /start first.", parse_mode="HTML")
        return
    settings = await get_settings()
    min_ref = int(settings.get("minimum_referral", 10))
    reward_name = settings.get("claim_reward_name", "Telegram Premium")
    points = int(db_user.get("referral_points", 0))
    referral_count = int(db_user.get("referral_count", 0))
    remaining = max(0, min_ref - points)
    referral_link = build_referral_link(config.BOT_USERNAME, user.id)
    bar = progress_bar(points, min_ref, length=12)
    text = (
        f"👥 <b>Your Referral Dashboard</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 <b>Your Referral Link:</b>\n<code>{referral_link}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n⭐ <b>Current Points:</b>  {points}\n"
        f"👥 <b>Total Referrals:</b>  {referral_count}\n🏆 <b>Goal:</b>  {min_ref} points\n"
        f"⏳ <b>Remaining:</b>  {remaining} more\n\n📊 <b>Progress:</b>\n  {bar}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n💡 <b>How to earn:</b>\n"
        f"  • Share your link with friends\n  • Every new user who joins = <b>+1 Point</b>\n"
        f"  • Reach <b>{min_ref} points</b> to claim <b>{reward_name}</b>! 🎁"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard(), disable_web_page_preview=True)

# ── Premium Handler ────────────────────────────────────────────────────────────
premium_router = Router(name="premium")

@premium_router.message(F.text == BTN_PREMIUM)
async def show_premium(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    db_user = await get_user(user.id)
    if not db_user:
        await message.answer("⚠️ Please send /start first.", parse_mode="HTML")
        return
    settings = await get_settings()
    min_ref = int(settings.get("minimum_referral", 10))
    reward_name = settings.get("claim_reward_name", "Telegram Premium")
    points = int(db_user.get("referral_points", 0))
    remaining = max(0, min_ref - points)
    bar = progress_bar(points, min_ref, length=12)
    if points >= min_ref:
        text = (
            f"🎉 <b>Congratulations!</b>\n\nYou have enough points to claim <b>{reward_name}</b>!\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n⭐ <b>Your Points:</b>  {points} / {min_ref}\n"
            f"📊 <b>Progress:</b>  {bar}\n━━━━━━━━━━━━━━━━━━━\n\n👇 Press the button below to submit your claim!"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=claim_keyboard())
    else:
        referral_link = build_referral_link(config.BOT_USERNAME, user.id)
        text = (
            f"⭐ <b>Telegram Premium</b>\n\nInvite friends to earn points and claim Premium for free!\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n⭐ <b>Your Points:</b>  {points}\n"
            f"🏆 <b>Required:</b>  {min_ref}\n⏳ <b>Still Need:</b>  {remaining} more\n\n"
            f"📊 <b>Progress:</b>\n  {bar}\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Your Link:</b>\n<code>{referral_link}</code>"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard(), disable_web_page_preview=True)

@premium_router.message(F.text == BTN_CLAIM)
async def process_claim(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    db_user = await get_user(user.id)
    if not db_user:
        await message.answer("⚠️ Please send /start first.", parse_mode="HTML")
        return
    settings = await get_settings()
    min_ref = int(settings.get("minimum_referral", 10))
    reward_name = settings.get("claim_reward_name", "Telegram Premium")
    points = int(db_user.get("referral_points", 0))
    if points < min_ref:
        remaining = min_ref - points
        await message.answer(f"❌ <b>Not enough points!</b>\n\n⭐ <b>You have:</b>  {points} points\n🏆 <b>Required:</b>  {min_ref} points\n⏳ <b>Need:</b>  {remaining} more\n\nKeep inviting friends to earn more points! 💪", parse_mode="HTML", reply_markup=main_menu_keyboard())
        return
    if await has_pending_claim(user.id):
        await message.answer(f"⏳ <b>Request Already Submitted</b>\n\nYour claim for <b>{reward_name}</b> has been submitted.\nPlease continue inviting friends while we process it! 🙌", parse_mode="HTML", reply_markup=main_menu_keyboard())
        return
    request_id = await create_claim_request(user_id=user.id, username=user.username, full_name=db_user.get("full_name", user.full_name or ""), points_used=points)
    if not request_id:
        await message.answer("⚠️ Something went wrong. Please try again later.", parse_mode="HTML", reply_markup=main_menu_keyboard())
        return
    await message.answer(
        f"✅ <b>Claim Submitted Successfully!</b>\n\n🎁 Your request for <b>{reward_name}</b> has been received.\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n💡 <b>What's next?</b>\n  • Your points have been reset to 0\n"
        f"  • Start inviting again to earn more!\n━━━━━━━━━━━━━━━━━━━\n\nThank you for using our bot! 🙏",
        parse_mode="HTML", reply_markup=main_menu_keyboard(),
    )

# ── Admin Dashboard ────────────────────────────────────────────────────────────
admin_dashboard_router = Router(name="admin_dashboard")
_BOT_START_TIME = time.time()

def _format_uptime() -> str:
    elapsed = int(time.time() - _BOT_START_TIME)
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts) or "0s"

@admin_dashboard_router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    if not await is_admin(user.id):
        await message.answer(MSG_ACCESS_DENIED, parse_mode="HTML")
        return
    await message.answer("🔧 <b>Admin Panel</b>\n\nWelcome to the admin panel. Select an option:", parse_mode="HTML", reply_markup=admin_main_keyboard())

@admin_dashboard_router.message(IsAdmin(), F.text == BTN_ADMIN_DASHBOARD)
async def show_dashboard(message: Message) -> None:
    await message.answer("🔍 Loading dashboard...", parse_mode="HTML")
    try:
        stats = await get_dashboard_stats()
        settings = await get_settings()
        uptime = _format_uptime()
        maintenance = "🔴 ON" if settings.get("maintenance") else "🟢 OFF"
        bot_status = "🟢 Online" if settings.get("bot_status", True) else "🔴 Offline"
        text = (
            f"📊 <b>Admin Dashboard</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 <b>Users</b>\n  📌 Total:      {stats['total_users']:,}\n  📅 Today:      {stats['today_users']:,}\n"
            f"  📆 Yesterday:  {stats['yesterday_users']:,}\n  🗓 Weekly:     {stats['weekly_users']:,}\n"
            f"  🗓 Monthly:    {stats['monthly_users']:,}\n  🚫 Blocked:    {stats['blocked_users']:,}\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n🔗 <b>Referrals</b>\n  ⭐ Total:      {stats['total_referrals']:,}\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n🎁 <b>Claims</b>\n  ⏳ Pending:    {stats['claims_pending']:,}\n"
            f"  ✅ Approved:   {stats['claims_approved']:,}\n  ❌ Rejected:   {stats['claims_rejected']:,}\n"
            f"  📦 Total:      {stats['claims_total']:,}\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n⚙️ <b>System</b>\n  📌 Channels:   {stats['force_join_channels']}\n"
            f"  🔧 Maintenance:{maintenance}\n  🤖 Bot Status: {bot_status}\n"
            f"  ⏱ Uptime:     {uptime}\n  🗄 Database:   ✅ Connected\n━━━━━━━━━━━━━━━━━━━"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=admin_main_keyboard())
    except Exception as e:
        logger.error("Dashboard error: %s", e)
        await message.answer("⚠️ Failed to load dashboard. Please try again.", parse_mode="HTML")

@admin_dashboard_router.message(IsAdmin(), F.text == BTN_ADMIN_BACK)
async def admin_back(message: Message) -> None:
    await message.answer("🔙 Returned to main menu.", parse_mode="HTML", reply_markup=main_menu_keyboard())

# ── Admin Requests ─────────────────────────────────────────────────────────────
admin_requests_router = Router(name="admin_requests")

def _format_claim_card(claim: dict, index: int, total: int) -> str:
    return (
        f"🎁 <b>Claim Request {index}/{total}</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 <b>Request ID:</b>  <code>{claim.get('request_id', 'N/A')}</code>\n"
        f"👤 <b>Name:</b>  {claim.get('full_name', 'Unknown')}\n"
        f"🔖 <b>Username:</b>  {'@' + claim['username'] if claim.get('username') else 'N/A'}\n"
        f"🪪 <b>User ID:</b>  <code>{claim.get('user_id', 'N/A')}</code>\n"
        f"📅 <b>Date:</b>  {claim.get('date', 'N/A')} {claim.get('time', '')}\n"
        f"⭐ <b>Points Used:</b>  {claim.get('points_used', 0)}\n━━━━━━━━━━━━━━━━━━━"
    )

def _request_action_keyboard(request_id: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=f"✅ Approve:{request_id}"), KeyboardButton(text=f"❌ Reject:{request_id}")], [KeyboardButton(text=f"🗑 Delete:{request_id}")], [KeyboardButton(text=BTN_ADMIN_BACK)]],
        resize_keyboard=True, one_time_keyboard=False,
    )

@admin_requests_router.message(IsAdmin(), F.text == BTN_ADMIN_REQUESTS)
async def show_requests(message: Message) -> None:
    pending = await get_pending_claims()
    if not pending:
        await message.answer("📭 <b>No Pending Requests</b>\n\nThere are no pending Premium claims.", parse_mode="HTML", reply_markup=admin_main_keyboard())
        return
    pending.sort(key=lambda x: x.get("timestamp", ""))
    await message.answer(f"📋 <b>Pending Requests: {len(pending)}</b>\n\nUse the action buttons below each request.\n━━━━━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=admin_main_keyboard())
    for i, claim in enumerate(pending, 1):
        await message.answer(_format_claim_card(claim, i, len(pending)), parse_mode="HTML", reply_markup=_request_action_keyboard(claim.get("request_id", "")))

@admin_requests_router.message(IsAdmin(), F.text.startswith("✅ Approve:"))
async def approve_request(message: Message, bot: Bot) -> None:
    request_id = message.text.split(":", 1)[1].strip()
    ok = await update_claim_status(request_id, CLAIM_APPROVED, message.from_user.id)
    if ok:
        await message.answer(f"✅ <b>Request Approved</b>\n\nRequest <code>{request_id}</code> has been approved.", parse_mode="HTML", reply_markup=admin_main_keyboard())
    else:
        await message.answer("⚠️ Failed to approve request. It may have already been processed.", parse_mode="HTML")

@admin_requests_router.message(IsAdmin(), F.text.startswith("❌ Reject:"))
async def reject_request(message: Message) -> None:
    request_id = message.text.split(":", 1)[1].strip()
    ok = await update_claim_status(request_id, CLAIM_REJECTED, message.from_user.id)
    if ok:
        await message.answer(f"❌ <b>Request Rejected</b>\n\nRequest <code>{request_id}</code> has been rejected.", parse_mode="HTML", reply_markup=admin_main_keyboard())
    else:
        await message.answer("⚠️ Failed to reject request.", parse_mode="HTML")

@admin_requests_router.message(IsAdmin(), F.text.startswith("🗑 Delete:"))
async def delete_request(message: Message) -> None:
    request_id = message.text.split(":", 1)[1].strip()
    ok = await delete_claim(request_id)
    if ok:
        await message.answer(f"🗑 <b>Request Deleted</b>\n\nRequest <code>{request_id}</code> has been deleted.", parse_mode="HTML", reply_markup=admin_main_keyboard())
    else:
        await message.answer("⚠️ Failed to delete request.", parse_mode="HTML")

# ── Admin Broadcast ────────────────────────────────────────────────────────────
admin_broadcast_router = Router(name="admin_broadcast")

class BroadcastState(StatesGroup):
    waiting_for_message = State()
    confirming = State()

SUPPORTED_CONTENT_TYPES = {ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.ANIMATION, ContentType.STICKER, ContentType.VOICE, ContentType.DOCUMENT, ContentType.AUDIO}

@admin_broadcast_router.message(IsAdmin(), F.text == BTN_ADMIN_BROADCAST)
async def broadcast_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("📢 <b>Broadcast Panel</b>\n\nSend messages to all users at once.\n\nChoose target audience:", parse_mode="HTML", reply_markup=admin_broadcast_keyboard())

@admin_broadcast_router.message(IsAdmin(), F.text == BTN_BROADCAST_ALL)
async def start_broadcast_all(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastState.waiting_for_message)
    await state.update_data(target="all")
    await message.answer("📝 <b>Send Your Broadcast Message</b>\n\nForward or send any message to broadcast.\nSupported: Text, Photo, Video, GIF, Sticker, Voice, Document, Audio\n\nPress ❌ Cancel to abort.", parse_mode="HTML", reply_markup=admin_cancel_keyboard())

@admin_broadcast_router.message(IsAdmin(), BroadcastState.waiting_for_message)
async def receive_broadcast_message(message: Message, state: FSMContext) -> None:
    if message.text in (BTN_CANCEL, BTN_BROADCAST_CANCEL):
        await state.clear()
        await message.answer("❌ Broadcast cancelled.", parse_mode="HTML", reply_markup=admin_main_keyboard())
        return
    if message.content_type not in SUPPORTED_CONTENT_TYPES:
        await message.answer("⚠️ Unsupported content type.", parse_mode="HTML")
        return
    await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id, content_type=message.content_type)
    await state.set_state(BroadcastState.confirming)
    user_ids = await get_all_user_ids()
    await message.answer(f"📋 <b>Broadcast Preview Received</b>\n\n👥 <b>Recipients:</b>  {len(user_ids):,} users\n📄 <b>Type:</b>  {message.content_type}\n\nAre you sure?", parse_mode="HTML", reply_markup=admin_confirm_broadcast_keyboard())

@admin_broadcast_router.message(IsAdmin(), BroadcastState.confirming, F.text == BTN_CONFIRM)
async def confirm_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    from_chat_id = data.get("from_chat_id")
    message_id = data.get("message_id")
    content_type = data.get("content_type", "text")
    user_ids = await get_all_user_ids()
    total = len(user_ids)
    if total == 0:
        await message.answer("⚠️ No users to broadcast to.", parse_mode="HTML", reply_markup=admin_main_keyboard())
        return
    status_msg = await message.answer(f"📢 <b>Broadcast Started</b>\n\nSending to {total:,} users...\n⏳ Please wait.", parse_mode="HTML", reply_markup=admin_main_keyboard())
    delivered = failed = blocked = 0
    for i, user_id in enumerate(user_ids):
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id)
            delivered += 1
        except Exception as e:
            err_str = str(e).lower()
            if "blocked" in err_str or "bot was kicked" in err_str or "deactivated" in err_str:
                blocked += 1
            else:
                failed += 1
        if (i + 1) % 50 == 0 and status_msg:
            try:
                pct = round((i + 1) / total * 100, 1)
                await status_msg.edit_text(f"📢 <b>Broadcasting...</b>\n\nProgress: {i + 1}/{total} ({pct}%)\n✅ Delivered: {delivered}\n🚫 Blocked: {blocked}\n❌ Failed: {failed}", parse_mode="HTML")
            except Exception:
                pass
        await asyncio.sleep(config.BROADCAST_DELAY)
    await save_broadcast_record(admin_id=message.from_user.id, total=total, delivered=delivered, failed=failed, blocked=blocked, message_type=content_type)
    report_text = f"📢 <b>Broadcast Complete!</b>\n\n━━━━━━━━━━━━━━━━━━━\n👥 <b>Total Recipients:</b>  {total:,}\n✅ <b>Delivered:</b>  {delivered:,}\n🚫 <b>Blocked:</b>  {blocked:,}\n❌ <b>Failed:</b>  {failed:,}\n📊 <b>Success Rate:</b>  {round(delivered / total * 100, 1) if total else 0}%\n━━━━━━━━━━━━━━━━━━━"
    try:
        await status_msg.edit_text(report_text, parse_mode="HTML")
    except Exception:
        await message.answer(report_text, parse_mode="HTML")

@admin_broadcast_router.message(IsAdmin(), BroadcastState.confirming, F.text.in_({BTN_CANCEL, BTN_BROADCAST_CANCEL}))
async def cancel_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Broadcast cancelled.", parse_mode="HTML", reply_markup=admin_main_keyboard())

@admin_broadcast_router.message(IsAdmin(), F.text == BTN_BROADCAST_CANCEL)
async def cancel_broadcast_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Broadcast cancelled.", parse_mode="HTML", reply_markup=admin_main_keyboard())

# ── Admin Force Join ───────────────────────────────────────────────────────────
admin_force_join_router = Router(name="admin_force_join")

class ForceJoinState(StatesGroup):
    waiting_channel_id = State()
    waiting_invite_link = State()
    waiting_remove_key = State()

@admin_force_join_router.message(IsAdmin(), F.text == BTN_ADMIN_FORCE_JOIN)
async def force_join_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("📌 <b>Force Join Manager</b>\n\nManage required join channels for bot access.", parse_mode="HTML", reply_markup=admin_force_join_keyboard())

@admin_force_join_router.message(IsAdmin(), F.text == BTN_VIEW_CHANNELS)
async def view_channels(message: Message) -> None:
    channels = await get_all_force_join_channels()
    if not channels:
        await message.answer("📭 <b>No channels configured.</b>\n\nAdd channels using ➕ Add Channel.", parse_mode="HTML", reply_markup=admin_force_join_keyboard())
        return
    lines = [f"📌 <b>Force Join Channels ({len(channels)})</b>\n━━━━━━━━━━━━━━━━━━━\n"]
    for i, ch in enumerate(channels, 1):
        status = "✅ Enabled" if ch.get("status", True) else "🔴 Disabled"
        username = ch.get("channel_username", "")
        channel_id = ch.get("channel_id", "")
        key = ch.get("_key", "")
        invite = ch.get("invite_link", "")
        lines.append(f"\n<b>{i}.</b> {('@' + username) if username else channel_id}\n   🆔 ID: <code>{channel_id}</code>\n   📎 Key: <code>{key}</code>\n   🔗 Link: {invite or 'N/A'}\n   Status: {status}")
    lines.append("\n━━━━━━━━━━━━━━━━━━━\n💡 Use key to enable/disable:\n  • <code>/enable_channel KEY</code>\n  • <code>/disable_channel KEY</code>")
    await message.answer("".join(lines), parse_mode="HTML", reply_markup=admin_force_join_keyboard())

@admin_force_join_router.message(IsAdmin(), F.text == BTN_ADD_CHANNEL)
async def start_add_channel(message: Message, state: FSMContext) -> None:
    await state.set_state(ForceJoinState.waiting_channel_id)
    await message.answer("➕ <b>Add Force Join Channel</b>\n\nStep 1/2: Send the channel ID or @username.\n\n<b>Examples:</b>\n  • <code>-1001234567890</code>\n  • <code>@mychannelname</code>\n\nPress 🔙 Back to abort.", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_force_join_router.message(IsAdmin(), ForceJoinState.waiting_channel_id)
async def receive_channel_id(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=admin_force_join_keyboard())
        return
    channel_id = (message.text or "").strip()
    if not channel_id:
        await message.answer("⚠️ Please send a valid channel ID or @username.")
        return
    channel_username = channel_id.lstrip("@") if channel_id.startswith("@") else ""
    await state.update_data(channel_id=channel_id, channel_username=channel_username)
    await state.set_state(ForceJoinState.waiting_invite_link)
    await message.answer("Step 2/2: Send the channel invite link.\n\n<b>Examples:</b>\n  • <code>https://t.me/mychannelname</code>\n  • <code>https://t.me/+ABCdefGHIjkl</code>\n\nPress 🔙 Back to abort.", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_force_join_router.message(IsAdmin(), ForceJoinState.waiting_invite_link)
async def receive_invite_link(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=admin_force_join_keyboard())
        return
    invite_link = (message.text or "").strip()
    data = await state.get_data()
    await state.clear()
    user = message.from_user
    ok = await add_force_join_channel(channel_id=data.get("channel_id", ""), channel_username=data.get("channel_username", ""), invite_link=invite_link, added_by=user.id if user else 0)
    if ok:
        await message.answer(f"✅ <b>Channel Added Successfully!</b>\n\n🆔 ID: <code>{data.get('channel_id', '')}</code>\n🔗 Link: {invite_link}\n\nUsers must now join this channel to use the bot.", parse_mode="HTML", reply_markup=admin_force_join_keyboard())
    else:
        await message.answer("⚠️ Failed to add channel. Please try again.", parse_mode="HTML", reply_markup=admin_force_join_keyboard())

@admin_force_join_router.message(IsAdmin(), F.text == BTN_REMOVE_CHANNEL)
async def start_remove_channel(message: Message, state: FSMContext) -> None:
    channels = await get_all_force_join_channels()
    if not channels:
        await message.answer("📭 No channels to remove.", parse_mode="HTML", reply_markup=admin_force_join_keyboard())
        return
    await state.set_state(ForceJoinState.waiting_remove_key)
    lines = ["📋 <b>Select channel to remove:</b>\n"]
    for ch in channels:
        key = ch.get("_key", "")
        cid = ch.get("channel_id", "")
        uname = ch.get("channel_username", "")
        display = f"@{uname}" if uname else cid
        lines.append(f"  • <code>{key}</code> — {display}")
    lines.append("\nSend the <b>Key</b> of the channel to remove.")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_force_join_router.message(IsAdmin(), ForceJoinState.waiting_remove_key)
async def receive_remove_key(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=admin_force_join_keyboard())
        return
    key = (message.text or "").strip()
    await state.clear()
    ok = await remove_force_join_channel(key)
    if ok:
        await message.answer(f"✅ Channel <code>{key}</code> removed successfully.", parse_mode="HTML", reply_markup=admin_force_join_keyboard())
    else:
        await message.answer(f"⚠️ Failed to remove channel <code>{key}</code>.", parse_mode="HTML", reply_markup=admin_force_join_keyboard())

@admin_force_join_router.message(IsAdmin(), F.text.startswith("/enable_channel "))
async def enable_channel(message: Message) -> None:
    key = (message.text or "").split(" ", 1)[1].strip()
    ok = await toggle_force_join_channel(key, True)
    await message.answer(f"✅ Channel <code>{key}</code> enabled." if ok else f"⚠️ Failed to enable channel <code>{key}</code>.", parse_mode="HTML")

@admin_force_join_router.message(IsAdmin(), F.text.startswith("/disable_channel "))
async def disable_channel(message: Message) -> None:
    key = (message.text or "").split(" ", 1)[1].strip()
    ok = await toggle_force_join_channel(key, False)
    await message.answer(f"🔴 Channel <code>{key}</code> disabled." if ok else f"⚠️ Failed to disable channel <code>{key}</code>.", parse_mode="HTML")

# ── Admin Statistics ───────────────────────────────────────────────────────────
admin_statistics_router = Router(name="admin_statistics")

@admin_statistics_router.message(IsAdmin(), F.text == BTN_ADMIN_STATISTICS)
async def show_statistics(message: Message) -> None:
    try:
        stats = await get_dashboard_stats()
        all_claims = await get_all_claims()
        pending_c = sum(1 for c in all_claims if c.get("status") == CLAIM_PENDING)
        approved_c = sum(1 for c in all_claims if c.get("status") == CLAIM_APPROVED)
        rejected_c = sum(1 for c in all_claims if c.get("status") == CLAIM_REJECTED)
        total_c = len(all_claims)
        total_users = stats.get("total_users", 0)
        total_refs = stats.get("total_referrals", 0)
        avg_refs = round(total_refs / total_users, 2) if total_users else 0.0
        text = (
            f"📈 <b>Detailed Statistics</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 <b>User Growth</b>\n  📌 Total Users:     {stats['total_users']:,}\n  📅 Today:          {stats['today_users']:,}\n"
            f"  📆 Yesterday:      {stats['yesterday_users']:,}\n  🗓 This Week:      {stats['weekly_users']:,}\n"
            f"  🗓 This Month:     {stats['monthly_users']:,}\n  🚫 Blocked:        {stats['blocked_users']:,}\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n🔗 <b>Referrals</b>\n  ⭐ Total:          {total_refs:,}\n  📊 Avg/User:       {avg_refs}\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n🎁 <b>Claims</b>\n  📦 Total:          {total_c:,}\n  ⏳ Pending:        {pending_c:,}\n"
            f"  ✅ Approved:       {approved_c:,}\n  ❌ Rejected:       {rejected_c:,}\n━━━━━━━━━━━━━━━━━━━"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=admin_main_keyboard())
    except Exception as e:
        logger.error("Statistics error: %s", e)
        await message.answer("⚠️ Failed to load statistics. Please try again.", parse_mode="HTML")

# ── Admin Settings ─────────────────────────────────────────────────────────────
admin_settings_router = Router(name="admin_settings")

class SettingsState(StatesGroup):
    waiting_min_referrals = State()
    waiting_points_per_refer = State()
    waiting_welcome_msg = State()
    waiting_bot_name = State()
    waiting_reward_name = State()

@admin_settings_router.message(IsAdmin(), F.text == BTN_ADMIN_SETTINGS)
async def show_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    settings = await get_settings()
    maintenance_status = "🔴 ON" if settings.get("maintenance") else "🟢 OFF"
    bot_status_label = "🟢 ON" if settings.get("bot_status", True) else "🔴 OFF"
    text = (
        f"⚙️ <b>Bot Settings</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔢 <b>Min Referrals:</b>  {settings.get('minimum_referral', 10)}\n"
        f"⭐ <b>Points Per Refer:</b>  {settings.get('referral_reward', 1)}\n"
        f"🏆 <b>Reward Name:</b>  {settings.get('claim_reward_name', 'Telegram Premium')}\n"
        f"🤖 <b>Bot Name:</b>  {settings.get('bot_name', 'Bot')}\n"
        f"📝 <b>Welcome Msg:</b>  {'Custom' if settings.get('welcome_message') else 'Default'}\n"
        f"🔧 <b>Maintenance:</b>  {maintenance_status}\n🟢 <b>Bot Status:</b>  {bot_status_label}\n━━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_settings_keyboard(maintenance=bool(settings.get("maintenance", False)), bot_status=bool(settings.get("bot_status", True))))

@admin_settings_router.message(IsAdmin(), F.text == "🔢 Min Referrals")
async def set_min_referrals(message: Message, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_min_referrals)
    settings = await get_settings()
    await message.answer(f"🔢 <b>Change Minimum Referrals</b>\n\nCurrent: <b>{settings.get('minimum_referral', 10)}</b>\n\nSend the new minimum number (e.g. <code>10</code>).", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_settings_router.message(IsAdmin(), F.text == "⭐ Points Per Refer")
async def set_points_per_refer(message: Message, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_points_per_refer)
    settings = await get_settings()
    await message.answer(f"⭐ <b>Points Per Referral</b>\n\nCurrent: <b>{settings.get('referral_reward', 1)} point(s)</b>\n\nSend the new value:", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_settings_router.message(IsAdmin(), SettingsState.waiting_points_per_refer)
async def receive_points_per_refer(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=await _settings_keyboard_current())
        return
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) < 1:
        await message.answer("⚠️ Please send a valid positive number.", parse_mode="HTML")
        return
    await state.clear()
    ok = await update_settings({"referral_reward": int(text)})
    kb = await _settings_keyboard_current()
    await message.answer(f"✅ Points per referral set to <b>{text}</b>." if ok else "⚠️ Failed to update.", parse_mode="HTML", reply_markup=kb)

@admin_settings_router.message(IsAdmin(), SettingsState.waiting_min_referrals)
async def receive_min_referrals(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=await _settings_keyboard_current())
        return
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) < 1:
        await message.answer("⚠️ Please send a valid positive number.")
        return
    await state.clear()
    ok = await update_settings({"minimum_referral": int(text)})
    kb = await _settings_keyboard_current()
    await message.answer(f"✅ Minimum referrals set to <b>{text}</b>." if ok else "⚠️ Failed to update.", parse_mode="HTML", reply_markup=kb)

@admin_settings_router.message(IsAdmin(), F.text == "📝 Welcome Msg")
async def set_welcome_msg(message: Message, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_welcome_msg)
    await message.answer("📝 <b>Set Custom Welcome Message</b>\n\nSend the new welcome message.\nUse <code>{name}</code> to include the user's name.\n\nSend <code>default</code> to reset.", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_settings_router.message(IsAdmin(), SettingsState.waiting_welcome_msg)
async def receive_welcome_msg(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=await _settings_keyboard_current())
        return
    text = (message.text or "").strip()
    await state.clear()
    new_val = "" if text.lower() == "default" else text
    ok = await update_settings({"welcome_message": new_val})
    kb = await _settings_keyboard_current()
    label = "reset to default" if not new_val else "updated"
    await message.answer(f"✅ Welcome message {label}." if ok else "⚠️ Failed to update.", parse_mode="HTML", reply_markup=kb)

@admin_settings_router.message(IsAdmin(), F.text == "🤖 Bot Name")
async def set_bot_name(message: Message, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_bot_name)
    settings = await get_settings()
    await message.answer(f"🤖 <b>Change Bot Name</b>\n\nCurrent: <b>{settings.get('bot_name', 'Bot')}</b>\n\nSend new name:", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_settings_router.message(IsAdmin(), SettingsState.waiting_bot_name)
async def receive_bot_name(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=await _settings_keyboard_current())
        return
    name = (message.text or "").strip()
    await state.clear()
    if not name:
        await message.answer("⚠️ Bot name cannot be empty.")
        return
    ok = await update_settings({"bot_name": name})
    kb = await _settings_keyboard_current()
    await message.answer(f"✅ Bot name set to <b>{name}</b>." if ok else "⚠️ Failed to update.", parse_mode="HTML", reply_markup=kb)

@admin_settings_router.message(IsAdmin(), F.text == "🏆 Reward Name")
async def set_reward_name(message: Message, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_reward_name)
    settings = await get_settings()
    await message.answer(f"🏆 <b>Change Reward Name</b>\n\nCurrent: <b>{settings.get('claim_reward_name', 'Telegram Premium')}</b>\n\nSend new name:", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_settings_router.message(IsAdmin(), SettingsState.waiting_reward_name)
async def receive_reward_name(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=await _settings_keyboard_current())
        return
    name = (message.text or "").strip()
    await state.clear()
    if not name:
        await message.answer("⚠️ Reward name cannot be empty.")
        return
    ok = await update_settings({"claim_reward_name": name})
    kb = await _settings_keyboard_current()
    await message.answer(f"✅ Reward name set to <b>{name}</b>." if ok else "⚠️ Failed to update.", parse_mode="HTML", reply_markup=kb)

@admin_settings_router.message(IsAdmin(), F.text == "🔧 Maintenance ON")
async def maintenance_on(message: Message) -> None:
    ok = await update_settings({"maintenance": True})
    kb = admin_settings_keyboard(maintenance=True, bot_status=True)
    await message.answer("🔧 <b>Maintenance mode ENABLED.</b>\n\nNormal users cannot use the bot until you turn it OFF." if ok else "⚠️ Failed to update.", parse_mode="HTML", reply_markup=kb)

@admin_settings_router.message(IsAdmin(), F.text == "✅ Maintenance OFF")
async def maintenance_off(message: Message) -> None:
    ok = await update_settings({"maintenance": False})
    kb = admin_settings_keyboard(maintenance=False, bot_status=True)
    await message.answer("✅ <b>Maintenance mode DISABLED.</b>\n\nBot is now accessible to all users." if ok else "⚠️ Failed to update.", parse_mode="HTML", reply_markup=kb)

@admin_settings_router.message(IsAdmin(), F.text == "🟢 Bot ON")
async def bot_on(message: Message) -> None:
    ok = await update_settings({"bot_status": True})
    kb = admin_settings_keyboard(maintenance=False, bot_status=True)
    await message.answer("🟢 <b>Bot is now ON.</b>" if ok else "⚠️ Failed to update.", parse_mode="HTML", reply_markup=kb)

@admin_settings_router.message(IsAdmin(), F.text == "🔴 Bot OFF")
async def bot_off(message: Message) -> None:
    ok = await update_settings({"bot_status": False})
    kb = admin_settings_keyboard(maintenance=False, bot_status=False)
    await message.answer("🔴 <b>Bot is now OFF.</b>\n\nOnly admins can use the bot." if ok else "⚠️ Failed to update.", parse_mode="HTML", reply_markup=kb)

@admin_settings_router.message(IsAdmin(), F.text.startswith("/block "))
async def block_user_cmd(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: /block USER_ID")
        return
    target_id = int(parts[1])
    ok = await block_user(target_id, message.from_user.id)
    await message.answer(f"🚫 User <code>{target_id}</code> blocked." if ok else f"⚠️ Failed to block user <code>{target_id}</code>.", parse_mode="HTML")

@admin_settings_router.message(IsAdmin(), F.text.startswith("/unblock "))
async def unblock_user_cmd(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: /unblock USER_ID")
        return
    target_id = int(parts[1])
    ok = await unblock_user(target_id, message.from_user.id)
    await message.answer(f"✅ User <code>{target_id}</code> unblocked." if ok else f"⚠️ Failed to unblock user <code>{target_id}</code>.", parse_mode="HTML")

# ── Admin Admins ───────────────────────────────────────────────────────────────
admin_admins_router = Router(name="admin_admins")

class AdminState(StatesGroup):
    waiting_add_id = State()
    waiting_remove_id = State()

@admin_admins_router.message(IsAdmin(), F.text == BTN_ADMIN_ADMINS)
async def admins_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("👑 <b>Admin Management</b>\n\nManage bot administrators.", parse_mode="HTML", reply_markup=admin_admins_keyboard())

@admin_admins_router.message(IsAdmin(), F.text == BTN_VIEW_ADMINS)
async def view_admins(message: Message) -> None:
    admin_ids = await get_all_admin_ids()
    admins_data = await get_admins_data()
    env_admins = config.get_initial_admin_ids()
    lines = [f"👑 <b>Current Admins ({len(admin_ids)})</b>\n━━━━━━━━━━━━━━━━━━━\n"]
    for i, uid in enumerate(admin_ids, 1):
        source = "🔒 ENV" if uid in env_admins else "🔧 DB"
        db_user = await get_user(uid)
        name = db_user.get("full_name", "Unknown") if db_user else "Unknown"
        uname = db_user.get("username", "") if db_user else ""
        lines.append(f"\n<b>{i}.</b> {name} ({'@' + uname if uname else 'N/A'})\n   🆔 <code>{uid}</code>  {source}")
    await message.answer("".join(lines), parse_mode="HTML", reply_markup=admin_admins_keyboard())

@admin_admins_router.message(IsAdmin(), F.text == BTN_ADD_ADMIN)
async def start_add_admin(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminState.waiting_add_id)
    await message.answer("➕ <b>Add Admin</b>\n\nSend the Telegram User ID of the new admin.\n\n<b>Note:</b> The user must have started the bot.\nPress 🔙 Back to cancel.", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_admins_router.message(IsAdmin(), AdminState.waiting_add_id)
async def receive_add_admin_id(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=admin_admins_keyboard())
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("⚠️ Please send a valid numeric User ID.")
        return
    target_id = int(text)
    sender_id = message.from_user.id
    await state.clear()
    if target_id == sender_id:
        await message.answer("⚠️ You cannot add yourself as admin.", reply_markup=admin_admins_keyboard())
        return
    if await is_admin(target_id):
        await message.answer(f"⚠️ User <code>{target_id}</code> is already an admin.", parse_mode="HTML", reply_markup=admin_admins_keyboard())
        return
    ok = await add_admin(target_id, sender_id)
    if ok:
        db_user = await get_user(target_id)
        name = db_user.get("full_name", str(target_id)) if db_user else str(target_id)
        await message.answer(f"✅ <b>Admin Added</b>\n\n👤 {name}\n🆔 <code>{target_id}</code>", parse_mode="HTML", reply_markup=admin_admins_keyboard())
    else:
        await message.answer("⚠️ Failed to add admin.", reply_markup=admin_admins_keyboard())

@admin_admins_router.message(IsAdmin(), F.text == BTN_REMOVE_ADMIN)
async def start_remove_admin(message: Message, state: FSMContext) -> None:
    admin_ids = await get_all_admin_ids()
    env_admins = config.get_initial_admin_ids()
    removable = [uid for uid in admin_ids if uid not in env_admins]
    if not removable:
        await message.answer("⚠️ No removable admins. Environment admins cannot be removed here.", parse_mode="HTML", reply_markup=admin_admins_keyboard())
        return
    await state.set_state(AdminState.waiting_remove_id)
    lines = ["➖ <b>Remove Admin</b>\n\nRemovable admins:\n"]
    for uid in removable:
        db_user = await get_user(uid)
        name = db_user.get("full_name", str(uid)) if db_user else str(uid)
        lines.append(f"  • <code>{uid}</code> — {name}")
    lines.append("\nSend the <b>User ID</b> to remove:")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_admins_router.message(IsAdmin(), AdminState.waiting_remove_id)
async def receive_remove_admin_id(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=admin_admins_keyboard())
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("⚠️ Please send a valid numeric User ID.")
        return
    target_id = int(text)
    sender_id = message.from_user.id
    await state.clear()
    env_admins = config.get_initial_admin_ids()
    if target_id in env_admins:
        await message.answer("⚠️ Cannot remove environment-configured admins.", reply_markup=admin_admins_keyboard())
        return
    ok = await remove_admin(target_id, sender_id)
    await message.answer(f"✅ Admin <code>{target_id}</code> removed." if ok else "⚠️ Failed to remove admin.", parse_mode="HTML", reply_markup=admin_admins_keyboard())

# ── Admin Users ────────────────────────────────────────────────────────────────
admin_users_router = Router(name="admin_users")

class UserMgmtState(StatesGroup):
    waiting_block_id = State()
    waiting_unblock_id = State()
    waiting_points_user_id = State()
    waiting_points_amount = State()
    waiting_view_id = State()

@admin_users_router.message(IsAdmin(), F.text == BTN_ADMIN_USERS)
async def users_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("👥 <b>User Management</b>\n\nBlock, unblock users or edit their points.", parse_mode="HTML", reply_markup=admin_users_keyboard())

@admin_users_router.message(IsAdmin(), F.text == "🚫 Block User")
async def start_block(message: Message, state: FSMContext) -> None:
    await state.set_state(UserMgmtState.waiting_block_id)
    await message.answer("🚫 <b>Block User</b>\n\nSend the <b>User ID</b> to block.\nPress 🔙 Back to cancel.", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_users_router.message(IsAdmin(), UserMgmtState.waiting_block_id)
async def do_block(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=admin_users_keyboard())
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("⚠️ Please send a valid numeric User ID.")
        return
    target_id = int(text)
    sender_id = message.from_user.id
    await state.clear()
    db_user = await get_user(target_id)
    if not db_user:
        await message.answer(f"⚠️ User <code>{target_id}</code> not found.", parse_mode="HTML", reply_markup=admin_users_keyboard())
        return
    if db_user.get("blocked"):
        await message.answer(f"⚠️ User <code>{target_id}</code> is already blocked.", parse_mode="HTML", reply_markup=admin_users_keyboard())
        return
    ok = await block_user(target_id, sender_id)
    if ok:
        name = db_user.get("full_name", str(target_id))
        uname = db_user.get("username", "")
        await message.answer(f"🚫 <b>User Blocked</b>\n\n👤 {name} {'(@' + uname + ')' if uname else ''}\n🆔 <code>{target_id}</code>", parse_mode="HTML", reply_markup=admin_users_keyboard())
    else:
        await message.answer("⚠️ Failed to block user.", reply_markup=admin_users_keyboard())

@admin_users_router.message(IsAdmin(), F.text == "✅ Unblock User")
async def start_unblock(message: Message, state: FSMContext) -> None:
    await state.set_state(UserMgmtState.waiting_unblock_id)
    await message.answer("✅ <b>Unblock User</b>\n\nSend the <b>User ID</b> to unblock.\nPress 🔙 Back to cancel.", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_users_router.message(IsAdmin(), UserMgmtState.waiting_unblock_id)
async def do_unblock(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=admin_users_keyboard())
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("⚠️ Please send a valid numeric User ID.")
        return
    target_id = int(text)
    sender_id = message.from_user.id
    await state.clear()
    db_user = await get_user(target_id)
    if not db_user:
        await message.answer(f"⚠️ User <code>{target_id}</code> not found.", parse_mode="HTML", reply_markup=admin_users_keyboard())
        return
    if not db_user.get("blocked"):
        await message.answer(f"⚠️ User <code>{target_id}</code> is not blocked.", parse_mode="HTML", reply_markup=admin_users_keyboard())
        return
    ok = await unblock_user(target_id, sender_id)
    if ok:
        name = db_user.get("full_name", str(target_id))
        uname = db_user.get("username", "")
        await message.answer(f"✅ <b>User Unblocked</b>\n\n👤 {name} {'(@' + uname + ')' if uname else ''}\n🆔 <code>{target_id}</code>", parse_mode="HTML", reply_markup=admin_users_keyboard())
    else:
        await message.answer("⚠️ Failed to unblock user.", reply_markup=admin_users_keyboard())

@admin_users_router.message(IsAdmin(), F.text == "⭐ Edit Points")
async def start_edit_points(message: Message, state: FSMContext) -> None:
    await state.set_state(UserMgmtState.waiting_points_user_id)
    await message.answer("⭐ <b>Edit User Points</b>\n\nStep 1/2: Send the <b>User ID</b>.\nPress 🔙 Back to cancel.", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_users_router.message(IsAdmin(), UserMgmtState.waiting_points_user_id)
async def receive_points_user_id(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=admin_users_keyboard())
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("⚠️ Please send a valid numeric User ID.")
        return
    target_id = int(text)
    db_user = await get_user(target_id)
    if not db_user:
        await message.answer(f"⚠️ User <code>{target_id}</code> not found.", parse_mode="HTML")
        return
    current_points = int(db_user.get("referral_points", 0))
    name = db_user.get("full_name", str(target_id))
    await state.update_data(target_id=target_id, current_points=current_points)
    await state.set_state(UserMgmtState.waiting_points_amount)
    await message.answer(f"⭐ <b>Edit Points</b>\n\n👤 <b>User:</b> {name}\n🆔 <b>ID:</b> <code>{target_id}</code>\n⭐ <b>Current Points:</b> {current_points}\n\n━━━━━━━━━━━━━━━━━━━\nStep 2/2: Send amount.\n\n<b>Examples:</b>\n  • <code>+5</code> → add 5\n  • <code>-3</code> → subtract 3\n  • <code>10</code> → set to 10\n\nPress 🔙 Back to cancel.", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_users_router.message(IsAdmin(), UserMgmtState.waiting_points_amount)
async def do_edit_points(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=admin_users_keyboard())
        return
    raw = (message.text or "").strip()
    data = await state.get_data()
    target_id: int = data["target_id"]
    current_points: int = data["current_points"]
    await state.clear()
    if raw.startswith("+") and raw[1:].isdigit():
        delta = int(raw[1:])
        new_points = current_points + delta
        op_str = f"+{delta}"
    elif raw.startswith("-") and raw[1:].isdigit():
        delta = int(raw[1:])
        new_points = max(0, current_points - delta)
        op_str = f"-{delta}"
    elif raw.lstrip("-").isdigit() and not raw.startswith("-"):
        new_points = int(raw)
        op_str = f"set to {new_points}"
    else:
        await message.answer("⚠️ Invalid format. Use <code>+5</code>, <code>-3</code>, or <code>10</code>.", parse_mode="HTML")
        return
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, fb_update, f"users/{target_id}", {"referral_points": new_points})
    _user_cache.pop(f"user_{target_id}", None)
    if ok:
        db_user = await get_user(target_id)
        name = db_user.get("full_name", str(target_id)) if db_user else str(target_id)
        await message.answer(f"✅ <b>Points Updated!</b>\n\n👤 <b>User:</b> {name}\n🆔 <b>ID:</b> <code>{target_id}</code>\n📝 <b>Operation:</b> {op_str}\n⭐ <b>Before:</b> {current_points}\n⭐ <b>After:</b> {new_points}", parse_mode="HTML", reply_markup=admin_users_keyboard())
    else:
        await message.answer("⚠️ Failed to update points.", reply_markup=admin_users_keyboard())

@admin_users_router.message(IsAdmin(), F.text == "🔍 View User")
async def start_view_user(message: Message, state: FSMContext) -> None:
    await state.set_state(UserMgmtState.waiting_view_id)
    await message.answer("🔍 <b>View User Info</b>\n\nSend the <b>User ID</b> to look up.\nPress 🔙 Back to cancel.", parse_mode="HTML", reply_markup=admin_back_keyboard())

@admin_users_router.message(IsAdmin(), UserMgmtState.waiting_view_id)
async def do_view_user(message: Message, state: FSMContext) -> None:
    if message.text == BTN_ADMIN_BACK:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=admin_users_keyboard())
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("⚠️ Please send a valid numeric User ID.")
        return
    target_id = int(text)
    await state.clear()
    db_user = await get_user(target_id)
    if not db_user:
        await message.answer(f"⚠️ User <code>{target_id}</code> not found.", parse_mode="HTML", reply_markup=admin_users_keyboard())
        return
    name = db_user.get("full_name", "Unknown")
    uname = db_user.get("username", "")
    join_date = format_datetime(db_user.get("join_date"))
    last_active = format_datetime(db_user.get("last_active"))
    points = int(db_user.get("referral_points", 0))
    ref_count = int(db_user.get("referral_count", 0))
    total_claims = int(db_user.get("total_claims", 0))
    blocked = db_user.get("blocked", False)
    status = "🚫 Blocked" if blocked else "✅ Active"
    await message.answer(
        f"🔍 <b>User Info</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>Name:</b>  {name}\n🔖 <b>Username:</b>  {'@' + uname if uname else 'N/A'}\n"
        f"🆔 <b>User ID:</b>  <code>{target_id}</code>\n📅 <b>Joined:</b>  {join_date}\n"
        f"🕐 <b>Last Active:</b>  {last_active}\n\n⭐ <b>Points:</b>  {points}\n"
        f"👥 <b>Referrals:</b>  {ref_count}\n🎁 <b>Total Claims:</b>  {total_claims}\n"
        f"🔒 <b>Status:</b>  {status}\n━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML", reply_markup=admin_users_keyboard(),
    )

# ══════════════════════════════════════════════════════════════════════════════
# BOT STARTUP / SHUTDOWN
# ══════════════════════════════════════════════════════════════════════════════

def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ThrottlingMiddleware())
    dp.message.middleware(AuthMiddleware())
    dp.include_router(admin_dashboard_router)
    dp.include_router(admin_requests_router)
    dp.include_router(admin_broadcast_router)
    dp.include_router(admin_force_join_router)
    dp.include_router(admin_statistics_router)
    dp.include_router(admin_settings_router)
    dp.include_router(admin_admins_router)
    dp.include_router(admin_users_router)
    dp.include_router(start_router)
    dp.include_router(user_router)
    dp.include_router(referral_router)
    dp.include_router(premium_router)
    return dp

async def on_startup(bot: Bot) -> None:
    logger.info("=" * 55)
    logger.info("  Telegram Premium Referral Bot Starting...")
    logger.info("=" * 55)
    try:
        initialize_firebase()
        logger.info("✅ Firebase connected.")
    except Exception as e:
        logger.critical("❌ Firebase initialization failed: %s", e)
        sys.exit(1)
    try:
        bot_info = await bot.get_me()
        logger.info("✅ Bot: @%s (ID: %s)", bot_info.username, bot_info.id)
    except Exception as e:
        logger.error("Failed to get bot info: %s", e)
    try:
        admin_ids = await get_all_admin_ids()
        logger.info("✅ Admins loaded: %s", admin_ids)
    except Exception as e:
        logger.error("Failed to load admins: %s", e)
    try:
        settings = await get_settings()
        logger.info("✅ Settings loaded: min_referral=%s maintenance=%s", settings.get("minimum_referral"), settings.get("maintenance"))
    except Exception as e:
        logger.error("Failed to load settings: %s", e)
    logger.info("=" * 55)
    logger.info("  Bot is ready and accepting messages!")
    logger.info("=" * 55)

async def on_shutdown(bot: Bot) -> None:
    logger.info("Bot is shutting down...")
    await bot.session.close()
    logger.info("Bot stopped.")

async def run_polling() -> None:
    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = create_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    logger.info("Starting in POLLING mode...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), drop_pending_updates=True)
    finally:
        await bot.session.close()

async def run_webhook() -> None:
    if not config.WEBHOOK_HOST:
        logger.error("WEBHOOK_HOST is not set. Falling back to polling.")
        await run_polling()
        return
    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = create_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    webhook_url = f"{config.WEBHOOK_HOST}{config.WEBHOOK_PATH}"
    await bot.set_webhook(url=webhook_url, allowed_updates=dp.resolve_used_update_types(), drop_pending_updates=True)
    logger.info("Webhook set: %s", webhook_url)
    app = web.Application()
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path=config.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    logger.info("Starting in WEBHOOK mode on port %s...", config.WEBHOOK_PORT)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.WEBHOOK_PORT)
    await site.start()
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await bot.session.close()

def main() -> None:
    try:
        config.validate()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)
    if config.USE_POLLING:
        asyncio.run(run_polling())
    else:
        asyncio.run(run_webhook())

if __name__ == "__main__":
    main()
