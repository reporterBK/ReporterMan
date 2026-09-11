import os
import time
import json
import sqlite3
import threading
import requests
from datetime import datetime, timedelta


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8203764232

DB_FILE = "breaking_repo.db"

DEFAULT_REPORT_MAX = 100
DEFAULT_EMAIL_MAX = 100

PROCESS_DELAY = 330

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN پیدا نشد. متغیر BOT_TOKEN را در Railway Variables قرار بده."
    )

API = f"https://api.telegram.org/bot{TOKEN}"


# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False,
        timeout=30
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            target TEXT NOT NULL,
            count INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            expires_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    defaults = {
        "force_join": "0",
        "force_channel": "",
        "report_max": str(DEFAULT_REPORT_MAX),
        "email_max": str(DEFAULT_EMAIL_MAX),
    }

    for key, value in defaults.items():
        cur.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
            (key, value)
        )

    conn.commit()
    conn.close()


init_db()


# =========================================================
# TELEGRAM API
# =========================================================

def tg(method, data=None):
    try:
        response = requests.post(
            f"{API}/{method}",
            data=data or {},
            timeout=35
        )

        try:
            result = response.json()
        except Exception:
            print("Telegram returned non-JSON:", response.text)
            return {}

        if not result.get("ok"):
            print(
                f"Telegram API ERROR [{method}]:",
                result
            )

        return result

    except requests.RequestException as e:
        print(f"NETWORK ERROR [{method}]:", e)
        return {}

    except Exception as e:
        print(f"TG ERROR [{method}]:", e)
        return {}


def send(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup is not None:
        # مهم: Telegram باید JSON دریافت کند
        data["reply_markup"] = json.dumps(
            reply_markup,
            ensure_ascii=False
        )

    return tg("sendMessage", data)


def edit(chat_id, message_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }

    if reply_markup is not None:
        # مهم: Telegram باید JSON دریافت کند
        data["reply_markup"] = json.dumps(
            reply_markup,
            ensure_ascii=False
        )

    return tg("editMessageText", data)


def answer(callback_id, text=None):
    data = {
        "callback_query_id": callback_id
    }

    if text:
        data["text"] = text

    return tg("answerCallbackQuery", data)


# =========================================================
# COLORED BUTTONS
# =========================================================

def blue(text, callback_data):
    return {
        "text": text,
        "callback_data": callback_data,
        "style": "primary"
    }


def green(text, callback_data):
    return {
        "text": text,
        "callback_data": callback_data,
        "style": "success"
    }


def red(text, callback_data):
    return {
        "text": text,
        "callback_data": callback_data,
        "style": "danger"
    }


def blue_url(text, url):
    return {
        "text": text,
        "url": url,
        "style": "primary"
    }


def green_url(text, url):
    return {
        "text": text,
        "url": url,
        "style": "success"
    }


# =========================================================
# SETTINGS
# =========================================================

def get_setting(key, default=None):
    conn = db()

    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,)
        ).fetchone()

        if row:
            return row["value"]

        return default

    finally:
        conn.close()


def set_setting(key, value):
    conn = db()

    try:
        conn.execute("""
            INSERT INTO settings(key, value)
            VALUES(?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value
        """, (key, str(value)))

        conn.commit()

    finally:
        conn.close()


def get_report_max():
    try:
        value = int(
            get_setting(
                "report_max",
                DEFAULT_REPORT_MAX
            )
        )

        return max(1, min(100, value))

    except Exception:
        return DEFAULT_REPORT_MAX


def get_email_max():
    try:
        value = int(
            get_setting(
                "email_max",
                DEFAULT_EMAIL_MAX
            )
        )

        return max(1, min(100, value))

    except Exception:
        return DEFAULT_EMAIL_MAX


# =========================================================
# USERS
# =========================================================

def save_user(user):
    conn = db()

    try:
        conn.execute("""
            INSERT INTO users(
                user_id,
                username,
                first_name,
                joined_at
            )
            VALUES(?, ?, ?, ?)

            ON CONFLICT(user_id)
            DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name
        """, (
            user["id"],
            user.get("username", ""),
            user.get("first_name", ""),
            datetime.now().isoformat()
        ))

        conn.commit()

    finally:
        conn.close()


def users_count():
    conn = db()

    try:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM users"
        ).fetchone()["c"]

    finally:
        conn.close()


def requests_count():
    conn = db()

    try:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM requests"
        ).fetchone()["c"]

    finally:
        conn.close()


# =========================================================
# SUBSCRIPTIONS
# =========================================================

def add_subscription(user_id, days):
    conn = db()

    try:
        now = datetime.now()

        old = conn.execute(
            "SELECT expires_at FROM subscriptions WHERE user_id=?",
            (user_id,)
        ).fetchone()

        expires = now + timedelta(days=days)

        if old:
            try:
                old_date = datetime.fromisoformat(
                    old["expires_at"]
                )

                if old_date > now:
                    expires = old_date + timedelta(days=days)

            except Exception:
                pass

        conn.execute("""
            INSERT INTO subscriptions(
                user_id,
                expires_at
            )
            VALUES(?, ?)

            ON CONFLICT(user_id)
            DO UPDATE SET
                expires_at=excluded.expires_at
        """, (
            user_id,
            expires.isoformat()
        ))

        conn.commit()

    finally:
        conn.close()


def remove_subscription(user_id):
    conn = db()

    try:
        conn.execute(
            "DELETE FROM subscriptions WHERE user_id=?",
            (user_id,)
        )

        conn.commit()

    finally:
        conn.close()


def has_subscription(user_id):
    conn = db()

    try:
        row = conn.execute(
            "SELECT expires_at FROM subscriptions WHERE user_id=?",
            (user_id,)
        ).fetchone()

    finally:
        conn.close()

    if not row:
        return False

    try:
        return datetime.fromisoformat(
            row["expires_at"]
        ) > datetime.now()

    except Exception:
        return False


def subscription_text(user_id):
    conn = db()

    try:
        row = conn.execute(
            "SELECT expires_at FROM subscriptions WHERE user_id=?",
            (user_id,)
        ).fetchone()

    finally:
        conn.close()

    if not row:
        return "❌ اشتراک فعال ندارید."

    try:
        expires = datetime.fromisoformat(
            row["expires_at"]
        )

        if expires <= datetime.now():
            return "❌ اشتراک شما منقضی شده است."

        return (
            "✅ اشتراک فعال است\n\n"
            f"📅 انقضا: {expires.strftime('%Y-%m-%d %H:%M')}"
        )

    except Exception:
        return "❌ اطلاعات اشتراک قابل خواندن نیست."


# =========================================================
# REQUESTS
# =========================================================

def create_request(user_id, kind, target, count):
    conn = db()

    try:
        cursor = conn.execute("""
            INSERT INTO requests(
                user_id,
                kind,
                target,
                count,
                status,
                created_at
            )
            VALUES(?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            kind,
            target,
            count,
            "pending",
            datetime.now().isoformat()
        ))

        conn.commit()

        return cursor.lastrowid

    finally:
        conn.close()


def complete_request(request_id):
    conn = db()

    try:
        conn.execute("""
            UPDATE requests
            SET status='completed'
            WHERE id=?
        """, (request_id,))

        conn.commit()

    finally:
        conn.close()


def delayed_result(chat_id, request_id, kind):
    try:
        time.sleep(PROCESS_DELAY)

        complete_request(request_id)

        if kind == "report":
            text = (
                "✅ پردازش داخلی انجام شد.\n\n"
                "درخواست شما ثبت و پردازش شد."
            )

        else:
            text = (
                "✅ پردازش داخلی انجام شد.\n\n"
                "متن ایمیل شما ثبت و پردازش شد."
            )

        send(
            chat_id,
            text,
            home_keyboard()
        )

    except Exception as e:
        print("DELAY ERROR:", e)


# =========================================================
# TELEGRAM LINK VALIDATION
# =========================================================

def is_telegram_link(text):
    text = text.strip()

    lower = text.lower()

    valid_prefixes = (
        "https://t.me/",
        "http://t.me/",
        "https://telegram.me/",
        "http://telegram.me/"
    )

    if not lower.startswith(valid_prefixes):
        return False

    # بعد از دامنه باید چیزی وجود داشته باشد
    remainder = lower.split("/", 3)

    if len(remainder) < 4:
        return False

    username = remainder[3].strip()

    if not username:
        return False

    # لینک‌های نامناسب برای این بخش
    blocked = (
        "addstickers/",
        "share/",
        "iv",
        "s/"
    )

    for item in blocked:
        if item in username:
            return False

    return True


# =========================================================
# KEYBOARDS
# =========================================================

def home_keyboard():
    return {
        "inline_keyboard": [
            [
                blue("⚡ ثبت درخواست", "request")
            ],
            [
                green("📧 بخش ایمیل", "email"),
                blue("👤 حساب من", "account")
            ],
            [
                blue("📊 وضعیت", "status"),
                blue("🆔 آیدی من", "myid")
            ],
            [
                green("💎 اشتراک", "subscription"),
                blue("💬 پشتیبانی", "support")
            ]
        ]
    }


def request_keyboard():
    return {
        "inline_keyboard": [
            [
                blue(
                    "🔗 ثبت لینک تلگرام",
                    "request_link"
                )
            ],
            [
                red(
                    "🔙 بازگشت",
                    "home"
                )
            ]
        ]
    }


def email_keyboard():
    return {
        "inline_keyboard": [
            [
                blue(
                    "📧 ثبت متن ایمیل",
                    "email_text"
                )
            ],
            [
                red(
                    "🔙 بازگشت",
                    "home"
                )
            ]
        ]
    }


def back_keyboard():
    return {
        "inline_keyboard": [
            [
                red(
                    "🔙 بازگشت",
                    "home"
                )
            ]
        ]
    }


def admin_keyboard():
    return {
        "inline_keyboard": [
            [
                blue(
                    "👥 تعداد کاربران",
                    "admin_users"
                ),
                blue(
                    "📊 آمار درخواست‌ها",
                    "admin_stats"
                )
            ],
            [
                green(
                    "💎 افزودن اشتراک",
                    "admin_add_sub"
                ),
                red(
                    "❌ حذف اشتراک",
                    "admin_remove_sub"
                )
            ],
            [
                green(
                    "➕ افزایش اشتراک",
                    "admin_extend_sub"
                ),
                blue(
                    "📢 عضویت اجباری",
                    "admin_force"
                )
            ],
            [
                blue(
                    "⚙️ تنظیمات تعداد",
                    "admin_limits"
                )
            ],
            [
                red(
                    "🔙 بازگشت",
                    "home"
                )
            ]
        ]
    }


def force_admin_keyboard():
    status = get_setting(
        "force_join",
        "0"
    )

    if status == "1":
        status_button = green(
            "🟢 عضویت اجباری: روشن",
            "admin_toggle_force"
        )
    else:
        status_button = red(
            "🔴 عضویت اجباری: خاموش",
            "admin_toggle_force"
        )

    return {
        "inline_keyboard": [
            [
                status_button
            ],
            [
                blue(
                    "📢 تنظیم کانال",
                    "admin_set_channel"
                )
            ],
            [
                red(
                    "🔙 بازگشت",
                    "admin"
                )
            ]
        ]
    }


def limits_keyboard():
    return {
        "inline_keyboard": [
            [
                blue(
                    f"📌 سقف ثبت درخواست: {get_report_max()}",
                    "admin_report_limit"
                )
            ],
            [
                green(
                    f"📧 سقف بخش ایمیل: {get_email_max()}",
                    "admin_email_limit"
                )
            ],
            [
                red(
                    "🔙 بازگشت",
                    "admin"
                )
            ]
        ]
    }


# =========================================================
# FORCE JOIN
# =========================================================

def check_membership(user_id):
    force = get_setting(
        "force_join",
        "0"
    )

    channel = get_setting(
        "force_channel",
        ""
    )

    if force != "1":
        return True

    if not channel:
        return True

    try:
        result = tg(
            "getChatMember",
            {
                "chat_id": channel,
                "user_id": user_id
            }
        )

        if not result.get("ok"):
            return False

        status = result["result"]["status"]

        return status in (
            "creator",
            "administrator",
            "member"
        )

    except Exception:
        return False


def force_join_message(chat_id):
    channel = get_setting(
        "force_channel",
        ""
    )

    if not channel:
        return False

    clean = channel.strip().replace("@", "")

    keyboard = {
        "inline_keyboard": [
            [
                blue_url(
                    "📢 عضویت در کانال",
                    f"https://t.me/{clean}"
                )
            ],
            [
                green(
                    "✅ عضو شدم",
                    "check_join"
                )
            ]
        ]
    }

    send(
        chat_id,
        "برای استفاده از ربات ابتدا در کانال عضو شوید.",
        keyboard
    )

    return True


# =========================================================
# STATES
# =========================================================

user_states = {}
admin_states = {}


def set_state(user_id, state, data=None):
    user_states[user_id] = {
        "state": state,
        "data": data or {}
    }


def get_state(user_id):
    return user_states.get(user_id)


def clear_state(user_id):
    user_states.pop(user_id, None)


def set_admin_state(user_id, state):
    admin_states[user_id] = state


def get_admin_state(user_id):
    return admin_states.get(user_id)


def clear_admin_state(user_id):
    admin_states.pop(user_id, None)


# =========================================================
# HOME
# =========================================================

def show_home(chat_id):
    send(
        chat_id,
        "🔥 BREAKING REPO\n\n"
        "به ربات خوش آمدید.\n\n"
        "از منوی زیر انتخاب کنید:",
        home_keyboard()
    )


# =========================================================
# CALLBACK HANDLER
# =========================================================

def handle_callback(query):

    callback_id = query["id"]
    data = query.get("data", "")

    user = query["from"]

    user_id = user["id"]

    message = query.get("message")

    if not message:
        answer(callback_id)
        return

    chat_id = message["chat"]["id"]
    message_id = message["message_id"]

    # فقط یک بار پاسخ callback
    answer(callback_id)

    # =====================================================
    # CHECK JOIN
    # =====================================================

    if data == "check_join":

        if check_membership(user_id):

            edit(
                chat_id,
                message_id,
                "✅ عضویت تأیید شد.\n\n"
                "حالا می‌توانید از ربات استفاده کنید.",
                home_keyboard()
            )

        else:

            send(
                chat_id,
                "❌ هنوز عضویت شما تأیید نشده است."
            )

        return

    # =====================================================
    # HOME
    # =====================================================

    if data == "home":

        clear_state(user_id)
        clear_admin_state(user_id)

        edit(
            chat_id,
            message_id,
            "🔥 BREAKING REPO\n\n"
            "منوی اصلی:",
            home_keyboard()
        )

        return

    # =====================================================
    # ADMIN
    # =====================================================

    if data == "admin":

        if user_id != ADMIN_ID:
            return

        clear_admin_state(user_id)

        edit(
            chat_id,
            message_id,
            "🛠 پنل مدیریت BREAKING REPO",
            admin_keyboard()
        )

        return

    if data == "admin_users":

        if user_id != ADMIN_ID:
            return

        edit(
            chat_id,
            message_id,
            f"👥 تعداد کاربران:\n\n{users_count()}",
            admin_keyboard()
        )

        return

    if data == "admin_stats":

        if user_id != ADMIN_ID:
            return

        edit(
            chat_id,
            message_id,
            "📊 آمار ربات\n\n"
            f"👥 کاربران: {users_count()}\n"
            f"📋 درخواست‌ها: {requests_count()}",
            admin_keyboard()
        )

        return

    if data == "admin_limits":

        if user_id != ADMIN_ID:
            return

        edit(
            chat_id,
            message_id,
            "⚙️ تنظیمات تعداد\n\n"
            "سقف دو بخش را می‌توانی جداگانه تغییر بدهی.",
            limits_keyboard()
        )

        return

    if data == "admin_report_limit":

        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "report_limit"
        )

        edit(
            chat_id,
            message_id,
            "📌 سقف ثبت درخواست\n\n"
            "یک عدد بین 1 تا 100 ارسال کن.",
            back_keyboard()
        )

        return

    if data == "admin_email_limit":

        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "email_limit"
        )

        edit(
            chat_id,
            message_id,
            "📧 سقف بخش ایمیل\n\n"
            "یک عدد بین 1 تا 100 ارسال کن.",
            back_keyboard()
        )

        return

    if data == "admin_add_sub":

        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "add_sub"
        )

        edit(
            chat_id,
            message_id,
            "💎 افزودن اشتراک\n\n"
            "فرمت:\n\n"
            "USER_ID DAYS\n\n"
            "مثال:\n"
            "123456789 30",
            back_keyboard()
        )

        return

    if data == "admin_remove_sub":

        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "remove_sub"
        )

        edit(
            chat_id,
            message_id,
            "🗑 آیدی کاربر را ارسال کن.",
            back_keyboard()
        )

        return

    if data == "admin_extend_sub":

        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "extend_sub"
        )

        edit(
            chat_id,
            message_id,
            "➕ افزایش اشتراک\n\n"
            "فرمت:\n\n"
            "USER_ID DAYS\n\n"
            "مثال:\n"
            "123456789 7",
            back_keyboard()
        )

        return

    if data == "admin_force":

        if user_id != ADMIN_ID:
            return

        edit(
            chat_id,
            message_id,
            "📢 تنظیمات عضویت اجباری",
            force_admin_keyboard()
        )

        return

    if data == "admin_toggle_force":

        if user_id != ADMIN_ID:
            return

        current = get_setting(
            "force_join",
            "0"
        )

        set_setting(
            "force_join",
            "0" if current == "1" else "1"
        )

        edit(
            chat_id,
            message_id,
            "📢 تنظیمات عضویت اجباری",
            force_admin_keyboard()
        )

        return

    if data == "admin_set_channel":

        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "set_channel"
        )

        edit(
            chat_id,
            message_id,
            "📢 آیدی کانال را ارسال کن.\n\n"
            "مثال:\n"
            "@MyChannel",
            back_keyboard()
        )

        return

    # =====================================================
    # USER REQUEST
    # =====================================================

    if data == "request":

        if not check_membership(user_id):

            force_join_message(chat_id)
            return

        if not has_subscription(user_id):

            edit(
                chat_id,
                message_id,
                "❌ برای ثبت درخواست اشتراک فعال لازم است.",
                {
                    "inline_keyboard": [
                        [
                            green(
                                "💎 اشتراک",
                                "subscription"
                            )
                        ],
                        [
                            red(
                                "🔙 بازگشت",
                                "home"
                            )
                        ]
                    ]
                }
            )

            return

        edit(
            chat_id,
            message_id,
            "⚡ ثبت درخواست\n\n"
            "فقط لینک تلگرام قبول می‌شود.\n\n"
            "مثال:\n"
            "https://t.me/example",
            request_keyboard()
        )

        return

    if data == "request_link":

        set_state(
            user_id,
            "waiting_report_link"
        )

        edit(
            chat_id,
            message_id,
            "🔗 لینک تلگرام را ارسال کن.\n\n"
            "فقط لینک‌های t.me و telegram.me قبول می‌شوند.",
            back_keyboard()
        )

        return

    # =====================================================
    # EMAIL
    # =====================================================

    if data == "email":

        if not check_membership(user_id):

            force_join_message(chat_id)
            return

        if not has_subscription(user_id):

            edit(
                chat_id,
                message_id,
                "❌ برای استفاده از این بخش اشتراک فعال لازم است.",
                {
                    "inline_keyboard": [
                        [
                            green(
                                "💎 اشتراک",
                                "subscription"
                            )
                        ],
                        [
                            red(
                                "🔙 بازگشت",
                                "home"
                            )
                        ]
                    ]
                }
            )

            return

        edit(
            chat_id,
            message_id,
            "📧 بخش ایمیل\n\n"
            "متن موردنظر را ارسال کن.",
            email_keyboard()
        )

        return

    if data == "email_text":

        set_state(
            user_id,
            "waiting_email_text"
        )

        edit(
            chat_id,
            message_id,
            "📧 متن ایمیل را ارسال کن.",
            back_keyboard()
        )

        return

    # =====================================================
    # ACCOUNT
    # =====================================================

    if data == "account":

        edit(
            chat_id,
            message_id,
            "👤 حساب من\n\n"
            f"🆔 آیدی: {user_id}\n\n"
            f"💎 وضعیت:\n{subscription_text(user_id)}",
            back_keyboard()
        )

        return

    if data == "status":

        conn = db()

        try:
            pending = conn.execute("""
                SELECT COUNT(*) AS c
                FROM requests
                WHERE user_id=?
                AND status='pending'
            """, (user_id,)).fetchone()["c"]

            completed = conn.execute("""
                SELECT COUNT(*) AS c
                FROM requests
                WHERE user_id=?
                AND status='completed'
            """, (user_id,)).fetchone()["c"]

        finally:
            conn.close()

        edit(
            chat_id,
            message_id,
            "📊 وضعیت شما\n\n"
            f"⏳ در حال پردازش: {pending}\n"
            f"✅ تکمیل‌شده: {completed}",
            back_keyboard()
        )

        return

    if data == "myid":

        edit(
            chat_id,
            message_id,
            f"🆔 آیدی عددی شما:\n\n{user_id}",
            back_keyboard()
        )

        return

    if data == "support":

        edit(
            chat_id,
            message_id,
            "💬 پشتیبانی\n\n"
            "برای ارتباط با پشتیبانی از راه ارتباطی تعیین‌شده توسط مدیریت استفاده کنید.",
            back_keyboard()
        )

        return

    if data == "subscription":

        edit(
            chat_id,
            message_id,
            "💎 اشتراک\n\n"
            + subscription_text(user_id),
            back_keyboard()
        )

        return


# =========================================================
# MESSAGE HANDLER
# =========================================================

def handle_message(message):

    user = message.get("from")

    if not user:
        return

    user_id = user["id"]
    chat_id = message["chat"]["id"]

    save_user(user)

    text = message.get("text", "").strip()

    # =====================================================
    # START
    # =====================================================

    if text.startswith("/start"):

        clear_state(user_id)
        clear_admin_state(user_id)

        if not check_membership(user_id):

            if force_join_message(chat_id):
                return

        show_home(chat_id)
        return

    # =====================================================
    # ADMIN
    # =====================================================

    if text == "/admin":

        if user_id != ADMIN_ID:

            send(
                chat_id,
                "❌ شما دسترسی مدیریت ندارید."
            )

            return

        clear_state(user_id)
        clear_admin_state(user_id)

        send(
            chat_id,
            "🛠 پنل مدیریت BREAKING REPO",
            admin_keyboard()
        )

        return

    # =====================================================
    # ADMIN STATES
    # =====================================================

    admin_state = get_admin_state(user_id)

    if user_id == ADMIN_ID and admin_state:

        # -------------------------------------------------
        # REPORT LIMIT
        # -------------------------------------------------

        if admin_state == "report_limit":

            try:
                value = int(text)

                if not 1 <= value <= 100:
                    raise ValueError

                set_setting(
                    "report_max",
                    value
                )

                clear_admin_state(user_id)

                send(
                    chat_id,
                    f"✅ سقف ثبت درخواست روی {value} تنظیم شد.",
                    limits_keyboard()
                )

            except Exception:

                send(
                    chat_id,
                    "❌ مقدار اشتباه است.\n\n"
                    "یک عدد بین 1 تا 100 ارسال کن."
                )

            return

        # -------------------------------------------------
        # EMAIL LIMIT
        # -------------------------------------------------

        if admin_state == "email_limit":

            try:
                value = int(text)

                if not 1 <= value <= 100:
                    raise ValueError

                set_setting(
                    "email_max",
                    value
                )

                clear_admin_state(user_id)

                send(
                    chat_id,
                    f"✅ سقف بخش ایمیل روی {value} تنظیم شد.",
                    limits_keyboard()
                )

            except Exception:

                send(
                    chat_id,
                    "❌ مقدار اشتباه است.\n\n"
                    "یک عدد بین 1 تا 100 ارسال کن."
                )

            return

        # -------------------------------------------------
        # ADD SUB
        # -------------------------------------------------

        if admin_state == "add_sub":

            try:
                parts = text.split()

                if len(parts) != 2:
                    raise ValueError

                target_id = int(parts[0])
                days = int(parts[1])

                if target_id <= 0 or days <= 0:
                    raise ValueError

                add_subscription(
                    target_id,
                    days
                )

                clear_admin_state(user_id)

                send(
                    chat_id,
                    "✅ اشتراک اضافه شد.",
                    admin_keyboard()
                )

            except Exception:

                send(
                    chat_id,
                    "❌ فرمت اشتباه است.\n\n"
                    "مثال:\n"
                    "123456789 30"
                )

            return

        # -------------------------------------------------
        # EXTEND SUB
        # -------------------------------------------------

        if admin_state == "extend_sub":

            try:
                parts = text.split()

                if len(parts) != 2:
                    raise ValueError

                target_id = int(parts[0])
                days = int(parts[1])

                if target_id <= 0 or days <= 0:
                    raise ValueError

                add_subscription(
                    target_id,
                    days
                )

                clear_admin_state(user_id)

                send(
                    chat_id,
                    "✅ مدت اشتراک افزایش پیدا کرد.",
                    admin_keyboard()
                )

            except Exception:

                send(
                    chat_id,
                    "❌ فرمت اشتباه است.\n\n"
                    "مثال:\n"
                    "123456789 7"
                )

            return

        # -------------------------------------------------
        # REMOVE SUB
        # -------------------------------------------------

        if admin_state == "remove_sub":

            try:
                target_id = int(text)

                if target_id <= 0:
                    raise ValueError

                remove_subscription(
                    target_id
                )

                clear_admin_state(user_id)

                send(
                    chat_id,
                    "✅ اشتراک حذف شد.",
                    admin_keyboard()
                )

            except Exception:

                send(
                    chat_id,
                    "❌ آیدی نامعتبر است."
                )

            return

        # -------------------------------------------------
        # CHANNEL
        # -------------------------------------------------

        if admin_state == "set_channel":

            channel = text.strip()

            if not channel.startswith("@"):

                send(
                    chat_id,
                    "❌ آیدی کانال باید با @ شروع شود.\n\n"
                    "مثال:\n"
                    "@MyChannel"
                )

                return

            set_setting(
                "force_channel",
                channel
            )

            clear_admin_state(user_id)

            send(
                chat_id,
                f"✅ کانال تنظیم شد:\n\n{channel}",
                force_admin_keyboard()
            )

            return

    # =====================================================
    # USER STATES
    # =====================================================

    state = get_state(user_id)

    if not state:
        return

    current_state = state["state"]

    # =====================================================
    # TELEGRAM LINK
    # =====================================================

    if current_state == "waiting_report_link":

        if not is_telegram_link(text):

            send(
                chat_id,
                "❌ فقط لینک تلگرام قبول می‌شود.\n\n"
                "نمونه صحیح:\n"
                "https://t.me/example"
            )

            return

        set_state(
            user_id,
            "waiting_report_count",
            {
                "target": text
            }
        )

        send(
            chat_id,
            "🔢 تعداد را ارسال کن.\n\n"
            f"حداکثر فعلی: {get_report_max()}\n\n"
            "عدد باید بین 1 و سقف تعیین‌شده باشد.",
            back_keyboard()
        )

        return

    # =====================================================
    # REPORT COUNT
    # =====================================================

    if current_state == "waiting_report_count":

        try:
            count = int(text)

        except Exception:

            send(
                chat_id,
                "❌ فقط عدد ارسال کن."
            )

            return

        maximum = get_report_max()

        if count < 1 or count > maximum:

            send(
                chat_id,
                f"❌ تعداد باید بین 1 تا {maximum} باشد."
            )

            return

        target = state["data"]["target"]

        request_id = create_request(
            user_id,
            "report",
            target,
            count
        )

        clear_state(user_id)

        send(
            chat_id,
            "✅ درخواست شما ثبت شد.\n\n"
            f"🔗 لینک: {target}\n"
            f"🔢 تعداد: {count}\n\n"
            "⏳ پردازش در حال انجام است..."
        )

        threading.Thread(
            target=delayed_result,
            args=(
                chat_id,
                request_id,
                "report"
            ),
            daemon=True
        ).start()

        return

    # =====================================================
    # EMAIL TEXT
    # =====================================================

    if current_state == "waiting_email_text":

        if len(text) < 3:

            send(
                chat_id,
                "❌ متن ایمیل خیلی کوتاه است."
            )

            return

        set_state(
            user_id,
            "waiting_email_count",
            {
                "target": text
            }
        )

        send(
            chat_id,
            "🔢 تعداد را ارسال کن.\n\n"
            f"حداکثر فعلی: {get_email_max()}\n\n"
            "عدد باید بین 1 و سقف تعیین‌شده باشد.",
            back_keyboard()
        )

        return

    # =====================================================
    # EMAIL COUNT
    # =====================================================

    if current_state == "waiting_email_count":

        try:
            count = int(text)

        except Exception:

            send(
                chat_id,
                "❌ فقط عدد ارسال کن."
            )

            return

        maximum = get_email_max()

        if count < 1 or count > maximum:

            send(
                chat_id,
                f"❌ تعداد باید بین 1 تا {maximum} باشد."
            )

            return

        target = state["data"]["target"]

        request_id = create_request(
            user_id,
            "email",
            target,
            count
        )

        clear_state(user_id)

        send(
            chat_id,
            "✅ درخواست شما ثبت شد.\n\n"
            f"🔢 تعداد: {count}\n\n"
            "⏳ پردازش در حال انجام است..."
        )

        threading.Thread(
            target=delayed_result,
            args=(
                chat_id,
                request_id,
                "email"
            ),
            daemon=True
        ).start()

        return


# =========================================================
# UPDATE
# =========================================================

def process_update(update):

    try:

        if "callback_query" in update:

            handle_callback(
                update["callback_query"]
            )

        elif "message" in update:

            handle_message(
                update["message"]
            )

    except Exception as e:

        print(
            "UPDATE ERROR:",
            repr(e)
        )


# =========================================================
# MAIN
# =========================================================

def main():

    print("================================")
    print("BREAKING REPO")
    print("Bot is starting...")
    print("================================")

    # تست اتصال توکن
    me = tg("getMe")

    if not me.get("ok"):

        print("❌ BOT TOKEN یا اتصال مشکل دارد.")
        print(me)

        raise RuntimeError(
            "اتصال به Telegram API برقرار نشد."
        )

    bot_info = me["result"]

    print(
        f"✅ Connected to @{bot_info.get('username', 'unknown')}"
    )

    # حذف webhook قبلی
    delete_result = tg(
        "deleteWebhook",
        {
            "drop_pending_updates": False
        }
    )

    print(
        "Webhook:",
        delete_result
    )

    offset = 0

    while True:

        try:

            result = tg(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": json.dumps([
                        "message",
                        "callback_query"
                    ])
                }
            )

            if not result.get("ok"):

                print(
                    "getUpdates failed:",
                    result
                )

                time.sleep(5)
                continue

            updates = result.get(
                "result",
                []
            )

            for update in updates:

                offset = update["update_id"] + 1

                process_update(update)

        except KeyboardInterrupt:

            print("Bot stopped.")
            break

        except Exception as e:

            print(
                "MAIN LOOP ERROR:",
                repr(e)
            )

            time.sleep(5)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
