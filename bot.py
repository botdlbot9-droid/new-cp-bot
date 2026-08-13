import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from vars import API_ID, API_HASH, BOT_TOKEN, OWNER
import drm_handler
import globals

app = Client(
    "drm_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4
)

drm_handler.register_drm_handlers(app)

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        f"**🚀 ClassPlus DRM Downloader Bot**\n\n"
        f"Send me any ClassPlus video link (L1 or L2).\n"
        f"I'll download and send you the video.\n\n"
        f"**Supported:**\n"
        f"- ClassPlus L1 (media-cdn)\n"
        f"- ClassPlus L2 (akamai-cdn)\n"
        f"- YouTube\n"
        f"- Direct M3U8 / MPD streams\n\n"
        f"Made with ❤️ by @{OWNER}"
    )

@app.on_message(filters.command("stop"))
async def stop_cmd(client, message):
    globals.cancel_requested = True
    await message.reply_text("⏹️ Stopped current process.")

if __name__ == "__main__":
    print("🤖 Bot started...")
    app.run()
