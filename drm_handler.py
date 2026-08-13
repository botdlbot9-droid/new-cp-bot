import os
import re
import asyncio
import time
from pathlib import Path
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from pyromod import listen

import helper
import globals
from vars import cptoken, OWNER

async def drm_handler(bot: Client, m: Message):
    globals.processing_request = True
    globals.cancel_requested = False
    
    if m.document and m.document.file_name.endswith('.txt'):
        x = await m.download()
        with open(x, "r") as f:
            lines = f.read().split("\n")
        os.remove(x)
        file_name = m.document.file_name.replace('.txt', '')
    elif m.text and "://" in m.text:
        lines = [m.text]
        file_name = "Link Input"
    else:
        return
    
    links = [line.strip() for line in lines if "://" in line.strip()]
    if not links:
        await m.reply_text("❌ No valid links found.")
        return
    
    failed_count = 0
    count = 1
    
    for url in links:
        if globals.cancel_requested:
            await m.reply_text("⏹️ Stopped.")
            globals.processing_request = False
            globals.cancel_requested = False
            return
        
        try:
            await process_single_video(bot, m, url, count, len(links))
            count += 1
        except Exception as e:
            print(f"Error: {e}")
            failed_count += 1
            count += 1
    
    await m.reply_text(f"✅ Done! Success: {len(links) - failed_count}, Failed: {failed_count}")

async def process_single_video(bot, m, url, count, total):
    name = f"{str(count).zfill(3)}) Video"
    keys_string = ""
    appxkey = ""
    quality = "720"
    
    if 'classplusapp' in url or 'akamai-cdn.classplusapp.com' in url:
        content_id = helper.extract_content_id(url)
        if not content_id:
            await m.reply_text(f"❌ Could not extract contentId from URL:\n`{url[:100]}...`")
            return
        
        await m.reply_text(f"🔄 Processing video {count}/{total}...")
        
        headers = {
            'x-access-token': cptoken,
            'content-type': 'application/json',
            'user-agent': 'Mobile-Android',
            'device-details': 'Xiaomi_Redmi 7_SDK-32',
            'device-id': 'a1b2c3d4e5f67890',
            'api-version': '18',
        }
        
        try:
            api_url = f"https://api.classplusapp.com/cams/uploader/video/jw-signed-url?contentId={content_id}&offlineDownload=false"
            
            response = helper.curl_request_with_retry(
                api_url,
                headers=headers,
                timeout=15
            )
            res = response.json()
            
            if 'drmUrls' in res and 'manifestUrl' in res['drmUrls']:
                mpd_url = res['drmUrls']['manifestUrl']
                license_url = res['drmUrls'].get('licenseUrl')
                
                if license_url:
                    keys = helper.get_widevine_keys(mpd_url, license_url)
                    keys_string = " ".join(keys) if keys else ""
                    url = mpd_url
                else:
                    url = res.get('url', url)
            else:
                url = res.get('url', url)
                
        except Exception as e:
            await m.reply_text(f"❌ API Error: {str(e)}")
            return
    
    elif 'encrypted.m' in url:
        if '*' in url:
            appxkey = url.split('*')[1]
            url = url.split('*')[0]
    
    elif 'youtu' in url:
        cmd = f'yt-dlp -f "bv*[height<={quality}][ext=mp4]+ba[ext=m4a]" -o "{name}.mp4" "{url}"'
    
    else:
        cmd = f'yt-dlp -f "bestvideo[height<={quality}]+bestaudio" -o "{name}.mp4" "{url}"'
    
    await m.reply_text(f"⬇️ Downloading video {count}/{total}...")
    
    try:
        if 'encrypted.m' in url:
            res_file = await helper.download_and_decrypt_video(url, cmd, name, appxkey)
        elif keys_string and ('drm' in url or 'akamai' in url):
            res_file = await helper.decrypt_and_merge_video(url, keys_string, f"./downloads/{m.chat.id}", name, quality)
        else:
            res_file = await helper.download_video(url, cmd, name)
        
        if res_file and os.path.exists(res_file):
            await m.reply_text(f"📤 Uploading video {count}/{total}...")
            
            await bot.send_video(
                chat_id=m.chat.id,
                video=res_file,
                caption=f"✅ Video {count}/{total} downloaded!\n\nMade with ❤️ by @{OWNER}",
                supports_streaming=True
            )
            
            os.remove(res_file)
            
    except Exception as e:
        await m.reply_text(f"❌ Download failed: {str(e)}")

def register_drm_handlers(bot):
    @bot.on_message(filters.private & (filters.document | filters.text))
    async def handler(bot: Client, m: Message):
        await drm_handler(bot, m)
