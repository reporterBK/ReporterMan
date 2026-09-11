import os
import re
import time
import sqlite3
import threading
import requests
from datetime import datetime, timedelta

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8203764232

DB_FILE = "breaking_repo.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN پیدا نشد.")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# =========================================================
# DATABASE
# =========================================================

def db():
    con = sqlite3.connect(DB_FILE, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            expires_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            target TEXT,
            count INTEGER,
            status TEXT,
            created_at TEXT,
            finish_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            report_text TEXT,
            count INTEGER,
            status TEXT,
            created_at TEXT,
            finish_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    con.commit()
    con.close()


# =========================================================
# SETTINGS
# =========================================================

def get_setting(key, default=""):
    con = db()
    row = con.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()
    con.close()

    return row["value"] if row else default


def set_setting(key, value):
    con = db()

    con.execute("""
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
    """, (key, str(value)))

    con.commit()
    con.close()


# =========================================================
# TELEGRAM
# =========================================================

def tg(method, data=None):
    try:
        r = requests.post(
            f"{API}/{method}",
            json=data or {},
            timeout=30
        )
        return r.json()
    except Exception as e:
        print("Telegram error:", e)
        return {"ok": False}


def send(chat_id, text, keyboard=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    if keyboard:
        data["reply_markup"] = {
            "inline_keyboard": keyboard
        }

    return tg("sendMessage", data)


def edit(chat_id, message_id, text, keyboard=None):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    if keyboard is not None:
        data["reply_markup"] = {
            "inline_keyboard": keyboard
        }

    return tg("editMessageText", data)


def answer(callback_id, text=None):
    data = {
        "callback_query_id": callback_id
    }

    if text:
        data["text"] = text

    return tg("answerCallbackQuery", data)


# =========================================================
# KEYBOARDS
# =========================================================

def home_keyboard():
    return [
        [
            {"text": "⚡ ثبت درخواست", "callback_data": "request"}
        ],
        [
            {"text": "📧 Email Sender", "callback_data": "email"},
            {"text": "💎 اشتراک", "callback_data": "subscription"}
        ],
        [
            {"text": "👤 حساب من", "callback_data": "account"},
            {"text": "🆔 آیدی من", "callback_data": "myid"}
        ],
        [
            {"text": "📊 وضعیت سیستم", "callback_data": "status"},
            {"text": "📞 پشتیبانی", "callback_data": "support"}
        ]
    ]


def back_keyboard():
    return [
        [
            {"text": "🔙 بازگشت", "callback_data": "home"}
        ]
    ]


def cancel_keyboard():
    return [
        [
            {"text": "❌ لغو", "callback_data": "home"}
        ]
    ]


def admin_keyboard():
    return [
        [
            {"text": "👥 کاربران", "callback_data": "a_users"},
            {"text": "📊 آمار", "callback_data": "a_stats"}
        ],
        [
            {"text": "➕ افزودن اشتراک", "callback_data": "a_add"},
            {"text": "➖ حذف اشتراک", "callback_data": "a_remove"}
        ],
        [
            {"text": "⏳ تمدید اشتراک", "callback_data": "a_extend"}
        ],
        [
            {"text": "🔎 جستجوی کاربر", "callback_data": "a_search"}
        ],
        [
            {"text": "🔐 عضویت اجباری", "callback_data": "force"}
        ],
        [
            {"text": "🏠 منوی اصلی", "callback_data": "home"}
        ]
    ]


def force_keyboard():
    enabled = get_setting("force_join", "0") == "1"

    status = "🟢 روشن" if enabled else "🔴 خاموش"

    return [
        [
            {
                "text": f"🔐 عضویت اجباری: {status}",
                "callback_data": "force_toggle"
            }
        ],
        [
            {
                "text": "📢 تنظیم کانال",
                "callback_data": "force_channel"
            }
        ],
        [
            {
                "text": "🔙 بازگشت",
                "callback_data": "admin"
            }
        ]
    ]


# =========================================================
# USERS
# =========================================================

def save_user(user):
    if not user:
        return

    con = db()

    con.execute("""
        INSERT INTO users(
            user_id,
            username,
            first_name,
            joined_at
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
    """, (
        user.get("id"),
        user.get("username", ""),
        user.get("first_name", ""),
        datetime.now().isoformat()
    ))

    con.commit()
    con.close()


def users_count():
    con = db()
    n = con.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]
    con.close()
    return n


# =========================================================
# SUBSCRIPTIONS
# =========================================================

def subscription(user_id):
    con = db()

    row = con.execute(
        "SELECT expires_at FROM subscriptions WHERE user_id=?",
        (user_id,)
    ).fetchone()

    con.close()

    if not row:
        return None

    try:
        expires = datetime.fromisoformat(row["expires_at"])

        if expires > datetime.now():
            return expires

    except Exception:
        pass

    return None


def has_access(user_id):
    if user_id == ADMIN_ID:
        return True

    return subscription(user_id) is not None


def add_subscription(user_id, days):
    current = subscription(user_id)

    if current:
        expires = current + timedelta(days=days)
    else:
        expires = datetime.now() + timedelta(days=days)

    con = db()

    con.execute("""
        INSERT INTO subscriptions(user_id, expires_at)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET expires_at=excluded.expires_at
    """, (
        user_id,
        expires.isoformat()
    ))

    con.commit()
    con.close()

    return expires


def remove_subscription(user_id):
    con = db()

    con.execute(
        "DELETE FROM subscriptions WHERE user_id=?",
        (user_id,)
    )

    con.commit()
    con.close()


# =========================================================
# FORCE JOIN
# =========================================================

def force_enabled():
    return get_setting("force_join", "0") == "1"


def force_channel():
    return get_setting("force_channel", "")


def is_member(user_id):
    if user_id == ADMIN_ID:
        return True

    if not force_enabled():
        return True

    channel = force_channel()

    if not channel:
        return True

    if not channel.startswith("@"):
        channel = "@" + channel

    result = tg("getChatMember", {
        "chat_id": channel,
        "user_id": user_id
    })

    if not result.get("ok"):
        return False

    status = result.get("result", {}).get("status")

    return status in [
        "member",
        "administrator",
        "creator"
    ]


def force_join(chat_id):
    channel = force_channel()

    if not channel:
        channel = "@YourChannel"

    username = channel.replace("@", "")

    keyboard = [
        [
            {
                "text": "📢 عضویت در کانال",
                "url": f"https://t.me/{username}"
            }
        ],
        [
            {
                "text": "✅ عضو شدم",
                "callback_data": "check_join"
            }
        ]
    ]

    send(
        chat_id,
        """
<b>🔐 عضویت در کانال</b>

برای استفاده از ربات ابتدا در کانال زیر عضو شوید.

━━━━━━━━━━━━━━━━━━

🔵 1️⃣ روی «عضویت در کانال» بزنید.
🟢 2️⃣ عضو کانال شوید.
🟢 3️⃣ سپس «عضو شدم» را بزنید.

━━━━━━━━━━━━━━━━━━
""",
        keyboard
    )


def require_join(chat_id, user_id):
    if is_member(user_id):
        return True

    force_join(chat_id)
    return False


# =========================================================
# STATES
# =========================================================

states = {}


def state(chat_id, name, **data):
    states[chat_id] = {
        "state": name,
        **data
    }


def clear_state(chat_id):
    states.pop(chat_id, None)


# =========================================================
# HOME
# =========================================================

def home(chat_id, user):
    save_user(user)
    clear_state(chat_id)

    send(
        chat_id,
        """
<b>⚡ BREAKING REPO</b>

━━━━━━━━━━━━━━━━━━

<b>خوش اومدی 👋</b>

از منوی زیر بخش موردنظر خودت رو انتخاب کن.

━━━━━━━━━━━━━━━━━━

🟢 سیستم آنلاین
⚡ سرویس فعال
🔐 دسترسی اشتراکی
""",
        home_keyboard()
    )


# =========================================================
# REQUEST
# =========================================================

def open_request(chat_id, user_id):
    if not require_join(chat_id, user_id):
        return

    if not has_access(user_id):
        send(
            chat_id,
            """
<b>🔒 دسترسی محدود</b>

برای استفاده از این بخش اشتراک فعال لازم است.

💎 برای فعال‌سازی با پشتیبانی تماس بگیرید.
""",
            [
                [
                    {
                        "text": "📞 پشتیبانی",
                        "callback_data": "support"
                    }
                ],
                [
                    {
                        "text": "🔙 بازگشت",
                        "callback_data": "home"
                    }
                ]
            ]
        )
        return

    state(chat_id, "request_link")

    send(
        chat_id,
        """
<b>⚡ ثبت درخواست</b>

فقط لینک موردنظر را ارسال کنید.

━━━━━━━━━━━━━━━━━━

🔗 نمونه:
<code>https://example.com/...</code>

❗ هیچ متن دیگری پذیرفته نمی‌شود.
""",
        cancel_keyboard()
    )


def valid_link(text):
    if not text:
        return False

    text = text.strip()

    if " " in text:
        return False

    return bool(
        re.match(
            r"^(https?://|www\.)[^\s]+$",
            text,
            re.IGNORECASE
        )
    )


def create_request(user_id, link, count):
    now = datetime.now()

    finish = now + timedelta(
        seconds=300
    )

    con = db()

    cur = con.execute("""
        INSERT INTO requests(
            user_id,
            target,
            count,
            status,
            created_at,
            finish_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        link,
        count,
        "pending",
        now.isoformat(),
        finish.isoformat()
    ))

    request_id = cur.lastrowid

    con.commit()
    con.close()

    return request_id


# =========================================================
# EMAIL REQUEST
# =========================================================

def open_email(chat_id, user_id):
    if not require_join(chat_id, user_id):
        return

    if not has_access(user_id):
        send(
            chat_id,
            """
<b>🔒 دسترسی محدود</b>

برای استفاده از Email Sender اشتراک فعال لازم است.
""",
            back_keyboard()
        )
        return

    state(chat_id, "email_text")

    send(
        chat_id,
        """
<b>📧 Email Sender</b>

متن گزارش را وارد کنید:

━━━━━━━━━━━━━━━━━━

📝 متن موردنظر را در یک پیام ارسال کنید.
""",
        cancel_keyboard()
    )


def create_email(user_id, text, count):
    now = datetime.now()

    finish = now + timedelta(
        seconds=330
    )

    con = db()

    cur = con.execute("""
        INSERT INTO email_requests(
            user_id,
            report_text,
            count,
            status,
            created_at,
            finish_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        text,
        count,
        "pending",
        now.isoformat(),
        finish.isoformat()
    ))

    request_id = cur.lastrowid

    con.commit()
    con.close()

    return request_id


# =========================================================
# PROCESSOR
# =========================================================

def processor():
    while True:

        try:
            now = datetime.now().isoformat()

            # ---------------- REQUESTS ----------------

            con = db()

            rows = con.execute("""
                SELECT *
                FROM requests
                WHERE status='pending'
                AND finish_at <= ?
                LIMIT 20
            """, (now,)).fetchall()

            con.close()

            for row in rows:

                con = db()

                con.execute("""
                    UPDATE requests
                    SET status='completed'
                    WHERE id=?
                """, (row["id"],))

                con.commit()
                con.close()

                send(
                    row["user_id"],
                    f"""
<b>✅ پردازش درخواست تکمیل شد</b>

━━━━━━━━━━━━━━━━━━

🔗 لینک:
<code>{row["target"]}</code>

📊 تعداد:
<b>{row["count"]}/{row["count"]}</b>

🟢 وضعیت پردازش داخلی: تکمیل شد

━━━━━━━━━━━━━━━━━━
""",
                    [
                        [
                            {
                                "text": "⚡ درخواست جدید",
                                "callback_data": "request"
                            }
                        ],
                        [
                            {
                                "text": "🏠 منوی اصلی",
                                "callback_data": "home"
                            }
                        ]
                    ]
                )

            # ---------------- EMAIL ----------------

            con = db()

            rows = con.execute("""
                SELECT *
                FROM email_requests
                WHERE status='pending'
                AND finish_at <= ?
                LIMIT 20
            """, (now,)).fetchall()

            con.close()

            for row in rows:

                con = db()

                con.execute("""
                    UPDATE email_requests
                    SET status='completed'
                    WHERE id=?
                """, (row["id"],))

                con.commit()
                con.close()

                send(
                    row["user_id"],
                    f"""
<b>📧 پردازش Email Sender تکمیل شد</b>

━━━━━━━━━━━━━━━━━━

📊 تعداد پردازش:
<b>{row["count"]}/{row["count"]}</b>

🟢 وضعیت پردازش داخلی: تکمیل شد

━━━━━━━━━━━━━━━━━━
""",
                    [
                        [
                            {
                                "text": "📧 درخواست جدید",
                                "callback_data": "email"
                            }
                        ],
                        [
                            {
                                "text": "🏠 منوی اصلی",
                                "callback_data": "home"
                            }
                        ]
                    ]
                )

        except Exception as e:
            print("Processor:", repr(e))

        time.sleep(5)


# =========================================================
# ADMIN
# =========================================================

def admin_panel(chat_id, user_id):

    if user_id != ADMIN_ID:
        send(
            chat_id,
            "❌ شما دسترسی ادمین ندارید.",
            back_keyboard()
        )
        return

    clear_state(chat_id)

    send(
        chat_id,
        """
<b>👑 پنل مدیریت BREAKING REPO</b>

━━━━━━━━━━━━━━━━━━

🔵 مدیریت کاربران
📊 آمار سیستم
💎 مدیریت اشتراک
🔐 عضویت اجباری

━━━━━━━━━━━━━━━━━━
""",
        admin_keyboard()
    )


def admin_stats(chat_id):

    con = db()

    users = con.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    requests = con.execute(
        "SELECT COUNT(*) FROM requests"
    ).fetchone()[0]

    emails = con.execute(
        "SELECT COUNT(*) FROM email_requests"
    ).fetchone()[0]

    pending = con.execute("""
        SELECT
        (SELECT COUNT(*) FROM requests WHERE status='pending')
        +
        (SELECT COUNT(*) FROM email_requests WHERE status='pending')
    """).fetchone()[0]

    con.close()

    send(
        chat_id,
        f"""
<b>📊 آمار سیستم</b>

━━━━━━━━━━━━━━━━━━

👥 کاربران:
<b>{users}</b>

⚡ درخواست‌ها:
<b>{requests}</b>

📧 درخواست‌های ایمیل:
<b>{emails}</b>

⏳ در حال پردازش:
<b>{pending}</b>

━━━━━━━━━━━━━━━━━━
""",
        [
            [
                {
                    "text": "🔄 بروزرسانی",
                    "callback_data": "a_stats"
                }
            ],
            [
                {
                    "text": "🔙 پنل مدیریت",
                    "callback_data": "admin"
                }
            ]
        ]
    )


# =========================================================
# USER MANAGEMENT
# =========================================================

def admin_users(chat_id):

    send(
        chat_id,
        f"""
<b>👥 کاربران</b>

━━━━━━━━━━━━━━━━━━

تعداد کاربران:
<b>{users_count()}</b>

━━━━━━━━━━━━━━━━━━
""",
        [
            [
                {
                    "text": "🔙 پنل مدیریت",
                    "callback_data": "admin"
                }
            ]
        ]
    )


def admin_add_start(chat_id):

    state(chat_id, "admin_add_user")

    send(
        chat_id,
        """
<b>➕ افزودن اشتراک</b>

آیدی عددی کاربر را ارسال کنید.
""",
        cancel_keyboard()
    )


def admin_remove_start(chat_id):

    state(chat_id, "admin_remove_user")

    send(
        chat_id,
        """
<b>➖ حذف اشتراک</b>

آیدی عددی کاربر را ارسال کنید.
""",
        cancel_keyboard()
    )


def admin_extend_start(chat_id):

    state(chat_id, "admin_extend_user")

    send(
        chat_id,
        """
<b>⏳ تمدید اشتراک</b>

آیدی عددی کاربر را ارسال کنید.
""",
        cancel_keyboard()
    )


def admin_search_start(chat_id):

    state(chat_id, "admin_search")

    send(
        chat_id,
        """
<b>🔎 جستجوی کاربر</b>

آیدی عددی کاربر را ارسال کنید.
""",
        cancel_keyboard()
    )


# =========================================================
# UPDATE ADMIN STATES
# =========================================================

def handle_admin_text(chat_id, user_id, text):

    if user_id != ADMIN_ID:
        return False

    s = states.get(chat_id)

    if not s:
        return False

    current = s.get("state")

    # ---------------- ADD ----------------

    if current == "admin_add_user":

        if not text.isdigit():
            send(chat_id, "❌ آیدی باید عددی باشد.", cancel_keyboard())
            return True

        target = int(text)

        state(
            chat_id,
            "admin_add_days",
            target=target
        )

        send(
            chat_id,
            """
<b>➕ تعداد روز اشتراک</b>

تعداد روز را ارسال کنید.
""",
            cancel_keyboard()
        )

        return True

    if current == "admin_add_days":

        if not text.isdigit():
            send(chat_id, "❌ تعداد روز نامعتبر است.", cancel_keyboard())
            return True

        days = int(text)

        if days <= 0:
            send(chat_id, "❌ تعداد روز باید بیشتر از صفر باشد.")
            return True

        target = s["target"]

        expires = add_subscription(target, days)

        clear_state(chat_id)

        send(
            chat_id,
            f"""
<b>✅ اشتراک اضافه شد</b>

👤 کاربر:
<code>{target}</code>

⏳ مدت:
<b>{days} روز</b>

📅 پایان:
<code>{expires.strftime("%Y-%m-%d %H:%M")}</code>
""",
            admin_keyboard()
        )

        send(
            target,
            f"""
<b>💎 اشتراک شما فعال شد</b>

⏳ مدت:
<b>{days} روز</b>

📅 اعتبار تا:
<code>{expires.strftime("%Y-%m-%d %H:%M")}</code>
"""
        )

        return True

    # ---------------- REMOVE ----------------

    if current == "admin_remove_user":

        if not text.isdigit():
            send(chat_id, "❌ آیدی نامعتبر است.", cancel_keyboard())
            return True

        target = int(text)

        remove_subscription(target)

        clear_state(chat_id)

        send(
            chat_id,
            f"""
<b>🔴 اشتراک حذف شد</b>

👤 آیدی:
<code>{target}</code>
""",
            admin_keyboard()
        )

        return True

    # ---------------- EXTEND ----------------

    if current == "admin_extend_user":

        if not text.isdigit():
            send(chat_id, "❌ آیدی نامعتبر است.", cancel_keyboard())
            return True

        target = int(text)

        state(
            chat_id,
            "admin_extend_days",
            target=target
        )

        send(
            chat_id,
            "⏳ چند روز تمدید شود؟",
            cancel_keyboard()
        )

        return True

    if current == "admin_extend_days":

        if not text.isdigit():
            send(chat_id, "❌ تعداد روز نامعتبر است.", cancel_keyboard())
            return True

        days = int(text)

        if days <= 0:
            send(chat_id, "❌ تعداد روز نامعتبر است.")
            return True

        target = s["target"]

        expires = add_subscription(target, days)

        clear_state(chat_id)

        send(
            chat_id,
            f"""
<b>✅ اشتراک تمدید شد</b>

👤 کاربر:
<code>{target}</code>

➕ تمدید:
<b>{days} روز</b>

📅 اعتبار تا:
<code>{expires.strftime("%Y-%m-%d %H:%M")}</code>
""",
            admin_keyboard()
        )

        return True

    # ---------------- SEARCH ----------------

    if current == "admin_search":

        if not text.isdigit():
            send(chat_id, "❌ آیدی باید عددی باشد.", cancel_keyboard())
            return True

        target = int(text)

        con = db()

        user = con.execute(
            "SELECT * FROM users WHERE user_id=?",
            (target,)
        ).fetchone()

        con.close()

        sub = subscription(target)

        if user:
            username = user["username"] or "ندارد"
            name = user["first_name"] or "ندارد"
        else:
            username = "یافت نشد"
            name = "یافت نشد"

        sub_text = (
            sub.strftime("%Y-%m-%d %H:%M")
            if sub else
            "ندارد"
        )

        clear_state(chat_id)

        send(
            chat_id,
            f"""
<b>🔎 اطلاعات کاربر</b>

━━━━━━━━━━━━━━━━━━

🆔 ID:
<code>{target}</code>

👤 نام:
{name}

🔹 Username:
@{username if username != "یافت نشد" else username}

💎 اشتراک:
<code>{sub_text}</code>

━━━━━━━━━━━━━━━━━━
""",
            admin_keyboard()
        )

        return True

    # ---------------- FORCE CHANNEL ----------------

    if current == "force_channel":

        channel = text.strip()

        if channel.startswith("https://t.me/"):
            channel = "@" + channel.split("/")[-1]

        if not channel.startswith("@"):
            channel = "@" + channel

        set_setting("force_channel", channel)

        clear_state(chat_id)

        send(
            chat_id,
            f"""
<b>✅ کانال ذخیره شد</b>

📢 کانال:
<code>{channel}</code>
""",
            force_keyboard()
        )

        return True

    return False


# =========================================================
# CALLBACKS
# =========================================================

def callback_handler(callback):

    callback_id = callback["id"]

    data = callback.get("data", "")
    message = callback.get("message", {})

    chat = message.get("chat", {})
    chat_id = chat.get("id")

    user = callback.get("from", {})
    user_id = user.get("id")

    save_user(user)

    answer(callback_id)

    # ---------------- HOME ----------------

    if data == "home":
        home(chat_id, user)
        return

    # ---------------- JOIN CHECK ----------------

    if data == "check_join":

        if is_member(user_id):
            answer(callback_id, "✅ عضویت تأیید شد.")

            send(
                chat_id,
                """
<b>✅ عضویت تأیید شد</b>

حالا می‌توانید از منوی اصلی استفاده کنید.
""",
                home_keyboard()
            )
        else:
            answer(
                callback_id,
                "❌ هنوز عضویت شما تأیید نشده است."
            )

        return

    # ---------------- ADMIN ----------------

    if data == "admin":

        if user_id != ADMIN_ID:
            return

        admin_panel(chat_id, user_id)
        return

    if data == "a_users":

        if user_id == ADMIN_ID:
            admin_users(chat_id)

        return

    if data == "a_stats":

        if user_id == ADMIN_ID:
            admin_stats(chat_id)

        return

    if data == "a_add":

        if user_id == ADMIN_ID:
            admin_add_start(chat_id)

        return

    if data == "a_remove":

        if user_id == ADMIN_ID:
            admin_remove_start(chat_id)

        return

    if data == "a_extend":

        if user_id == ADMIN_ID:
            admin_extend_start(chat_id)

        return

    if data == "a_search":

        if user_id == ADMIN_ID:
            admin_search_start(chat_id)

        return

    # ---------------- FORCE JOIN ----------------

    if data == "force":

        if user_id != ADMIN_ID:
            return

        send(
            chat_id,
            """
<b>🔐 مدیریت عضویت اجباری</b>

از گزینه‌های زیر استفاده کنید.
""",
            force_keyboard()
        )

        return

    if data == "force_toggle":

        if user_id != ADMIN_ID:
            return

        current = get_setting("force_join", "0")

        set_setting(
            "force_join",
            "0" if current == "1" else "1"
        )

        send(
            chat_id,
            "<b>✅ وضعیت عضویت اجباری تغییر کرد.</b>",
            force_keyboard()
        )

        return

    if data == "force_channel":

        if user_id != ADMIN_ID:
            return

        state(chat_id, "force_channel")

        send(
            chat_id,
            """
<b>📢 تنظیم کانال عضویت</b>

آیدی کانال را ارسال کنید.

مثال:
<code>@YourChannel</code>
""",
            cancel_keyboard()
        )

        return

    # ---------------- REQUEST ----------------

    if data == "request":

        open_request(chat_id, user_id)
        return

    # ---------------- EMAIL ----------------

    if data == "email":

        open_email(chat_id, user_id)
        return

    # ---------------- SUBSCRIPTION ----------------

    if data == "subscription":

        if not require_join(chat_id, user_id):
            return

        expires = subscription(user_id)

        if expires:

            send(
                chat_id,
                f"""
<b>💎 اشتراک شما</b>

━━━━━━━━━━━━━━━━━━

🟢 وضعیت: فعال

📅 اعتبار تا:
<code>{expires.strftime("%Y-%m-%d %H:%M")}</code>

━━━━━━━━━━━━━━━━━━
""",
                back_keyboard()
            )

        else:

            send(
                chat_id,
                """
<b>💎 اشتراک</b>

━━━━━━━━━━━━━━━━━━

🔴 اشتراک فعالی ندارید.

برای فعال‌سازی با پشتیبانی تماس بگیرید.
""",
                [
                    [
                        {
                            "text": "📞 پشتیبانی",
                            "callback_data": "support"
                        }
                    ],
                    [
                        {
                            "text": "🔙 بازگشت",
                            "callback_data": "home"
                        }
                    ]
                ]
            )

        return

    # ---------------- ACCOUNT ----------------

    if data == "account":

        if not require_join(chat_id, user_id):
            return

        con = db()

        total = con.execute(
            "SELECT COUNT(*) FROM requests WHERE user_id=?",
            (user_id,)
        ).fetchone()[0]

        completed = con.execute(
            "SELECT COUNT(*) FROM requests WHERE user_id=? AND status='completed'",
            (user_id,)
        ).fetchone()[0]

        con.close()

        expires = subscription(user_id)

        sub = (
            "🟢 فعال"
            if expires
            else
            "🔴 غیرفعال"
        )

        send(
            chat_id,
            f"""
<b>👤 حساب من</b>

━━━━━━━━━━━━━━━━━━

🆔 آیدی:
<code>{user_id}</code>

💎 اشتراک:
{sub}

📦 کل درخواست‌ها:
<b>{total}</b>

✅ تکمیل‌شده:
<b>{completed}</b>

━━━━━━━━━━━━━━━━━━
""",
            back_keyboard()
        )

        return

    # ---------------- MY ID ----------------

    if data == "myid":

        send(
            chat_id,
            f"""
<b>🆔 آیدی شما</b>

<code>{user_id}</code>
""",
            back_keyboard()
        )

        return

    # ---------------- STATUS ----------------

    if data == "status":

        con = db()

        pending1 = con.execute(
            "SELECT COUNT(*) FROM requests WHERE status='pending'"
        ).fetchone()[0]

        pending2 = con.execute(
            "SELECT COUNT(*) FROM email_requests WHERE status='pending'"
        ).fetchone()[0]

        con.close()

        send(
            chat_id,
            f"""
<b>📊 وضعیت سیستم</b>

━━━━━━━━━━━━━━━━━━

🟢 ربات: آنلاین

⚡ درخواست‌های در حال پردازش:
<b>{pending1}</b>

📧 پردازش‌های ایمیل:
<b>{pending2}</b>

👥 کاربران:
<b>{users_count()}</b>

━━━━━━━━━━━━━━━━━━
""",
            back_keyboard()
        )

        return

    # ---------------- SUPPORT ----------------

    if data == "support":

        support = get_setting(
            "support",
            "@YourSupport"
        )

        send(
            chat_id,
            f"""
<b>📞 پشتیبانی</b>

برای ارتباط با پشتیبانی:

{support}
""",
            back_keyboard()
        )

        return


# =========================================================
# TEXT HANDLER
# =========================================================

def handle_message(message):

    chat = message.get("chat", {})
    chat_id = chat.get("id")

    user = message.get("from", {})
    user_id = user.get("id")

    text = message.get("text", "")

    save_user(user)

    # ---------------- START ----------------

    if text == "/start":

        if not require_join(chat_id, user_id):
            return

        home(chat_id, user)
        return

    # ---------------- ADMIN COMMAND ----------------

    if text == "/admin":

        if user_id == ADMIN_ID:
            admin_panel(chat_id, user_id)
        else:
            send(chat_id, "❌ دسترسی ندارید.")

        return

    # ---------------- STATE ----------------

    s = states.get(chat_id)

    if s:

        current = s.get("state")

        # ADMIN STATES
        if user_id == ADMIN_ID:

            if handle_admin_text(
                chat_id,
                user_id,
                text
            ):
                return

        # ---------------- REQUEST LINK ----------------

        if current == "request_link":

            if not valid_link(text):

                send(
                    chat_id,
                    """
<b>❌ لینک نامعتبر</b>

فقط یک لینک معتبر ارسال کنید.

مثال:
<code>https://example.com/...</code>
""",
                    cancel_keyboard()
                )

                return

            state(
                chat_id,
                "request_count",
                link=text.strip()
            )

            send(
                chat_id,
                """
<b>🔢 تعداد درخواست</b>

یک عدد بین <b>1 تا 40</b> ارسال کنید.
""",
                cancel_keyboard()
            )

            return

        # ---------------- REQUEST COUNT ----------------

        if current == "request_count":

            if not text.isdigit():

                send(
                    chat_id,
                    "❌ فقط عدد وارد کنید.",
                    cancel_keyboard()
                )

                return

            count = int(text)

            if count < 1 or count > 40:

                send(
                    chat_id,
                    "❌ تعداد باید بین 1 تا 40 باشد.",
                    cancel_keyboard()
                )

                return

            link = s["link"]

            request_id = create_request(
                user_id,
                link,
                count
            )

            clear_state(chat_id)

            send(
                chat_id,
                f"""
<b>🟢 درخواست ثبت شد</b>

━━━━━━━━━━━━━━━━━━

🔗 لینک:
<code>{link}</code>

📊 تعداد:
<b>{count}</b>

🆔 شماره درخواست:
<code>#{request_id}</code>

⏳ زمان پردازش: حدود ۵ تا ۶ دقیقه

━━━━━━━━━━━━━━━━━━
""",
                [
                    [
                        {
                            "text": "🏠 منوی اصلی",
                            "callback_data": "home"
                        }
                    ]
                ]
            )

            return

        # ---------------- EMAIL TEXT ----------------

        if current == "email_text":

            if not text.strip():

                send(
                    chat_id,
                    "❌ متن گزارش نمی‌تواند خالی باشد.",
                    cancel_keyboard()
                )

                return

            state(
                chat_id,
                "email_count",
                report_text=text.strip()
            )

            send(
                chat_id,
                """
<b>🔢 تعداد پردازش</b>

یک عدد بین <b>1 تا 270</b> انتخاب کنید.
""",
                cancel_keyboard()
            )

            return

        # ---------------- EMAIL COUNT ----------------

        if current == "email_count":

            if not text.isdigit():

                send(
                    chat_id,
                    "❌ فقط عدد وارد کنید.",
                    cancel_keyboard()
                )

                return

            count = int(text)

            if count < 1 or count > 270:

                send(
                    chat_id,
                    "❌ تعداد باید بین 1 تا 270 باشد.",
                    cancel_keyboard()
                )

                return

            report_text = s["report_text"]

            request_id = create_email(
                user_id,
                report_text,
                count
            )

            clear_state(chat_id)

            send(
                chat_id,
                f"""
<b>📧 پردازش شروع شد</b>

━━━━━━━━━━━━━━━━━━

📊 تعداد:
<b>{count}</b>

🆔 شماره درخواست:
<code>#{request_id}</code>

⏳ نتیجه پس از پردازش ارسال می‌شود.

━━━━━━━━━━━━━━━━━━
""",
                [
                    [
                        {
                            "text": "🏠 منوی اصلی",
                            "callback_data": "home"
                        }
                    ]
                ]
            )

            return

    # ---------------- NORMAL TEXT ----------------

    if text and not text.startswith("/"):
        send(
            chat_id,
            """
<b>❌ دستور نامعتبر</b>

از دکمه‌های منوی اصلی استفاده کنید.
""",
            home_keyboard()
        )


# =========================================================
# POLLING
# =========================================================

def polling():

    print("🟢 BREAKING REPO started")
    print("👑 ADMIN:", ADMIN_ID)

    tg(
        "deleteWebhook",
        {
            "drop_pending_updates": True
        }
    )

    offset = None

    while True:

        try:

            result = tg(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 30
                }
            )

            if not result.get("ok"):
                time.sleep(3)
                continue

            for update in result.get("result", []):

                offset = update["update_id"] + 1

                if "callback_query" in update:

                    try:
                        callback_handler(
                            update["callback_query"]
                        )
                    except Exception as e:
                        print(
                            "Callback Error:",
                            repr(e)
                        )

                    continue

                message = update.get("message")

                if message:

                    try:
                        handle_message(message)
                    except Exception as e:
                        print(
                            "Message Error:",
                            repr(e)
                        )

        except Exception as e:

            print(
                "Polling Error:",
                repr(e)
            )

            time.sleep(3)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    init_db()

    # پردازش درخواست‌های زمان‌دار
    threading.Thread(
        target=processor,
        daemon=True
    ).start()

    # شروع ربات
    polling()
