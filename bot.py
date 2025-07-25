from dotenv import load_dotenv
load_dotenv()

import os
import json
import logging
import asyncio
import requests
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEFAULT_VIOTP_TOKEN = os.getenv("VIOTP_API_TOKEN")
ADMIN_ID = 1262582104
USER_TOKEN_FILE = "user_tokens.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
user_sessions = {}

def load_user_tokens():
    if os.path.exists(USER_TOKEN_FILE):
        with open(USER_TOKEN_FILE, "r") as f:
            return json.load(f)
    return {}

def save_user_tokens(tokens):
    with open(USER_TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)

user_tokens = load_user_tokens()

def get_token(user_id):
    return user_tokens.get(str(user_id), DEFAULT_VIOTP_TOKEN)

def set_token(user_id, token):
    user_tokens[str(user_id)] = token
    save_user_tokens(user_tokens)

async def send(update: Update, text, parse_mode=ParseMode.MARKDOWN):
    await update.message.reply_text(text, parse_mode=parse_mode)

def check_balance_raw(token):
    try:
        res = requests.get("https://api.viotp.com/users/balance", params={"token": token}, timeout=5)
        data = res.json()
        if data.get("success"):
            return f"{data['data']['balance']}đ"
    except:
        pass
    return "Không lấy được"

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send(update, "🤖 Bot Thuê Số VIOTP\nGõ /help để xem hướng dẫn.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send(update,
        "📘 *Hướng dẫn sử dụng:*\n"
        "`/addtoken TOKEN` – Lưu token cá nhân\n"
        "`/balance` – Kiểm tra số dư\n"
        "`/rent ID` – Thuê số dịch vụ\n"
        "`/grab` – Thuê Grab (Mobi/Viettel)\n"
        "`/search tên_dịch_vụ` – Tìm ID dịch vụ\n"
        "`/user` – Thông tin token cá nhân\n"
        "`/users` – (Admin) Danh sách toàn bộ user và token")

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
    await send(update, f"💰 Số dư: {check_balance_raw(token)}")

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
            user_sessions[user_id] = {"request_id": req_id, "phone": phone, "token": token}
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
            user_sessions[user_id] = {"request_id": req_id, "phone": phone, "token": token}
            await send(update, f"📱 Grab thuê: `{phone}`\n⌛ Đang đợi OTP...")
            asyncio.create_task(poll_otp(user_id, context))
        else:
            await send(update, f"❌ Lỗi thuê Grab: {data.get('message', '')}")
    except Exception as e:
        await send(update, f"⚠️ Lỗi: `{e}`")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = get_token(update.effective_user.id)
    try:
        keyword = update.message.text.split(" ", 1)[1].lower()
    except:
        await send(update, "❌ Dùng: /search tên_dịch_vụ")
        return

    try:
        res = requests.get("https://api.viotp.com/service/getv2", params={
            "token": token, "country": "vn"
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
    user_id = update.effective_user.id
    token = get_token(user_id)
    balance = check_balance_raw(token)
    await send(update, f"🆔 ID: `{user_id}`\n🔑 Token: `{token}`\n💰 Số dư: {balance}")

async def all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await send(update, "❌ Bạn không có quyền sử dụng lệnh này.")
    
    msg = "*📋 Danh sách người dùng và token:*\n"
    for uid, token in user_tokens.items():
        balance = check_balance_raw(token)
        msg += f"\n🆔 `{uid}`\n🔑 `{token}`\n💰 {balance}\n"
    await send(update, msg)

async def poll_otp(user_id, context):
    session = user_sessions.get(user_id)
    if not session:
        return
    token, req_id, phone = session["token"], session["request_id"], session["phone"]

    for _ in range(30):
        await asyncio.sleep(5)
        try:
            res = requests.get("https://api.viotp.com/session/getv2", params={
                "token": token, "requestId": req_id
            }, timeout=5)
            data = res.json()
            if data.get("success"):
                if data["data"]["Status"] == 1:
                    code = data["data"]["Code"]
                    sms = data["data"].get("SmsContent", "")
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ *OTP:* `{code}`\n📱 *SĐT:* `{phone}`\n✉️ {sms}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                elif data["data"]["Status"] == 2:
                    await context.bot.send_message(chat_id=user_id, text="❌ Số đã hết hạn.")
                    return
        except:
            continue
    await context.bot.send_message(chat_id=user_id, text="❌ Hết thời gian chờ OTP.")

# 🔁 Gửi tin nhắn định kỳ để giữ kết nối
async def ping_loop(bot):
    while True:
        try:
            await bot.send_message(chat_id=ADMIN_ID, text="p")
        except Exception as e:
            logger.warning(f"Không gửi được ping: {e}")
        await asyncio.sleep(300)  # 5 phút

# Main
async def run():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("addtoken", add_token))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("rent", rent))
    app.add_handler(CommandHandler("grab", grab))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("user", user_info))
    app.add_handler(CommandHandler("users", all_users))

    # 🟢 Bắt đầu ping loop
    asyncio.create_task(ping_loop(app.bot))

    print("🤖 Bot đang chạy...")
    await app.run_polling()

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
