import os
import urllib.parse
import asyncio
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

# Make sure aria2 and ffmpeg are installed and accessible in PATH

# Replace with your actual aria2 client instance
aria2 = ...  

def format_size(size):
    # Format bytes as human-readable text
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"

def is_valid_url(url):
    return url.startswith("http://") or url.startswith("https://")

async def split_video_with_ffmpeg(input_path, duration_per_part, output_pattern):
    import subprocess
    import shlex

    proc = await asyncio.create_subprocess_exec(
        'ffmpeg', '-y', '-i', input_path,
        '-c', 'copy', '-map', '0',
        '-segment_time', str(duration_per_part),
        '-f', 'segment',
        output_pattern,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()}")

@Client.on_message(filters.private & filters.command("start"))
async def start(client: Client, message: Message):
    user_mention = message.from_user.mention
    welcome_text = (
        f"👋 **Welcome, {user_mention}!**\n\n"
        "⭐ I am a Terabox Downloader Bot.\n"
        "Send me any Terabox link and I'll download it and send you the file here!\n\n"
        "🚀 Join our channel for updates and support."
    )
    await message.reply_text(welcome_text, parse_mode="Markdown")

@Client.on_message(filters.private & filters.text)
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    user_mention = message.from_user.mention

    # Find a URL in the message
    url = None
    for word in message.text.split():
        if is_valid_url(word):
            url = word
            break

    if not url:
        await message.reply_text("❌ Please provide a valid Terabox link.")
        return

    encoded_url = urllib.parse.quote(url)
    final_url = f"https://teradlrobot.cheemsbackup.workers.dev/?url={encoded_url}"

    try:
        # Add download
        download = aria2.add_uris([final_url])
    except Exception as e:
        await message.reply_text(f"❌ Failed to add download: {e}")
        return

    status_message = await message.reply_text("⏳ Starting download...", parse_mode="Markdown")

    start_time = datetime.now()
    last_update_time = datetime.min

    # Show typing status while downloading
    await client.send_chat_action(message.chat.id, "upload_document")

    while not download.is_complete:
        if download.is_removed or getattr(download, "error_message", None):
            await status_message.edit_text(f"❌ Download failed: {getattr(download, 'error_message', 'Unknown error')}")
            return

        now = datetime.now()
        # Update status every 15 seconds
        if (now - last_update_time).seconds >= 15:
            download.update()

            progress = download.progress or 0
            elapsed_time = now - start_time
            elapsed_minutes, elapsed_seconds = divmod(elapsed_time.seconds, 60)

            progress_bar = "█" * int(progress // 10) + "░" * (10 - int(progress // 10))

            status_text = (
                f"📥 **Downloading:** `{download.name}`\n"
                f"🔹 Progress: [{progress_bar}] {progress:.2f}%\n"
                f"🔹 Size: {format_size(download.completed_length or 0)} / {format_size(download.total_length or 0)}\n"
                f"⏳ Speed: {format_size(download.download_speed or 0)}/s\n"
                f"⌛ ETA: {download.eta or 'N/A'} | Elapsed: {elapsed_minutes}m {elapsed_seconds}s\n"
                f"👤 User: [{user_mention}](tg://user?id={user_id}) | ID: `{user_id}`"
            )

            # Add cancel button
            cancel_button = InlineKeyboardButton("Cancel ⛔️", callback_data=f"cancel_{download.gid}")
            reply_markup = InlineKeyboardMarkup([[cancel_button]])

            await status_message.edit_text(status_text, reply_markup=reply_markup, parse_mode="Markdown")
            last_update_time = now

        await asyncio.sleep(5)

    # Download completed
    file_path = download.files[0].path if download.files else None
    if not file_path or not os.path.exists(file_path):
        await status_message.edit_text("❌ Downloaded file not found.")
        return

    await status_message.edit_text(f"✅ Download completed: `{os.path.basename(file_path)}`\n⏳ Preparing to upload...", parse_mode="Markdown")

    # Check file size and split if needed (example: split if >1GB)
    max_size = 1 * 1024 * 1024 * 1024  # 1GB
    if os.path.getsize(file_path) > max_size:
        await status_message.edit_text("⚠️ File is large, splitting into parts...")
        # Split file into 500MB parts with ffmpeg (for video) or split binary for other types
        # Here just an example with ffmpeg for video:
        duration_per_part = 600  # 10 minutes parts
        output_pattern = file_path + "_part%03d.mp4"

        try:
            await split_video_with_ffmpeg(file_path, duration_per_part, output_pattern)
        except Exception as e:
            await status_message.edit_text(f"❌ Failed to split video: {e}")
            return

        # Upload parts one by one
        part_index = 0
        while True:
            part_file = file_path + f"_part{part_index:03d}.mp4"
            if not os.path.exists(part_file):
                break

            await status_message.edit_text(f"⏳ Uploading part {part_index + 1}...")

            try:
                await client.send_document(message.chat.id, part_file, caption=f"Part {part_index + 1} of split video")
            except Exception as e:
                await status_message.edit_text(f"❌ Failed to upload part {part_index + 1}: {e}")
                return

            try:
                os.remove(part_file)
            except Exception:
                pass
            part_index += 1

        try:
            os.remove(file_path)
        except Exception:
            pass

        await status_message.edit_text("✅ All parts uploaded successfully!")
        return

    # File size < max, upload directly
    await status_message.edit_text("⏳ Uploading file...")
    try:
        await client.send_document(message.chat.id, file_path, caption=f"Here is your file, {user_mention}")
    except Exception as e:
        await status_message.edit_text(f"❌ Upload failed: {e}")
        return

    try:
        os.remove(file_path)
    except Exception:
        pass

    await status_message.edit_text("✅ Upload completed successfully!")

@Client.on_callback_query(filters.regex(r"cancel_"))
async def cancel_download(client, callback_query):
    gid = callback_query.data.split("_", 1)[1]
    try:
        aria2.remove(gid)
        await callback_query.answer("❌ Download cancelled.", show_alert=True)
        await callback_query.message.edit_text("❌ Download cancelled by user.")
    except Exception as e:
        await callback_query.answer(f"Error cancelling: {e}", show_alert=True)
