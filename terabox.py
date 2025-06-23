import os
import math
import time
import asyncio
import logging
import urllib.parse
from datetime import datetime
from threading import Thread
from urllib.parse import urlparse

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait

from aria2p import API as Aria2API, Client as Aria2Client
from dotenv import load_dotenv
from flask import Flask, render_template


# Load environment variables from config.env
load_dotenv('config.env', override=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(name)s - %(levelname)s] %(message)s - %(filename)s:%(lineno)d"
)
logger = logging.getLogger(__name__)

# Reduce Pyrogram debug logging noise
logging.getLogger("pyrogram.session").setLevel(logging.ERROR)
logging.getLogger("pyrogram.connection").setLevel(logging.ERROR)
logging.getLogger("pyrogram.dispatcher").setLevel(logging.ERROR)

# Aria2 RPC connection details from environment (support Koyeb or custom host/port)
ARIA2_HOST = os.environ.get('ARIA2_HOST', 'http://localhost')
ARIA2_PORT = int(os.environ.get('ARIA2_PORT', 6800))
ARIA2_SECRET = os.environ.get('ARIA2_SECRET', '')

aria2 = Aria2API(
    Aria2Client(
        host=ARIA2_HOST,
        port=ARIA2_PORT,
        secret=ARIA2_SECRET
    )
)

# Set global Aria2 options
options = {
    "max-tries": "50",
    "retry-wait": "3",
    "continue": "true",
    "allow-overwrite": "true",
    "min-split-size": "4M",
    "split": "10"
}
aria2.set_global_options(options)

# Required environment variables
API_ID = os.environ.get('TELEGRAM_API', '')
API_HASH = os.environ.get('TELEGRAM_HASH', '')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
DUMP_CHAT_ID = os.environ.get('DUMP_CHAT_ID', '')
FSUB_ID = os.environ.get('FSUB_ID', '')
USER_SESSION_STRING = os.environ.get('USER_SESSION_STRING', None)

# Validation for required vars
def validate_env_var(name, val):
    if not val:
        logger.error(f"{name} variable is missing! Exiting now")
        exit(1)

validate_env_var('TELEGRAM_API', API_ID)
validate_env_var('TELEGRAM_HASH', API_HASH)
validate_env_var('BOT_TOKEN', BOT_TOKEN)
validate_env_var('DUMP_CHAT_ID', DUMP_CHAT_ID)
validate_env_var('FSUB_ID', FSUB_ID)

DUMP_CHAT_ID = int(DUMP_CHAT_ID)
FSUB_ID = int(FSUB_ID)

# Initialize Pyrogram clients
app = Client("jetbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user = None
SPLIT_SIZE = 2093796556  # ~2GB split size by default
if USER_SESSION_STRING:
    user = Client("jetu", api_id=API_ID, api_hash=API_HASH, session_string=USER_SESSION_STRING)
    SPLIT_SIZE = 4241280205  # ~4GB if user session is provided
else:
    logger.info("USER_SESSION_STRING not provided, will split files at 2GB")

# Valid Terabox domains to check URLs against
VALID_DOMAINS = [
    'terabox.com', 'nephobox.com', '4funbox.com', 'mirrobox.com',
    'momerybox.com', 'teraboxapp.com', '1024tera.com',
    'terabox.app', 'gibibox.com', 'goaibox.com', 'terasharelink.com',
    'teraboxlink.com', 'terafileshare.com'
]

# Utility: Check if user is member of the required Telegram channel
async def is_user_member(client, user_id):
    try:
        member = await client.get_chat_member(FSUB_ID, user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"Error checking membership for user {user_id}: {e}")
        return False

# Utility: Validate if URL belongs to valid Terabox domains
def is_valid_url(url):
    try:
        parsed_url = urlparse(url)
        return any(parsed_url.netloc.endswith(domain) for domain in VALID_DOMAINS)
    except Exception:
        return False

# Utility: Human-readable file size formatting
def format_size(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024 ** 2:
        return f"{size / 1024:.2f} KB"
    elif size < 1024 ** 3:
        return f"{size / (1024 ** 2):.2f} MB"
    else:
        return f"{size / (1024 ** 3):.2f} GB"

# /start command handler with inline buttons and optional video
@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
    developer_button = InlineKeyboardButton("ᴅᴇᴠᴇʟᴏᴘᴇʀ ⚡️", url="https://t.me/rtx5069")
    repo_button = InlineKeyboardButton("ʀᴇᴘᴏ 🌐", url="https://github.com/Hrishi2861/Terabox-Downloader-Bot")

    reply_markup = InlineKeyboardMarkup([[join_button, developer_button], [repo_button]])
    user_mention = message.from_user.mention if message.from_user else "User"

    welcome_text = (
        f"ᴡᴇʟᴄᴏᴍᴇ, {user_mention}.\n\n"
        "🌟 ɪ ᴀᴍ ᴀ ᴛᴇʀᴀʙᴏx ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ.\n"
        "sᴇɴᴅ ᴍᴇ ᴀɴʏ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ ᴀɴᴅ ɪ ᴡɪʟʟ ᴅᴏᴡɴʟᴏᴀᴅ ɪᴛ ᴀɴᴅ sᴇɴᴅ ɪᴛ ᴛᴏ ʏᴏᴜ ✨."
    )

    video_file_path = "/app/Jet-Mirror.mp4"
    if os.path.exists(video_file_path):
        await client.send_video(
            chat_id=message.chat.id,
            video=video_file_path,
            caption=welcome_text,
            reply_markup=reply_markup
        )
    else:
        await message.reply_text(welcome_text, reply_markup=reply_markup)

# Helper to safely update the status message with flood wait handling
async def update_status_message(status_message, text):
    try:
        await status_message.edit_text(text)
    except FloodWait as e:
        logger.warning(f"FloodWait: sleeping for {e.value} seconds")
        await asyncio.sleep(e.value)
        await update_status_message(status_message, text)
    except Exception as e:
        logger.error(f"Failed to update status message: {e}")

# Main message handler for text messages (not commands)
@app.on_message(filters.text & (~filters.command))
async def handle_message(client: Client, message: Message):
    if not message.from_user:
        return

    user_id = message.from_user.id
    is_member = await is_user_member(client, user_id)

    if not is_member:
        join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
        await message.reply_text(
            "ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.",
            reply_markup=InlineKeyboardMarkup([[join_button]])
        )
        return

    # Extract first valid Terabox URL from message
    url = None
    for word in message.text.split():
        if is_valid_url(word):
            url = word
            break

    if not url:
        await message.reply_text("Please provide a valid Terabox link.")
        return

    # Prepare final URL for aria2
    encoded_url = urllib.parse.quote(url, safe='')
    final_url = f"https://teradlrobot.cheemsbackup.workers.dev/?url={encoded_url}"

    # Add download to aria2
    download = aria2.add_uris([final_url])
    status_message = await message.reply_text("sᴇɴᴅɪɴɢ ʏᴏᴜ ᴛʜᴇ ᴍᴇssᴀɢᴇ...")

    def download_status_thread():
        try:
            while True:
                try:
                    aria2.load()  # Refresh aria2 status
                    info = aria2.get_download(download.gid)
                except Exception:
                    # Download might be removed or error occurred
                    break

                # Prepare status text
                size_total = info.total_length
                size_downloaded = info.completed_length
                progress = size_downloaded / size_total if size_total > 0 else 0
                percent = progress * 100

                speed = info.download_speed or 0
                eta = (size_total - size_downloaded) / speed if speed > 0 else 0
                eta_str = time.strftime('%H:%M:%S', time.gmtime(eta))

                status_text = (
                    f"📥 **Downloading...**\n"
                    f"🗂️ File: {info.name}\n"
                    f"⬇️ {format_size(size_downloaded)} / {format_size(size_total)} ({percent:.2f}%)\n"
                    f"🚀 Speed: {format_size(speed)}/s\n"
                    f"⏳ ETA: {eta_str}\n"
                    f"⚙️ Status: {info.status}"
                )

                # Update status message asynchronously
                asyncio.run_coroutine_threadsafe(update_status_message(status_message, status_text), client.loop)

                if info.is_complete or info.status == "complete":
                    # Download complete
                    # Here you can do post-processing, e.g., upload to Telegram
                    # For now just send a completion message
                    asyncio.run_coroutine_threadsafe(
                        status_message.reply_text(f"Download complete!\nFile name: {info.name}"),
                        client.loop
                    )
                    break

                time.sleep(3)
        except Exception as e:
            logger.error(f"Error in download status thread: {e}")

    # Run download status in a background thread so main loop is free
    Thread(target=download_status_thread, daemon=True).start()

# Flask app for web (if needed)
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "Jet-Mirror Bot is running!"

# Run both pyrogram client and flask app if required
if __name__ == "__main__":
    # Start user client if any
    if user:
        user.start()
        logger.info("User client started")

    # Start bot client
    app.start()
    logger.info("Bot client started")

    # Run flask app in a thread if needed
    from threading import Thread
    flask_thread = Thread(target=flask_app.run, kwargs={"host": "0.0.0.0", "port": 8080})
    flask_thread.start()

    # Idle the bot
    print("Bot is running... Press Ctrl+C to stop.")
    import signal
    signal.pause()
