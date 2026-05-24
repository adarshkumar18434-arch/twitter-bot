import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("❌ Error: API_ID or API_HASH not found in .env")
    exit()

print("🚀 Starting Telegram Session Generator...")
print("Enter your phone number and the code you receive on Telegram.")

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    session_string = client.session.save()
    print("\n" + "="*60)
    print("✅ YOUR SESSION STRING (Copy everything below):")
    print("="*60)
    print(f"\n{session_string}\n")
    print("="*60)
    print("📌 COPY this string and add it to your Railway Environment Variables as:")
    print("TELEGRAM_SESSION_STRING")
    print("="*60)
