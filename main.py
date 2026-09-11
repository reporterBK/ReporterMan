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

# سقف پیش‌فرض هر دو بخش
DEFAULT_REPORT_MAX = 1000
DEFAULT_EMAIL_MAX = 1000

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            days INTEGER NOT NULL,
            price INTEGER NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            receipt_type TEXT,
            receipt_text TEXT,
            created_at TEXT
        )
    """)

    defaults = {
        "force_join": "0",
        "force_channel": "",
        "report_max": str(DEFAULT_REPORT_MAX),
        "email_max": str(DEFAULT_EMAIL_MAX),
        "card_number": "",
        "support_id": "",
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
            print(
                "Telegram returned non-JSON:",
                response.text
            )
            return {}

        if not result.get("ok"):
            print(
                f"Telegram API ERROR [{method}]:",
                result
            )

        return result

    except requests.RequestException as e:
        print(
            f"NETWORK ERROR [{method}]:",
            e
        )
        return {}

    except Exception as e:
        print(
            f"TG ERROR [{method}]:",
            e
        )
        return {}


def send(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup is not None:
        data["reply_markup"] = json.dumps(
            reply_markup,
            ensure_ascii=False
        )

    return tg(
        "sendMessage",
        data
    )


def edit(chat_id, message_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }

    if reply_markup is not None:
        data["reply_markup"] = json.dumps(
            reply_markup,
            ensure_ascii=False
        )

    return tg(
        "editMessageText",
        data
    )


def answer(callback_id, text=None):
    data = {
        "callback_query_id": callback_id
    }

    if text:
        data["text"] = text

    return tg(
        "answerCallbackQuery",
        data
    )


def copy_message(chat_id, from_chat_id, message_id):
    return tg(
        "copyMessage",
        {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id
        }
    )


# =========================================================
# BUTTONS
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

        return row["value"] if row else default

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
        """, (
            key,
            str(value)
        ))

        conn.commit()

    finally:
        conn.close()


# =========================================================
# LIMITS
# =========================================================

def get_report_max():
    try:
        return max(
            1,
            min(
                1000,
                int(
                    get_setting(
                        "report_max",
                        DEFAULT_REPORT_MAX
                    )
                )
            )
        )

    except Exception:
        return DEFAULT_REPORT_MAX


def get_email_max():
    try:
        return max(
            1,
            min(
                1000,
                int(
                    get_setting(
                        "email_max",
                        DEFAULT_EMAIL_MAX
                    )
                )
            )
        )

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
            """
            SELECT expires_at
            FROM subscriptions
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchone()

        expires = now + timedelta(
            days=days
        )

        if old:
            try:
                old_date = datetime.fromisoformat(
                    old["expires_at"]
                )

                if old_date > now:
                    expires = (
                        old_date +
                        timedelta(days=days)
                    )

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
            """
            DELETE FROM subscriptions
            WHERE user_id=?
            """,
            (user_id,)
        )

        conn.commit()

    finally:
        conn.close()


def has_subscription(user_id):
    conn = db()

    try:
        row = conn.execute(
            """
            SELECT expires_at
            FROM subscriptions
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchone()

    finally:
        conn.close()

    if not row:
        return False

    try:
        return (
            datetime.fromisoformat(
                row["expires_at"]
            )
            > datetime.now()
        )

    except Exception:
        return False


def subscription_text(user_id):
    conn = db()

    try:
        row = conn.execute(
            """
            SELECT expires_at
            FROM subscriptions
            WHERE user_id=?
            """,
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
            f"📅 انقضا: "
            f"{expires.strftime('%Y-%m-%d %H:%M')}"
        )

    except Exception:
        return "❌ اطلاعات اشتراک قابل خواندن نیست."


# =========================================================
# REQUESTS - RECORD ONLY
# =========================================================

def create_request(
    user_id,
    kind,
    target,
    count
):
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
        """, (
            request_id,
        ))

        conn.commit()

    finally:
        conn.close()


# =========================================================
# PLANS
# =========================================================

def create_plan(
    name,
    days,
    price
):
    conn = db()

    try:
        cur = conn.execute("""
            INSERT INTO plans(
                name,
                days,
                price,
                active,
                created_at
            )
            VALUES(?, ?, ?, 1, ?)
        """, (
            name,
            days,
            price,
            datetime.now().isoformat()
        ))

        conn.commit()

        return cur.lastrowid

    finally:
        conn.close()


def get_plans(active_only=True):
    conn = db()

    try:
        if active_only:
            return conn.execute("""
                SELECT *
                FROM plans
                WHERE active=1
                ORDER BY id ASC
            """).fetchall()

        return conn.execute("""
            SELECT *
            FROM plans
            ORDER BY id ASC
        """).fetchall()

    finally:
        conn.close()


def get_plan(plan_id):
    conn = db()

    try:
        return conn.execute(
            """
            SELECT *
            FROM plans
            WHERE id=?
            """,
            (plan_id,)
        ).fetchone()

    finally:
        conn.close()


def delete_plan(plan_id):
    conn = db()

    try:
        conn.execute(
            """
            UPDATE plans
            SET active=0
            WHERE id=?
            """,
            (plan_id,)
        )

        conn.commit()

    finally:
        conn.close()


def plans_text():
    plans = get_plans()

    if not plans:
        return "❌ هنوز هیچ پلن فعالی ساخته نشده."

    lines = [
        "💎 پلن‌های فعال:\n"
    ]

    for p in plans:
        lines.append(
            f"🆔 {p['id']} — {p['name']}\n"
            f"⏱ مدت: {p['days']} روز\n"
            f"💰 قیمت: {p['price']:,} تومان\n"
        )

    return "\n".join(lines)


# =========================================================
# PAYMENTS
# =========================================================

def create_payment(
    user_id,
    plan
):
    conn = db()

    try:
        cur = conn.execute("""
            INSERT INTO payments(
                user_id,
                plan_id,
                amount,
                status,
                created_at
            )
            VALUES(?, ?, ?, 'pending', ?)
        """, (
            user_id,
            plan["id"],
            plan["price"],
            datetime.now().isoformat()
        ))

        conn.commit()

        return cur.lastrowid

    finally:
        conn.close()


def get_payment(payment_id):
    conn = db()

    try:
        return conn.execute(
            """
            SELECT *
            FROM payments
            WHERE id=?
            """,
            (payment_id,)
        ).fetchone()

    finally:
        conn.close()


def update_payment(
    payment_id,
    status,
    receipt_type=None,
    receipt_text=None
):
    conn = db()

    try:
        conn.execute("""
            UPDATE payments
            SET
                status=?,
                receipt_type=COALESCE(
                    ?,
                    receipt_type
                ),
                receipt_text=COALESCE(
                    ?,
                    receipt_text
                )
            WHERE id=?
        """, (
            status,
            receipt_type,
            receipt_text,
            payment_id
        ))

        conn.commit()

    finally:
        conn.close()


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

    if force != "1" or not channel:
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

        return result["result"]["status"] in (
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

    clean = channel.strip().replace(
        "@",
        ""
    )

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


def set_state(
    user_id,
    state,
    data=None
):
    user_states[user_id] = {
        "state": state,
        "data": data or {}
    }


def get_state(user_id):
    return user_states.get(
        user_id
    )


def clear_state(user_id):
    user_states.pop(
        user_id,
        None
    )


def set_admin_state(
    user_id,
    state,
    data=None
):
    admin_states[user_id] = {
        "state": state,
        "data": data or {}
    }


def get_admin_state(user_id):
    return admin_states.get(
        user_id
    )


def clear_admin_state(user_id):
    admin_states.pop(
        user_id,
        None
    )


# =========================================================
# KEYBOARDS
# =========================================================

def home_keyboard():
    return {
        "inline_keyboard": [
            [
                blue(
                    "⚡ ثبت درخواست",
                    "request"
                )
            ],
            [
                green(
                    "💎 خرید اشتراک",
                    "subscription_buy"
                ),
                blue(
                    "👤 حساب من",
                    "account"
                )
            ],
            [
                blue(
                    "📊 وضعیت",
                    "status"
                ),
                blue(
                    "🆔 آیدی من",
                    "myid"
                )
            ],
            [
                blue(
                    "📧 بخش درخواست متنی",
                    "email"
                ),
                blue(
                    "💬 پشتیبانی",
                    "support"
                )
            ]
        ]
    }


def request_keyboard():
    return {
        "inline_keyboard": [
            [
                blue(
                    "🔗 ثبت لینک",
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
                    "📝 ثبت متن درخواست",
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
                    "📊 آمار",
                    "admin_stats"
                )
            ],
            [
                green(
                    "💎 مدیریت پلن‌ها",
                    "admin_plans"
                ),
                green(
                    "💳 شماره کارت",
                    "admin_card"
                )
            ],
            [
                blue(
                    "👤 پشتیبانی",
                    "admin_support"
                ),
                blue(
                    "📢 پیام همگانی",
                    "admin_broadcast"
                )
            ],
            [
                green(
                    "➕ افزودن اشتراک",
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


def plans_admin_keyboard():
    return {
        "inline_keyboard": [
            [
                green(
                    "➕ ساخت پلن جدید",
                    "admin_create_plan"
                )
            ],
            [
                blue(
                    "📋 لیست پلن‌ها",
                    "admin_plan_list"
                )
            ],
            [
                red(
                    "🗑 حذف پلن",
                    "admin_delete_plan"
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


def payment_admin_keyboard(
    payment_id
):
    return {
        "inline_keyboard": [
            [
                green(
                    "✅ تأیید پرداخت",
                    f"pay_ok:{payment_id}"
                )
            ],
            [
                red(
                    "❌ رد پرداخت",
                    f"pay_no:{payment_id}"
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
        button = green(
            "🟢 عضویت اجباری: روشن",
            "admin_toggle_force"
        )
    else:
        button = red(
            "🔴 عضویت اجباری: خاموش",
            "admin_toggle_force"
        )

    return {
        "inline_keyboard": [
            [
                button
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
                    f"📧 سقف درخواست متنی: {get_email_max()}",
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
# USER SUBSCRIPTION UI
# =========================================================

def show_plans(chat_id):
    plans = get_plans()

    if not plans:
        send(
            chat_id,
            "❌ در حال حاضر پلن فعالی برای خرید وجود ندارد.",
            back_keyboard()
        )
        return

    rows = []

    for p in plans:
        rows.append([
            green(
                f"💎 {p['name']} | {p['price']:,} تومان",
                f"buyplan:{p['id']}"
            )
        ])

    rows.append([
        red(
            "🔙 بازگشت",
            "home"
        )
    ])

    send(
        chat_id,
        "💎 خرید اشتراک\n\n"
        "پلن موردنظر را انتخاب کن:",
        {
            "inline_keyboard": rows
        }
    )


def payment_details(
    chat_id,
    user_id,
    plan
):
    card = get_setting(
        "card_number",
        ""
    )

    support = get_setting(
        "support_id",
        ""
    )

    if not card:
        send(
            chat_id,
            "❌ شماره کارت هنوز توسط مدیریت تنظیم نشده است.",
            back_keyboard()
        )
        return

    payment_id = create_payment(
        user_id,
        plan
    )

    set_state(
        user_id,
        "waiting_receipt",
        {
            "payment_id": payment_id
        }
    )

    support_text = (
        support
        or
        "تنظیم نشده"
    )

    send(
        chat_id,
        "💳 اطلاعات پرداخت\n\n"
        f"💎 پلن: {plan['name']}\n"
        f"⏱ مدت: {plan['days']} روز\n"
        f"💰 مبلغ: {plan['price']:,} تومان\n\n"
        f"💳 شماره کارت:\n{card}\n\n"
        "پس از پرداخت، عکس رسید یا متن رسید "
        "را همینجا ارسال کن.\n\n"
        f"👤 پشتیبانی: {support_text}",
        back_keyboard()
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

    answer(callback_id)

    # -----------------------------------------------------
    # JOIN
    # -----------------------------------------------------

    if data == "check_join":
        if check_membership(user_id):
            edit(
                chat_id,
                message_id,
                "✅ عضویت تأیید شد.\n\nحالا می‌توانید از ربات استفاده کنید.",
                home_keyboard()
            )
        else:
            send(
                chat_id,
                "❌ هنوز عضویت شما تأیید نشده است."
            )
        return

    # -----------------------------------------------------
    # HOME
    # -----------------------------------------------------

    if data == "home":
        clear_state(user_id)
        clear_admin_state(user_id)

        edit(
            chat_id,
            message_id,
            "🔥 BREAKING REPO\n\nمنوی اصلی:",
            home_keyboard()
        )
        return

    # -----------------------------------------------------
    # USER REQUEST
    # -----------------------------------------------------

    if data == "request":
        if not check_membership(user_id):
            force_join_message(chat_id)
            return

        if not has_subscription(user_id):
            edit(
                chat_id,
                message_id,
                "❌ برای ثبت درخواست باید اشتراک فعال داشته باشید.",
                {
                    "inline_keyboard": [
                        [
                            green(
                                "💳 خرید اشتراک",
                                "subscription_buy"
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
            "⚡ ثبت درخواست\n\nنوع درخواست را انتخاب کن:",
            request_keyboard()
        )
        return

    if data == "email":
        if not check_membership(user_id):
            force_join_message(chat_id)
            return

        if not has_subscription(user_id):
            edit(
                chat_id,
                message_id,
                "❌ برای ثبت درخواست باید اشتراک فعال داشته باشید.",
                {
                    "inline_keyboard": [
                        [
                            green(
                                "💳 خرید اشتراک",
                                "subscription_buy"
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
            "📧 بخش درخواست متنی\n\nنوع درخواست را انتخاب کن:",
            email_keyboard()
        )
        return

    if data == "request_link":
        if not has_subscription(user_id):
            send(
                chat_id,
                "❌ اشتراک فعال ندارید.",
                back_keyboard()
            )
            return

        set_state(
            user_id,
            "waiting_report_link"
        )

        edit(
            chat_id,
            message_id,
            "🔗 لینک موردنظر را ارسال کن.",
            back_keyboard()
        )
        return

    if data == "email_text":
        if not has_subscription(user_id):
            send(
                chat_id,
                "❌ اشتراک فعال ندارید.",
                back_keyboard()
            )
            return

        set_state(
            user_id,
            "waiting_email_text"
        )

        edit(
            chat_id,
            message_id,
            "📝 متن درخواست را ارسال کن.",
            back_keyboard()
        )
        return

    # -----------------------------------------------------
    # ACCOUNT
    # -----------------------------------------------------

    if data == "account":
        edit(
            chat_id,
            message_id,
            "👤 حساب کاربری\n\n"
            f"🆔 آیدی: {user_id}\n\n"
            f"{subscription_text(user_id)}",
            {
                "inline_keyboard": [
                    [
                        green(
                            "💳 خرید / تمدید اشتراک",
                            "subscription_buy"
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

    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    if data == "status":
        edit(
            chat_id,
            message_id,
            "📊 وضعیت حساب\n\n"
            + subscription_text(user_id),
            {
                "inline_keyboard": [
                    [
                        green(
                            "💳 خرید / تمدید",
                            "subscription_buy"
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

    # -----------------------------------------------------
    # MY ID
    # -----------------------------------------------------

    if data == "myid":
        edit(
            chat_id,
            message_id,
            "🆔 آیدی تلگرام شما:\n\n"
            f"`{user_id}`",
            back_keyboard()
        )
        return

    # -----------------------------------------------------
    # SUPPORT
    # -----------------------------------------------------

    if data == "support":
        support = get_setting(
            "support_id",
            ""
        )

        if not support:
            edit(
                chat_id,
                message_id,
                "💬 پشتیبانی هنوز توسط مدیریت تنظیم نشده است.",
                back_keyboard()
            )
            return

        clean = support.strip().replace(
            "@",
            ""
        )

        edit(
            chat_id,
            message_id,
            "💬 پشتیبانی\n\n"
            f"👤 آیدی پشتیبانی: @{clean}",
            {
                "inline_keyboard": [
                    [
                        blue_url(
                            "💬 ارتباط با پشتیبانی",
                            f"https://t.me/{clean}"
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

    # -----------------------------------------------------
    # ADMIN HOME
    # -----------------------------------------------------

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

        conn = db()

        try:
            pending_payments = conn.execute("""
                SELECT COUNT(*) AS c
                FROM payments
                WHERE status='pending'
            """).fetchone()["c"]

            approved_payments = conn.execute("""
                SELECT COUNT(*) AS c
                FROM payments
                WHERE status='approved'
            """).fetchone()["c"]

        finally:
            conn.close()

        edit(
            chat_id,
            message_id,
            "📊 آمار ربات\n\n"
            f"👥 کاربران: {users_count()}\n"
            f"📋 درخواست‌ها: {requests_count()}\n"
            f"💳 پرداخت‌های در انتظار: {pending_payments}\n"
            f"✅ پرداخت‌های تأییدشده: {approved_payments}",
            admin_keyboard()
        )
        return

    # -----------------------------------------------------
    # ADMIN PLANS
    # -----------------------------------------------------

    if data == "admin_plans":
        if user_id != ADMIN_ID:
            return

        edit(
            chat_id,
            message_id,
            "💎 مدیریت پلن‌ها",
            plans_admin_keyboard()
        )
        return

    if data == "admin_create_plan":
        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "plan_name"
        )

        edit(
            chat_id,
            message_id,
            "➕ ساخت پلن جدید\n\n"
            "مرحله 1 از 3\n\n"
            "نام پلن را ارسال کن.\n\n"
            "مثال:\n"
            "پلن طلایی",
            back_keyboard()
        )
        return

    if data == "admin_plan_list":
        if user_id != ADMIN_ID:
            return

        edit(
            chat_id,
            message_id,
            plans_text(),
            plans_admin_keyboard()
        )
        return

    if data == "admin_delete_plan":
        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "delete_plan"
        )

        edit(
            chat_id,
            message_id,
            "🗑 حذف پلن\n\n"
            "آیدی پلن را ارسال کن.",
            back_keyboard()
        )
        return

    # -----------------------------------------------------
    # ADMIN CARD
    # -----------------------------------------------------

    if data == "admin_card":
        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "set_card"
        )

        current = get_setting(
            "card_number",
            ""
        )

        edit(
            chat_id,
            message_id,
            "💳 تنظیم شماره کارت\n\n"
            f"شماره فعلی:\n"
            f"{current or 'تنظیم نشده'}\n\n"
            "شماره کارت جدید را ارسال کن.",
            back_keyboard()
        )
        return

    # -----------------------------------------------------
    # ADMIN SUPPORT
    # -----------------------------------------------------

    if data == "admin_support":
        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "set_support"
        )

        current = get_setting(
            "support_id",
            ""
        )

        edit(
            chat_id,
            message_id,
            "👤 تنظیم پشتیبانی\n\n"
            f"آیدی فعلی:\n"
            f"{current or 'تنظیم نشده'}\n\n"
            "آیدی پشتیبانی را ارسال کن.\n"
            "مثال: @SupportID",
            back_keyboard()
        )
        return

    # -----------------------------------------------------
    # ADMIN BROADCAST
    # -----------------------------------------------------

    if data == "admin_broadcast":
        if user_id != ADMIN_ID:
            return

        set_admin_state(
            user_id,
            "broadcast"
        )

        edit(
            chat_id,
            message_id,
            "📢 پیام همگانی\n\n"
            "متن پیام را ارسال کن.\n"
            "پیام برای کاربران ثبت‌شده ارسال می‌شود.",
            back_keyboard()
        )
        return

    # -----------------------------------------------------
    # ADMIN ADD SUB
    # -----------------------------------------------------

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
            "💎 افزودن اشتراک دستی\n\n"
            "فرمت:\n"
            "USER_ID DAYS\n\n"
            "مثال:\n"
            "123456789 30",
            back_keyboard()
        )
        return

    # -----------------------------------------------------
    # ADMIN REMOVE SUB
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # ADMIN EXTEND SUB
    # -----------------------------------------------------

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
            "فرمت:\n"
            "USER_ID DAYS\n\n"
            "مثال:\n"
            "123456789 7",
            back_keyboard()
        )
        return

    # -----------------------------------------------------
    # ADMIN FORCE JOIN
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # ADMIN LIMITS
    # -----------------------------------------------------

    if data == "admin_limits":
        if user_id != ADMIN_ID:
            return

        edit(
            chat_id,
            message_id,
            "⚙️ تنظیمات تعداد",
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
            "📌 سقف ثبت لینک\n\n"
            "یک عدد بین 1 تا 1000 ارسال کن.",
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
            "📧 سقف درخواست متنی\n\n"
            "یک عدد بین 1 تا 1000 ارسال کن.",
            back_keyboard()
        )
        return

    # -----------------------------------------------------
    # PAYMENT APPROVAL
    # -----------------------------------------------------

    if data.startswith("pay_ok:") or data.startswith("pay_no:"):
        if user_id != ADMIN_ID:
            return

        try:
            payment_id = int(
                data.split(":", 1)[1]
            )
        except Exception:
            return

        payment = get_payment(
            payment_id
        )

        if not payment:
            send(
                chat_id,
                "❌ پرداخت پیدا نشد."
            )
            return

        if payment["status"] != "pending":
            send(
                chat_id,
                "ℹ️ این پرداخت قبلاً بررسی شده است."
            )
            return

        if data.startswith("pay_ok:"):
            plan = get_plan(
                payment["plan_id"]
            )

            if not plan:
                send(
                    chat_id,
                    "❌ پلن مربوط به پرداخت پیدا نشد."
                )
                return

            add_subscription(
                payment["user_id"],
                plan["days"]
            )

            update_payment(
                payment_id,
                "approved"
            )

            send(
                payment["user_id"],
                "✅ پرداخت شما تأیید شد.\n\n"
                f"💎 پلن: {plan['name']}\n"
                f"⏱ مدت اضافه‌شده: {plan['days']} روز\n\n"
                f"{subscription_text(payment['user_id'])}",
                home_keyboard()
            )

            edit(
                chat_id,
                message_id,
                f"✅ پرداخت #{payment_id} تأیید شد.",
                admin_keyboard()
            )

        else:
            update_payment(
                payment_id,
                "rejected"
            )

            send(
                payment["user_id"],
                "❌ پرداخت شما رد شد.\n\n"
                "برای پیگیری با پشتیبانی تماس بگیرید.",
                home_keyboard()
            )

            edit(
                chat_id,
                message_id,
                f"❌ پرداخت #{payment_id} رد شد.",
                admin_keyboard()
            )

        return
        # =========================================================
# MESSAGE HANDLER
# =========================================================

def handle_message(message):
    user = message.get("from", {})

    if not user:
        return

    user_id = user["id"]
    chat_id = message["chat"]["id"]

    save_user(user)

    text = message.get("text", "") or ""

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    if text.startswith("/start"):
        clear_state(user_id)
        clear_admin_state(user_id)

        if not check_membership(user_id):
            force_join_message(chat_id)
            return

        show_home(chat_id)
        return

    # -----------------------------------------------------
    # ADMIN COMMAND
    # -----------------------------------------------------

    if text.startswith("/admin"):
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

    # -----------------------------------------------------
    # ADMIN STATE
    # -----------------------------------------------------

    admin_state = get_admin_state(user_id)

    if admin_state and user_id == ADMIN_ID:
        state = admin_state["state"]
        state_data = admin_state.get(
            "data",
            {}
        )

        # -------------------------------------------------
        # PLAN NAME
        # -------------------------------------------------

        if state == "plan_name":
            if len(text.strip()) < 1:
                send(
                    chat_id,
                    "❌ نام پلن نمی‌تواند خالی باشد."
                )
                return

            if len(text.strip()) > 60:
                send(
                    chat_id,
                    "❌ نام پلن خیلی طولانی است."
                )
                return

            set_admin_state(
                user_id,
                "plan_days",
                {
                    "name": text.strip()
                }
            )

            send(
                chat_id,
                "➕ ساخت پلن جدید\n\n"
                "مرحله 2 از 3\n\n"
                "مدت پلن را به روز ارسال کن.\n\n"
                "مثال:\n"
                "30",
                back_keyboard()
            )
            return

        # -------------------------------------------------
        # PLAN DAYS
        # -------------------------------------------------

        if state == "plan_days":
            try:
                days = int(text)

                if not 1 <= days <= 3650:
                    raise ValueError

            except Exception:
                send(
                    chat_id,
                    "❌ مدت باید بین 1 تا 3650 روز باشد."
                )
                return

            set_admin_state(
                user_id,
                "plan_price",
                {
                    "name": state_data["name"],
                    "days": days
                }
            )

            send(
                chat_id,
                "➕ ساخت پلن جدید\n\n"
                "مرحله 3 از 3\n\n"
                "قیمت پلن را به تومان ارسال کن.\n\n"
                "مثال:\n"
                "150000",
                back_keyboard()
            )
            return

        # -------------------------------------------------
        # PLAN PRICE
        # -------------------------------------------------

        if state == "plan_price":
            try:
                price = int(text)

                if price <= 0:
                    raise ValueError

            except Exception:
                send(
                    chat_id,
                    "❌ قیمت باید یک عدد مثبت باشد."
                )
                return

            plan_id = create_plan(
                state_data["name"],
                state_data["days"],
                price
            )

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                "✅ پلن با موفقیت ساخته شد.\n\n"
                f"🆔 آیدی پلن: {plan_id}\n"
                f"💎 نام: {state_data['name']}\n"
                f"⏱ مدت: {state_data['days']} روز\n"
                f"💰 قیمت: {price:,} تومان",
                plans_admin_keyboard()
            )
            return

        # -------------------------------------------------
        # DELETE PLAN
        # -------------------------------------------------

        if state == "delete_plan":
            try:
                plan_id = int(text)
            except Exception:
                send(
                    chat_id,
                    "❌ آیدی پلن نامعتبر است."
                )
                return

            plan = get_plan(
                plan_id
            )

            if not plan or plan["active"] != 1:
                send(
                    chat_id,
                    "❌ پلن فعال با این آیدی پیدا نشد."
                )
                return

            delete_plan(
                plan_id
            )

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                f"✅ پلن #{plan_id} حذف شد.",
                plans_admin_keyboard()
            )
            return

        # -------------------------------------------------
        # SET CARD
        # -------------------------------------------------

        if state == "set_card":
            card = text.replace(
                " ",
                ""
            ).replace(
                "-",
                ""
            )

            if not card.isdigit():
                send(
                    chat_id,
                    "❌ شماره کارت باید فقط شامل عدد باشد."
                )
                return

            if not 12 <= len(card) <= 24:
                send(
                    chat_id,
                    "❌ طول شماره کارت نامعتبر است."
                )
                return

            set_setting(
                "card_number",
                card
            )

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                "✅ شماره کارت با موفقیت تنظیم شد.",
                admin_keyboard()
            )
            return

        # -------------------------------------------------
        # SET SUPPORT
        # -------------------------------------------------

        if state == "set_support":
            support = text.strip()

            if not support.startswith("@"):
                send(
                    chat_id,
                    "❌ آیدی باید با @ شروع شود.\n\n"
                    "مثال:\n"
                    "@SupportID"
                )
                return

            set_setting(
                "support_id",
                support
            )

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                "✅ آیدی پشتیبانی تنظیم شد.",
                admin_keyboard()
            )
            return

        # -------------------------------------------------
        # SET CHANNEL
        # -------------------------------------------------

        if state == "set_channel":
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

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                "✅ کانال عضویت اجباری تنظیم شد.",
                force_admin_keyboard()
            )
            return

        # -------------------------------------------------
        # REPORT LIMIT
        # -------------------------------------------------

        if state == "report_limit":
            try:
                value = int(text)

                if not 1 <= value <= 1000:
                    raise ValueError

            except Exception:
                send(
                    chat_id,
                    "❌ عدد باید بین 1 تا 1000 باشد."
                )
                return

            set_setting(
                "report_max",
                value
            )

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                f"✅ سقف ثبت لینک روی {value} تنظیم شد.",
                limits_keyboard()
            )
            return

        # -------------------------------------------------
        # EMAIL LIMIT
        # -------------------------------------------------

        if state == "email_limit":
            try:
                value = int(text)

                if not 1 <= value <= 1000:
                    raise ValueError

            except Exception:
                send(
                    chat_id,
                    "❌ عدد باید بین 1 تا 1000 باشد."
                )
                return

            set_setting(
                "email_max",
                value
            )

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                f"✅ سقف درخواست متنی روی {value} تنظیم شد.",
                limits_keyboard()
            )
            return

        # -------------------------------------------------
        # ADD SUBSCRIPTION
        # -------------------------------------------------

        if state == "add_sub":
            parts = text.split()

            if len(parts) != 2:
                send(
                    chat_id,
                    "❌ فرمت صحیح:\n\n"
                    "USER_ID DAYS\n\n"
                    "مثال:\n"
                    "123456789 30"
                )
                return

            try:
                target_user = int(parts[0])
                days = int(parts[1])

                if days <= 0:
                    raise ValueError

            except Exception:
                send(
                    chat_id,
                    "❌ اطلاعات واردشده نامعتبر است."
                )
                return

            add_subscription(
                target_user,
                days
            )

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                "✅ اشتراک اضافه شد.\n\n"
                f"👤 کاربر: {target_user}\n"
                f"⏱ مدت: {days} روز",
                admin_keyboard()
            )

            send(
                target_user,
                "🎉 اشتراک شما توسط مدیریت فعال شد.\n\n"
                f"⏱ مدت اضافه‌شده: {days} روز\n\n"
                f"{subscription_text(target_user)}",
                home_keyboard()
            )

            return

        # -------------------------------------------------
        # EXTEND SUBSCRIPTION
        # -------------------------------------------------

        if state == "extend_sub":
            parts = text.split()

            if len(parts) != 2:
                send(
                    chat_id,
                    "❌ فرمت صحیح:\n\n"
                    "USER_ID DAYS\n\n"
                    "مثال:\n"
                    "123456789 7"
                )
                return

            try:
                target_user = int(parts[0])
                days = int(parts[1])

                if days <= 0:
                    raise ValueError

            except Exception:
                send(
                    chat_id,
                    "❌ اطلاعات واردشده نامعتبر است."
                )
                return

            if not has_subscription(
                target_user
            ):
                send(
                    chat_id,
                    "❌ این کاربر اشتراک فعال ندارد."
                )
                return

            add_subscription(
                target_user,
                days
            )

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                "✅ اشتراک افزایش پیدا کرد.\n\n"
                f"👤 کاربر: {target_user}\n"
                f"➕ روز اضافه‌شده: {days}",
                admin_keyboard()
            )

            send(
                target_user,
                "✅ اشتراک شما افزایش پیدا کرد.\n\n"
                f"➕ روز اضافه‌شده: {days}\n\n"
                f"{subscription_text(target_user)}",
                home_keyboard()
            )

            return

        # -------------------------------------------------
        # REMOVE SUBSCRIPTION
        # -------------------------------------------------

        if state == "remove_sub":
            try:
                target_user = int(text)
            except Exception:
                send(
                    chat_id,
                    "❌ آیدی کاربر نامعتبر است."
                )
                return

            remove_subscription(
                target_user
            )

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                "✅ اشتراک کاربر حذف شد.\n\n"
                f"👤 کاربر: {target_user}",
                admin_keyboard()
            )

            send(
                target_user,
                "❌ اشتراک شما توسط مدیریت حذف شد.",
                home_keyboard()
            )

            return

        # -------------------------------------------------
        # BROADCAST
        # -------------------------------------------------

        if state == "broadcast":
            broadcast_text = text.strip()

            if not broadcast_text:
                send(
                    chat_id,
                    "❌ متن پیام خالی است."
                )
                return

            conn = db()

            try:
                users = conn.execute(
                    "SELECT user_id FROM users"
                ).fetchall()

            finally:
                conn.close()

            sent_count = 0
            failed_count = 0

            for row in users:
                target_user = row["user_id"]

                result = send(
                    target_user,
                    broadcast_text
                )

                if result.get("ok"):
                    sent_count += 1
                else:
                    failed_count += 1

                time.sleep(0.05)

            clear_admin_state(
                user_id
            )

            send(
                chat_id,
                "📢 ارسال همگانی تمام شد.\n\n"
                f"✅ موفق: {sent_count}\n"
                f"❌ ناموفق: {failed_count}",
                admin_keyboard()
            )

            return


    # -----------------------------------------------------
    # USER STATE
    # -----------------------------------------------------

    state_info = get_state(
        user_id
    )

    if not state_info:
        if text:
            send(
                chat_id,
                "از منوی ربات استفاده کن.",
                home_keyboard()
            )

        return

    current = state_info["state"]
    state_data = state_info.get(
        "data",
        {}
    )

    # -----------------------------------------------------
    # PAYMENT RECEIPT
    # -----------------------------------------------------

    if current == "waiting_receipt":
        payment_id = state_data.get(
            "payment_id"
        )

        if not payment_id:
            clear_state(user_id)

            send(
                chat_id,
                "❌ خطای داخلی پرداخت.",
                home_keyboard()
            )
            return

        # TEXT RECEIPT
        if text:
            update_payment(
                payment_id,
                "pending",
                "text",
                text
            )

            admin_message = (
                "💳 رسید پرداخت جدید\n\n"
                f"🆔 پرداخت: #{payment_id}\n"
                f"👤 کاربر: {user_id}\n"
                f"🧾 نوع رسید: متن\n\n"
                f"📄 رسید:\n{text}"
            )

            send(
                ADMIN_ID,
                admin_message,
                payment_admin_keyboard(
                    payment_id
                )
            )

            clear_state(
                user_id
            )

            send(
                chat_id,
                "✅ رسید شما دریافت شد.\n\n"
                "⏳ منتظر بررسی مدیریت باشید.",
                home_keyboard()
            )

            return

        # PHOTO RECEIPT
        photo = message.get(
            "photo"
        )

        if photo:
            file_id = photo[-1]["file_id"]

            update_payment(
                payment_id,
                "pending",
                "photo",
                file_id
            )

            send(
                ADMIN_ID,
                "💳 رسید پرداخت جدید\n\n"
                f"🆔 پرداخت: #{payment_id}\n"
                f"👤 کاربر: {user_id}\n"
                "🧾 نوع رسید: تصویر",
                payment_admin_keyboard(
                    payment_id
                )
            )

            tg(
                "sendPhoto",
                {
                    "chat_id": ADMIN_ID,
                    "photo": file_id,
                    "caption":
                        f"🧾 رسید پرداخت #{payment_id}\n"
                        f"👤 کاربر: {user_id}"
                }
            )

            clear_state(
                user_id
            )

            send(
                chat_id,
                "✅ تصویر رسید دریافت شد.\n\n"
                "⏳ منتظر بررسی مدیریت باشید.",
                home_keyboard()
            )

            return

        send(
            chat_id,
            "❌ لطفاً عکس رسید یا متن رسید را ارسال کن."
        )
        return

    # -----------------------------------------------------
    # LINK REQUEST
    # -----------------------------------------------------

    if current == "waiting_report_link":
        if len(text) < 5:
            send(
                chat_id,
                "❌ لینک نامعتبر است."
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
            f"حداکثر فعلی: {get_report_max()}",
            back_keyboard()
        )

        return

    if current == "waiting_report_count":
        try:
            count = int(text)
        except Exception:
            send(
                chat_id,
                "❌ فقط عدد ارسال کن."
            )
            return

        maximum = get_report_max()

        if not 1 <= count <= maximum:
            send(
                chat_id,
                f"❌ تعداد باید بین 1 تا {maximum} باشد."
            )
            return

        request_id = create_request(
            user_id,
            "link",
            state_data["target"],
            count
        )

        clear_state(
            user_id
        )

        send(
            chat_id,
            "✅ درخواست شما ثبت شد.\n\n"
            f"🆔 شماره درخواست: #{request_id}\n"
            f"🔗 لینک: {state_data['target']}\n"
            f"🔢 تعداد: {count}\n\n"
            "⏳ درخواست برای بررسی ثبت شد.",
            home_keyboard()
        )

        return

    # -----------------------------------------------------
    # TEXT REQUEST
    # -----------------------------------------------------

    if current == "waiting_email_text":
        if len(text) < 3:
            send(
                chat_id,
                "❌ متن خیلی کوتاه است."
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
            f"حداکثر فعلی: {get_email_max()}",
            back_keyboard()
        )

        return

    if current == "waiting_email_count":
        try:
            count = int(text)
        except Exception:
            send(
                chat_id,
                "❌ فقط عدد ارسال کن."
            )
            return

        maximum = get_email_max()

        if not 1 <= count <= maximum:
            send(
                chat_id,
                f"❌ تعداد باید بین 1 تا {maximum} باشد."
            )
            return

        request_id = create_request(
            user_id,
            "text",
            state_data["target"],
            count
        )

        clear_state(
            user_id
        )

        send(
            chat_id,
            "✅ درخواست شما ثبت شد.\n\n"
            f"🆔 شماره درخواست: #{request_id}\n"
            f"🔢 تعداد: {count}\n\n"
            "⏳ درخواست برای بررسی ثبت شد.",
            home_keyboard()
        )

        return


# =========================================================
# HOME
# =========================================================

def show_home(chat_id):
    send(
        chat_id,
        "🔥 BREAKING REPO\n\n"
        "به ربات خوش آمدید.\n"
        "از منوی زیر استفاده کنید:",
        home_keyboard()
    )


# =========================================================
# UPDATE PROCESSOR
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
    print(
        "================================"
    )
    print(
        "BREAKING REPO"
    )
    print(
        "Bot is starting..."
    )
    print(
        "================================"
    )

    me = tg(
        "getMe"
    )

    if not me.get("ok"):
        print(
            "❌ BOT TOKEN یا اتصال مشکل دارد."
        )

        print(
            me
        )

        raise RuntimeError(
            "اتصال به Telegram API برقرار نشد."
        )

    bot_info = me["result"]

    print(
        f"✅ Connected to "
        f"@{bot_info.get('username', 'unknown')}"
    )

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
                    "allowed_updates": json.dumps(
                        [
                            "message",
                            "callback_query"
                        ]
                    )
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
                offset = (
                    update["update_id"] + 1
                )

                process_update(
                    update
                )

        except KeyboardInterrupt:
            print(
                "Bot stopped."
            )
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
