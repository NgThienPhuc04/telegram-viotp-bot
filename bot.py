import os
import json
import logging
import asyncio
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# ==== Load ENV ====
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEFAULT_VIOTP_TOKEN = os.getenv("VIOTP_API_TOKEN")
ADMIN_ID = 1262582104
USER_TOKEN_FILE = "user_tokens.json"

# ==== Logger ====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
user_sessions = {}

# ==== Token Handling ====
def load_user_tokens():
    if os.path.exists(USER_TOKEN_FILE):
        with open(USER_TOKEN_FILE, "r") as f:
            return json.load(f)
    return {}

def save_user_tokens(tokens):
    with open(USER_TOKEN_FILE, "w") as f:
        json.dump(tokens, f)

user_tokens = load_user_tokens()

def get_token(user_id):
    return user_tokens.get(str(user_id), DEFAULT_VIOTP_TOKEN)

def set_token(user_id, token):
    user_tokens[str(user_id)] = token
    save_user_tokens(user_tokens)

def check_balance_raw(token):
    try:
        res = requests.get("https://api.viotp.com/users/balance", params={"token": token}, timeout=5)
        data = res.json()
        if data.get("success"):
            return f"{data['data']['balance']}đ"
    except:
        pass
    return "Không thể lấy số dư"

# ==== Bot Message ====
async def send(update: Update, text, parse_mode=ParseMode.MARKDOWN):
    await update.message.reply_text(text, parse_mode=parse_mode)

# ==== Command Handlers ====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send(update, "🤖 Bot Thuê Số VIOTP\nGõ /help để xem các lệnh.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send(update,
        "📘 *Hướng dẫn sử dụng:*\n"
        "`/addtoken YOUR_TOKEN` – Lưu token cá nhân\n"
        "`/balance` – Kiểm tra số dư\n"
        "`/rent ID` – Thuê số dịch vụ\n"
        "`/grab` – Thuê Grab (Mobi/Viettel)\n"
        "`/search tên_dịch_vụ` – Tìm ID dịch vụ\n"
        "`/user` – Xem token và số dư (admin)\n"
        "`/users` – Danh sách tất cả token (admin)"
    )

async def add_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        token = update.message.text.split(" ", 1)[1].strip()
        set_token(user_id, token)
        balance = check_balance_raw(token)
        await send(update, f"✅ Token đã lưu!\n💰 Số dư: {balance}")
    except:
        await send(update, "❌ Dùng: /addtoken YOUR_TOKEN")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = get_token(update.effective_user.id)
    balance = check_balance_raw(token)
    await send(update, f"💰 {balance}")

async def rent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = get_token(user_id)
    try:
        service_id = update.message.text.split(" ", 1)[1].strip()
    except:
        await send(update, "❌ Dùng: /rent ID")
        return

    try:
        res = requests.get("https://api.viotp.com/request/getv2", params={
            "token": token,
            "serviceId": service_id
        }, timeout=10)
        data = res.json()
        if data.get("success"):
            phone = data["data"]["phone_number"]
            req_id = data["data"]["request_id"]
            user_sessions[user_id] = {
                "request_id": req_id,
                "phone": phone,
                "token": token
            }
            await send(update, f"📱 Số đã thuê: `{phone}`\n⌛ Đang chờ mã OTP...")
            asyncio.create_task(poll_otp(user_id, context))
        else:
            await send(update, f"❌ Lỗi thuê số: {data.get('message', '')}")
    except Exception as e:
        await send(update, f"⚠️ Lỗi hệ thống: `{e}`")

async def grab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = get_token(user_id)
    try:
        res = requests.get("https://api.viotp.com/request/getv2", params={
            "token": token,
            "serviceId": "20",
            "network": "MOBIFONE|VIETTEL"
        }, timeout=10)
        data = res.json()
        if data.get("success"):
            phone = data["data"]["phone_number"]
            req_id = data["data"]["request_id"]
            user_sessions[user_id] = {
                "request_id": req_id,
                "phone": phone,
                "token": token
            }
            await send(update, f"📱 Grab thuê: `{phone}`\n⌛ Đang đợi OTP...")
            asyncio.create_task(poll_otp(user_id, context))
        else:
            await send(update, f"❌ Lỗi thuê Grab: {data.get('message', '')}")
    except Exception as e:
        await send(update, f"⚠️ Lỗi: `{e}`")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = get_token(user_id)
    try:
        keyword = update.message.text.split(" ", 1)[1].lower()
    except:
        await send(update, "❌ Dùng: /search tên_dịch_vụ")
        return

    try:
        res = requests.get("https://api.viotp.com/service/getv2", params={
            "token": token,
            "country": "vn"
        }, timeout=10)
        data = res.json()
        if data.get("success"):
            matches = [f"{s['id']} – {s['name']}" for s in data["data"] if keyword in s["name"].lower()]
            msg = "\n".join(matches[:20]) if matches else "❌ Không tìm thấy dịch vụ nào."
            await send(update, msg)
        else:
            await send(update, "❌ Không lấy được danh sách dịch vụ.")
    except Exception as e:
        await send(update, f"⚠️ Lỗi: `{e}`")

async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    token = get_token(update.effective_user.id)
    balance = check_balance_raw(token)
    await send(update, f"🧾 Token: `{token}`\n💰 Số dư: {balance}")

async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    msg = "📋 Danh sách user:\n"
    for uid, token in user_tokens.items():
        balance = check_balance_raw(token)
        msg += f"👤 `{uid}`\n🔑 `{token}`\n💰 {balance}\n\n"
    await send(update, msg)

# ==== OTP Polling ====
async def poll_otp(user_id, context):
    session = user_sessions.get(user_id)
    if not session:
        return
    token = session["token"]
    req_id = session["request_id"]
    phone = session["phone"]

    for _ in range(30):
        await asyncio.sleep(5)
        try:
            res = requests.get("https://api.viotp.com/session/getv2", params={
                "token": token,
                "requestId": req_id
            }, timeout=5)
            data = res.json()
            if data.get("success") and data["data"]["Status"] == 1:
                code = data["data"]["Code"]
                sms = data["data"].get("SmsContent", "")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ *OTP:* `{code}`\n📱 *SĐT:* `{phone}`\n✉️ {sms}",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
        except:
            continue
    await context.bot.send_message(chat_id=user_id, text="❌ Hết thời gian chờ OTP.")

# ==== Ping loop to keep alive ====
async def ping_loop(app):
    while True:
        await asyncio.sleep(300)
        await app.bot.send_message(chat_id=ADMIN_ID, text="p")

# ==== Main ====
async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("addtoken", add_token))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("rent", rent))
    app.add_handler(CommandHandler("grab", grab))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("user", user_info))
    app.add_handler(CommandHandler("users", users_list))
    asyncio.create_task(ping_loop(app))
    await app.run_polling()

# === Entry point ===
if __name__ == "__main__":
    asyncio.run(main())
