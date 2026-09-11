import os
import time
import sqlite3
import threading
import requests
from datetime import datetime, timedelta

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8203764232

DB_FILE = "breaking_repo.db"

# مقدار پیش‌فرض
DEFAULT_REPORT_MAX = 100
DEFAULT_EMAIL_MAX = 100

# زمان پردازش داخلی
PROCESS_DELAY = 330

if not TOKEN:
    raise RuntimeError("BOT_TOKEN پیدا نشد.")

API = f"https://api.telegram.org/bot{TOKEN}"


# =========================
# DATABASE
# =========================

def db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
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
            user_id INTEGER,
            kind TEXT,
            target TEXT,
            count INTEGER,
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

    # تنظیمات اولیه
    cur.execute(
        "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
        ("force_join", "0")
    )

    cur.execute(
        "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
        ("force_channel", "")
    )

    cur.execute(
        "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
        ("report_max", str(DEFAULT_REPORT_MAX))
    )

    cur.execute(
        "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
        ("email_max", str(DEFAULT_EMAIL_MAX))
    )

    conn.commit()
    conn.close()


init_db()


# =========================
# TELEGRAM API
# =========================

def tg(method, data=None):
    try:
        r = requests.post(
            f"{API}/{method}",
            data=data or {},
            timeout=30
        )
        return r.json()
    except Exception:
        return {}


def send(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return tg("sendMessage", data)


def edit(chat_id, message_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return tg("editMessageText", data)


def answer(callback_id, text=""):
    return tg(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text
        }
    )


# =========================
# BUTTON COLORS
# =========================

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


# =========================
# SETTINGS
# =========================

def get_setting(key, default=None):
    conn = db()
    row = conn.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()
    conn.close()

    if row:
        return row["value"]

    return default


def set_setting(key, value):
    conn = db()

    conn.execute("""
        INSERT INTO settings(key,value)
        VALUES(?,?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
    """, (key, str(value)))

    conn.commit()
    conn.close()


def get_report_max():
    try:
        return max(1, min(100, int(get_setting(
            "report_max",
            DEFAULT_REPORT_MAX
        ))))
    except:
        return DEFAULT_REPORT_MAX


def get_email_max():
    try:
        return max(1, min(100, int(get_setting(
            "email_max",
            DEFAULT_EMAIL_MAX
        ))))
    except:
        return DEFAULT_EMAIL_MAX


# =========================
# USERS
# =========================

def save_user(user):
    conn = db()

    conn.execute("""
        INSERT INTO users(user_id, username, first_name, joined_at)
        VALUES(?,?,?,?)
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
    conn.close()


def users_count():
    conn = db()
    value = conn.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]
    conn.close()
    return value


def requests_count():
    conn = db()
    value = conn.execute(
        "SELECT COUNT(*) AS c FROM requests"
    ).fetchone()["c"]
    conn.close()
    return value


# =========================
# SUBSCRIPTIONS
# =========================

def add_subscription(user_id, days):
    conn = db()

    expires = datetime.now() + timedelta(days=days)

    old = conn.execute(
        "SELECT expires_at FROM subscriptions WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if old:
        try:
            old_date = datetime.fromisoformat(old["expires_at"])

            if old_date > datetime.now():
                expires = old_date + timedelta(days=days)
        except:
            pass

    conn.execute("""
        INSERT INTO subscriptions(user_id, expires_at)
        VALUES(?,?)
        ON CONFLICT(user_id)
        DO UPDATE SET expires_at=excluded.expires_at
    """, (
        user_id,
        expires.isoformat()
    ))

    conn.commit()
    conn.close()


def remove_subscription(user_id):
    conn = db()

    conn.execute(
        "DELETE FROM subscriptions WHERE user_id=?",
        (user_id,)
    )

    conn.commit()
    conn.close()


def has_subscription(user_id):
    conn = db()

    row = conn.execute(
        "SELECT expires_at FROM subscriptions WHERE user_id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    if not row:
        return False

    try:
        return datetime.fromisoformat(
            row["expires_at"]
        ) > datetime.now()
    except:
        return False


def subscription_text(user_id):
    conn = db()

    row = conn.execute(
        "SELECT expires_at FROM subscriptions WHERE user_id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    if not row:
        return "❌ اشتراک فعال ندارید."

    try:
        expires = datetime.fromisoformat(row["expires_at"])

        if expires <= datetime.now():
            return "❌ اشتراک شما منقضی شده است."

        return (
            "✅ اشتراک فعال است\n\n"
            f"📅 انقضا: {expires.strftime('%Y-%m-%d %H:%M')}"
        )

    except:
        return "❌ اطلاعات اشتراک قابل خواندن نیست."


# =========================
# REQUESTS
# =========================

def create_request(user_id, kind, target, count):
    conn = db()

    cur = conn.execute("""
        INSERT INTO requests(
            user_id,
            kind,
            target,
            count,
            status,
            created_at
        )
        VALUES(?,?,?,?,?,?)
    """, (
        user_id,
        kind,
        target,
        count,
        "pending",
        datetime.now().isoformat()
    ))

    request_id = cur.lastrowid

    conn.commit()
    conn.close()

    return request_id


def complete_request(request_id):
    conn = db()

    conn.execute("""
        UPDATE requests
        SET status='completed'
        WHERE id=?
    """, (request_id,))

    conn.commit()
    conn.close()


def delayed_result(chat_id, request_id, kind):
    time.sleep(PROCESS_DELAY)

    complete_request(request_id)

    if kind == "report":
        text = (
            "✅ پردازش داخلی انجام شد.\n\n"
            "درخواست شما با موفقیت ثبت و پردازش شد."
        )
    else:
        text = (
            "✅ پردازش داخلی انجام شد.\n\n"
            "متن ایمیل شما با موفقیت ثبت و پردازش شد."
        )

    send(
        chat_id,
        text,
        home_keyboard()
    )


# =========================
# TELEGRAM LINK VALIDATION
# =========================

def is_telegram_link(text):
    text = text.strip().lower()

    if not (
        text.startswith("https://t.me/")
        or text.startswith("http://t.me/")
        or text.startswith("https://telegram.me/")
        or text.startswith("http://telegram.me/")
    ):
        return False

    # نباید لینک خالی باشد
    if text.endswith("/"):
        return False

    # لینک‌های تلگرام
    blocked = [
        "t.me/addstickers/",
        "t.me/share/",
        "t.me/iv",
        "t.me/s/",
        "telegram.me/addstickers/",
        "telegram.me/share/"
    ]

    for item in blocked:
        if item in text:
            return False

    return True


# =========================
# KEYBOARDS
# =========================

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
                blue("🔗 ثبت لینک تلگرام", "request_link")
            ],
            [
                red("🔙 بازگشت", "home")
            ]
        ]
    }


def email_keyboard():
    return {
        "inline_keyboard": [
            [
                blue("📧 ثبت متن ایمیل", "email_text")
            ],
            [
                red("🔙 بازگشت", "home")
            ]
        ]
    }


def back_keyboard():
    return {
        "inline_keyboard": [
            [
                red("🔙 بازگشت", "home")
            ]
        ]
    }


def admin_keyboard():
    return {
        "inline_keyboard": [
            [
                blue("👥 تعداد کاربران", "admin_users"),
                blue("📊 آمار درخواست‌ها", "admin_stats")
            ],
            [
                green("💎 افزودن اشتراک", "admin_add_sub"),
                red("❌ حذف اشتراک", "admin_remove_sub")
            ],
            [
                green("➕ افزایش اشتراک", "admin_extend_sub"),
                blue("📢 عضویت اجباری", "admin_force")
            ],
            [
                blue("⚙️ تنظیمات تعداد", "admin_limits")
            ],
            [
                red("🔙 بازگشت", "home")
            ]
        ]
    }


def force_admin_keyboard():
    status = get_setting("force_join", "0")

    status_text = (
        "🟢 عضویت اجباری: روشن"
        if status == "1"
        else
        "🔴 عضویت اجباری: خاموش"
    )

    return {
        "inline_keyboard": [
            [
                green(status_text, "admin_toggle_force")
            ],
            [
                blue("📢 تنظیم کانال", "admin_set_channel")
            ],
            [
                red("🔙 بازگشت", "admin")
            ]
        ]
    }


def limits_keyboard():
    return {
        "inline_keyboard": [
            [
                blue(
                    f"📌 حد ثبت درخواست: {get_report_max()}",
                    "admin_report_limit"
                )
            ],
            [
                green(
                    f"📧 حد بخش ایمیل: {get_email_max()}",
                    "admin_email_limit"
                )
            ],
            [
                red("🔙 بازگشت", "admin")
            ]
        ]
    }


# =========================
# FORCE JOIN
# =========================

def check_membership(user_id):
    force = get_setting("force_join", "0")
    channel = get_setting("force_channel", "")

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

        return status in [
            "creator",
            "administrator",
            "member"
        ]

    except:
        return False


def force_join_message(chat_id):
    channel = get_setting("force_channel", "")

    if not channel:
        return False

    clean = channel.replace("@", "")

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


# =========================
# USER STATES
# =========================

user_states = {}


def set_state(user_id, state, data=None):
    user_states[user_id] = {
        "state": state,
        "data": data or {}
    }


def get_state(user_id):
    return user_states.get(user_id)


def clear_state(user_id):
    user_states.pop(user_id, None)


# =========================
# ADMIN STATES
# =========================

admin_states = {}


def set_admin_state(user_id, state):
    admin_states[user_id] = state


def get_admin_state(user_id):
    return admin_states.get(user_id)


def clear_admin_state(user_id):
    admin_states.pop(user_id, None)


# =========================
# START
# =========================

def show_home(chat_id):
    send(
        chat_id,
        "🔥 BREAKING REPO\n\n"
        "به ربات خوش آمدید.\n"
        "از منوی زیر انتخاب کنید:",
        home_keyboard()
    )


# =========================
# CALLBACK HANDLER
# =========================

def handle_callback(query):
    callback_id = query["id"]
    data = query.get("data", "")

    user = query["from"]
    user_id = user["id"]
    chat_id = query["message"]["chat"]["id"]
    message_id = query["message"]["message_id"]

    answer(callback_id)

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
            answer(
                callback_id,
                "❌ هنوز عضویت شما تأیید نشده."
            )

        return

    # =====================
    # ADMIN
    # =====================

    if data == "admin":
        if user_id != ADMIN_ID:
            answer(callback_id, "❌ دسترسی ندارید.")
            return

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
            f"👥 تعداد کاربران: {users_count()}",
            admin_keyboard()
        )
        return

    if data == "admin_stats":
        if user_id != ADMIN_ID:
            return

        edit(
            chat_id,
            message_id,
            f"📊 آمار ربات\n\n"
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
            "می‌توانید سقف تعداد هر بخش را جداگانه تغییر دهید.",
            limits_keyboard()
        )
        return

    if data == "admin_report_limit":
        if user_id != ADMIN_ID:
            return

        set_admin_state(user_id, "report_limit")

        edit(
            chat_id,
            message_id,
            "📌 سقف ثبت درخواست را وارد کنید.\n\n"
            "مقدار مجاز: 1 تا 100",
            back_keyboard()
        )
        return

    if data == "admin_email_limit":
        if user_id != ADMIN_ID:
            return

        set_admin_state(user_id, "email_limit")

        edit(
            chat_id,
            message_id,
            "📧 سقف بخش ایمیل را وارد کنید.\n\n"
            "مقدار مجاز: 1 تا 100",
            back_keyboard()
        )
        return

    if data == "admin_add_sub":
        if user_id != ADMIN_ID:
            return

        set_admin_state(user_id, "add_sub")

        edit(
            chat_id,
            message_id,
            "💎 به این شکل وارد کنید:\n\n"
            "123456789 30\n\n"
            "عدد اول = آیدی کاربر\n"
            "عدد دوم = تعداد روز",
            back_keyboard()
        )
        return

    if data == "admin_remove_sub":
        if user_id != ADMIN_ID:
            return

        set_admin_state(user_id, "remove_sub")

        edit(
            chat_id,
            message_id,
            "🗑 آیدی کاربر را ارسال کنید.",
            back_keyboard()
        )
        return

    if data == "admin_extend_sub":
        if user_id != ADMIN_ID:
            return

        set_admin_state(user_id, "extend_sub")

        edit(
            chat_id,
            message_id,
            "➕ به این شکل وارد کنید:\n\n"
            "123456789 7\n\n"
            "عدد اول = آیدی کاربر\n"
            "عدد دوم = تعداد روز برای افزایش",
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

        current = get_setting("force_join", "0")

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

        set_admin_state(user_id, "set_channel")

        edit(
            chat_id,
            message_id,
            "📢 آیدی کانال را ارسال کنید.\n\n"
            "مثال:\n"
            "@MyChannel",
            back_keyboard()
        )
        return

    # =====================
    # HOME
    # =====================

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

    # =====================
    # REQUEST
    # =====================

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
        set_state(user_id, "waiting_report_link")

        edit(
            chat_id,
            message_id,
            "🔗 لینک تلگرام را ارسال کنید.\n\n"
            "فقط لینک‌هایی با دامنه t.me یا telegram.me پذیرفته می‌شوند.",
            back_keyboard()
        )
        return

    # =====================
    # EMAIL
    # =====================

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
            "متن موردنظر خود را ارسال کنید.",
            email_keyboard()
        )
        return

    if data == "email_text":
        set_state(user_id, "waiting_email_text")

        edit(
            chat_id,
            message_id,
            "📧 متن ایمیل را ارسال کنید.",
            back_keyboard()
        )
        return

    # =====================
    # ACCOUNT
    # =====================

    if data == "account":
        edit(
            chat_id,
            message_id,
            "👤 حساب شما\n\n"
            f"🆔 آیدی: {user_id}\n"
            f"💎 وضعیت اشتراک:\n{subscription_text(user_id)}",
            back_keyboard()
        )
        return

    if data == "status":
        conn = db()

        pending = conn.execute("""
            SELECT COUNT(*) AS c
            FROM requests
            WHERE user_id=? AND status='pending'
        """, (user_id,)).fetchone()["c"]

        completed = conn.execute("""
            SELECT COUNT(*) AS c
            FROM requests
            WHERE user_id=? AND status='completed'
        """, (user_id,)).fetchone()["c"]

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
            "برای ارتباط با پشتیبانی از آیدی درج‌شده توسط مدیریت استفاده کنید.",
            back_keyboard()
        )
        return

    if data == "subscription":
        edit(
            chat_id,
            message_id,
            "💎 اشتراک شما\n\n"
            + subscription_text(user_id),
            back_keyboard()
        )
        return


# =========================
# MESSAGE HANDLER
# =========================

def handle_message(message):
    user = message["from"]
    user_id = user["id"]
    chat_id = message["chat"]["id"]

    save_user(user)

    text = message.get("text", "").strip()

    # =====================
    # START
    # =====================

    if text == "/start":
        clear_state(user_id)
        clear_admin_state(user_id)

        if not check_membership(user_id):
            if force_join_message(chat_id):
                return

        show_home(chat_id)
        return

    # =====================
    # ADMIN COMMAND
    # =====================

    if text == "/admin":
        if user_id != ADMIN_ID:
            send(chat_id, "❌ شما دسترسی مدیریت ندارید.")
            return

        clear_admin_state(user_id)

        send(
            chat_id,
            "🛠 پنل مدیریت BREAKING REPO",
            admin_keyboard()
        )
        return

    # =====================
    # ADMIN TEXT STATES
    # =====================

    admin_state = get_admin_state(user_id)

    if user_id == ADMIN_ID and admin_state:

        if admin_state == "report_limit":
            try:
                value = int(text)

                if not 1 <= value <= 100:
                    raise ValueError

                set_setting("report_max", value)
                clear_admin_state(user_id)

                send(
                    chat_id,
                    f"✅ سقف ثبت درخواست روی {value} تنظیم شد.",
                    limits_keyboard()
                )

            except:
                send(
                    chat_id,
                    "❌ مقدار نامعتبر است.\n"
                    "یک عدد بین 1 تا 100 ارسال کنید."
                )

            return

        if admin_state == "email_limit":
            try:
                value = int(text)

                if not 1 <= value <= 100:
                    raise ValueError

                set_setting("email_max", value)
                clear_admin_state(user_id)

                send(
                    chat_id,
                    f"✅ سقف بخش ایمیل روی {value} تنظیم شد.",
                    limits_keyboard()
                )

            except:
                send(
                    chat_id,
                    "❌ مقدار نامعتبر است.\n"
                    "یک عدد بین 1 تا 100 ارسال کنید."
                )

            return

        if admin_state == "add_sub":
            try:
                parts = text.split()

                target_id = int(parts[0])
                days = int(parts[1])

                if days <= 0:
                    raise ValueError

                add_subscription(target_id, days)
                clear_admin_state(user_id)

                send(
                    chat_id,
                    "✅ اشتراک اضافه شد.",
                    admin_keyboard()
                )

            except:
                send(
                    chat_id,
                    "❌ فرمت اشتباه است.\n\n"
                    "مثال:\n"
                    "123456789 30"
                )

            return

        if admin_state == "extend_sub":
            try:
                parts = text.split()

                target_id = int(parts[0])
                days = int(parts[1])

                if days <= 0:
                    raise ValueError

                add_subscription(target_id, days)
                clear_admin_state(user_id)

                send(
                    chat_id,
                    "✅ مدت اشتراک افزایش پیدا کرد.",
                    admin_keyboard()
                )

            except:
                send(
                    chat_id,
                    "❌ فرمت اشتباه است.\n\n"
                    "مثال:\n"
                    "123456789 7"
                )

            return

        if admin_state == "remove_sub":
            try:
                target_id = int(text)

                remove_subscription(target_id)
                clear_admin_state(user_id)

                send(
                    chat_id,
                    "✅ اشتراک حذف شد.",
                    admin_keyboard()
                )

            except:
                send(
                    chat_id,
                    "❌ آیدی نامعتبر است."
                )

            return

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

            set_setting("force_channel", channel)
            clear_admin_state(user_id)

            send(
                chat_id,
                f"✅ کانال تنظیم شد:\n{channel}",
                force_admin_keyboard()
            )

            return

    # =====================
    # USER STATE
    # =====================

    state = get_state(user_id)

    if not state:
        return

    # =====================
    # TELEGRAM LINK
    # =====================

    if state["state"] == "waiting_report_link":

        if not is_telegram_link(text):
            send(
                chat_id,
                "❌ فقط لینک تلگرام قبول می‌شود.\n\n"
                "مثال صحیح:\n"
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
            f"🔢 تعداد را وارد کنید.\n\n"
            f"حداکثر فعلی: {get_report_max()}\n\n"
            "یک عدد بین 1 تا سقف تعیین‌شده ارسال کنید.",
            back_keyboard()
        )

        return

    # =====================
    # REPORT COUNT
    # =====================

    if state["state"] == "waiting_report_count":

        try:
            count = int(text)
        except:
            send(
                chat_id,
                "❌ فقط عدد وارد کنید."
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
            args=(chat_id, request_id, "report"),
            daemon=True
        ).start()

        return

    # =====================
    # EMAIL TEXT
    # =====================

    if state["state"] == "waiting_email_text":

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
            f"🔢 تعداد را وارد کنید.\n\n"
            f"حداکثر فعلی: {get_email_max()}\n\n"
            "یک عدد بین 1 تا سقف تعیین‌شده ارسال کنید.",
            back_keyboard()
        )

        return

    # =====================
    # EMAIL COUNT
    # =====================

    if state["state"] == "waiting_email_count":

        try:
            count = int(text)
        except:
            send(
                chat_id,
                "❌ فقط عدد وارد کنید."
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
            args=(chat_id, request_id, "email"),
            daemon=True
        ).start()

        return


# =========================
# UPDATE LOOP
# =========================

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
        print("UPDATE ERROR:", e)


def main():
    print("BREAKING REPO started...")

    # حذف webhook
    tg("deleteWebhook")

    offset = 0

    while True:
        try:

            result = tg(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": [
                        "message",
                        "callback_query"
                    ]
                }
            )

            if not result.get("ok"):
                time.sleep(3)
                continue

            updates = result.get("result", [])

            for update in updates:

                offset = update["update_id"] + 1

                process_update(update)

        except Exception as e:
            print("LOOP ERROR:", e)
            time.sleep(3)


if __name__ == "__main__":
    main()
