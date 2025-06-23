import os, time, math, asyncio, logging, urllib.parse
from datetime import datetime
from threading import Thread
from flask import Flask, render_template
from aria2p import API as Aria2API, Client as Aria2Client
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait

# Load env and configure
from dotenv import load_dotenv
load_dotenv('config.env', override=True)
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

# Telegram & Aria2 setup
aria2 = Aria2API(Aria2Client(host="http://localhost", port=6800, secret=""))
aria2.set_global_options({"max-tries":"50","retry-wait":"3","continue":"true","allow-overwrite":"true","min-split-size":"4M","split":"10"})

API_ID, API_HASH, BOT_TOKEN = os.getenv('TELEGRAM_API'), os.getenv('TELEGRAM_HASH'), os.getenv('BOT_TOKEN')
DUMP_CHAT_ID, FSUB_ID = int(os.getenv('DUMP_CHAT_ID')), int(os.getenv('FSUB_ID'))
USER_SESSION_STRING = os.getenv('USER_SESSION_STRING')
SPLIT_SIZE = 4_241_280_205 if USER_SESSION_STRING else 2_093_796_556

app = Client("jetbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("jetu", api_id=API_ID, api_hash=API_HASH, session_string=USER_SESSION_STRING) if USER_SESSION_STRING else None

VALID_DOMAINS = ['terabox.com','nephobox.com','4funbox.com','mirrobox.com',... ]  # same as before

# Semaphore to limit simultaneous downloads
semaphore = asyncio.Semaphore(3)

# Utilities
def is_valid_url(url):
    from urllib.parse import urlparse
    net = urlparse(url).netloc
    return any(net.endswith(d) for d in VALID_DOMAINS)

def format_size(sz):
    for unit in ['B','KB','MB','GB','TB']:
        if sz < 1024.0:
            return f"{sz:.2f} {unit}"
        sz /= 1024.0
    return f"{sz:.2f} PB"

async def is_user_member(client, user_id):
    try:
        m = await client.get_chat_member(FSUB_ID, user_id)
        return m.status in [ChatMemberStatus.MEMBER,ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER]
    except:
        return False

# UI Progress bar
def progress_bar(pct):
    full = int(pct / 10)
    return "🟩" * full + "⬜" * (10 - full)

# Telegram handlers
@app.on_message(filters.command("start"))
async def start_cmd(_, msg: Message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💌 Join", url="https://t.me/jetmirror")],
        [InlineKeyboardButton("⚙️ Dev", url="https://t.me/rtx5069"), InlineKeyboardButton("🌐 Repo", url="https://github.com/...")]
    ])
    txt = f"👋 Hello {msg.from_user.mention}, send me a Terabox link to download."
    if os.path.exists("/app/Jet-Mirror.mp4"):
        await msg.reply_video("/app/Jet-Mirror.mp4", caption=txt, reply_markup=kb)
    else:
        await msg.reply(txt, reply_markup=kb)

@app.on_message(filters.text & ~filters.command)
async def handle_msg(client: Client, message: Message):
    async with semaphore:
        user_id = message.from_user.id
        if not await is_user_member(client, user_id):
            return await message.reply("🔒 You must join the channel first.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join", url="https://t.me/jetmirror")]]))

        # extract valid URL
        url = next((w for w in message.text.split() if is_valid_url(w)), None)
        if not url:
            return await message.reply("❌ Provide a valid Terabox link.")
        
        status = await message.reply("🚀 Starting download...")
        download = aria2.add_uris([f"https://teradlrobot.cheemsbackup.workers.dev/?url={urllib.parse.quote(url)}"])

        start = datetime.now()
        while not download.is_complete:
            await asyncio.sleep(8)
            download.update()
            pct = download.progress
            bar = progress_bar(pct)
            await safe_edit(status, f"{bar} {pct:.2f}% • {format_size(download.completed_length)}/{format_size(download.total_length)} • ↓{format_size(download.download_speed)}/s")
        
        file_path = download.files[0].path
        elapsed = datetime.now() - start

        # handle splitting & upload
        await upload_file(client, message, status, download.name, file_path, elapsed)

        await safe_delete(status)
        await safe_delete(message)

async def safe_edit(msg, txt):
    try: await msg.edit(txt)
    except FloodWait as e: await asyncio.sleep(e.value); await safe_edit(msg, txt)
    except: pass

async def safe_delete(msg):
    try: await msg.delete()
    except: pass

async def upload_file(client, message, status, filename, path, elapsed):
    size = os.path.getsize(path)
    parts = math.ceil(size / SPLIT_SIZE)

    async def upload(src):
        return await (user.send_video if user else client.send_video)(DUMP_CHAT_ID, src, caption=filename, progress=lambda c, t: asyncio.ensure_future(
            safe_edit(status, f"⬆️ {progress_bar(c/t*100)} {c/t*100:.2f}% • {format_size(c)}/{format_size(t)}")
        ))

    if parts > 1:
        # Splitting using ffmpeg
        for i in range(parts):
            out = f"{path}.{i+1:03d}"
            await safe_edit(status, f"✂️ Splitting part {i+1}/{parts}")
            await asyncio.create_subprocess_exec(
                'ffmpeg', '-y', '-i', path, '-ss', str(i*size/parts), '-t', str(size/parts),
                '-c','copy', out
            )
            sent = await upload(out)
            await client.send_copy(message.chat.id, DUMP_CHAT_ID, sent.message_id)
            os.remove(out)
    else:
        sent = await upload(path)
        await client.send_video(message.chat.id, sent.video.file_id, caption=f"✅ Done: {filename}\n⏱ {elapsed.seconds//60}m {elapsed.seconds%60}s")
    os.remove(path)

# Keepalive server
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return render_template("index.html")
def run_flask(): flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)))
def keep_alive(): Thread(target=run_flask, daemon=True).start()

if __name__ == "__main__":
    keep_alive()
    if user:
        Thread(target=lambda: user.run(), daemon=True).start()
    app.run()
