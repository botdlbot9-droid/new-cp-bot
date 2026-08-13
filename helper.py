import os
import re
import time
import mmap
import asyncio
import subprocess
import glob
from pathlib import Path
from xml.etree import ElementTree as ET

# ========== curl_cffi for TLS Fingerprint Spoofing ==========
from curl_cffi import requests as curl_requests

# Widevine CDM
try:
    from pywidevine.pssh import PSSH
    from pywidevine.cdm import Cdm
    from pywidevine.device import Device
    WIDEVINE_AVAILABLE = True
except ImportError:
    WIDEVINE_AVAILABLE = False
    print("⚠️ pywidevine not installed")

# ========== CONFIG ==========
PROFILES = ["chrome124", "chrome123", "chrome120", "edge101"]

def create_curl_session(profile="chrome124"):
    return curl_requests.Session(impersonate=profile)

def curl_request_with_retry(url, headers=None, cookies=None, method="GET", data=None, timeout=30):
    if headers is None:
        headers = {}
    if cookies is None:
        cookies = {}
    
    last_error = None
    for profile in PROFILES:
        try:
            session = create_curl_session(profile)
            
            if method.upper() == "GET":
                response = session.get(url, headers=headers, cookies=cookies, timeout=timeout)
            elif method.upper() == "POST":
                response = session.post(url, headers=headers, cookies=cookies, data=data, timeout=timeout)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            if response.status_code < 500:
                print(f"✅ Success with profile: {profile}, status: {response.status_code}")
                return response
                
        except Exception as e:
            print(f"❌ Profile {profile} failed: {e}")
            last_error = e
            continue
    
    raise last_error or Exception("All profiles failed")

def find_wvd_file():
    paths = [
        'WVDs/*.wvd',
        './WVDs/*.wvd',
        'WVDs/device.wvd',
        './WVDs/device.wvd',
        '*.wvd'
    ]
    for pattern in paths:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    raise FileNotFoundError("No .wvd file found")

def extract_content_id(url):
    patterns = [
        r'/lc/([^/]+)/',
        r'/gcs/\d+/lc/([^/]+)/',
        r'/([^/]+)/\d+/hdntl=',
        r'contentHashId=([^&]+)',
        r'[?&]contentHashId=([^&]+)',
        r'/([a-zA-Z0-9]+-\d+)(?=/|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            content_id = match.group(1).split('?')[0].split('&')[0]
            return content_id
    return None

def extract_license_url(mpd_content):
    patterns = [
        r'<ms:laurl[^>]*>([^<]+)</ms:laurl>',
        r'licenseUrl[=:]\s*["\']([^"\']+)["\']',
        r'<ContentProtection[^>]*>.*?<ms:laurl>(.*?)</ms:laurl>',
    ]
    for pattern in patterns:
        match = re.search(pattern, mpd_content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return None

def extract_pssh_from_mpd(mpd_content):
    patterns = [
        r'<pssh[^>]*>([^<]+)</pssh>',
        r'<ms:pro[^>]*>([^<]+)</ms:pro>',
    ]
    for pattern in patterns:
        match = re.search(pattern, mpd_content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return None

def get_widevine_keys(mpd_url, license_url):
    if not WIDEVINE_AVAILABLE:
        return []
    
    try:
        wvd_path = find_wvd_file()
        print(f"📂 Loading WVD: {wvd_path}")
        
        response = curl_request_with_retry(
            mpd_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/dash+xml,application/xml,text/xml,*/*'
            },
            timeout=30
        )
        mpd_content = response.text
        
        pssh_b64 = extract_pssh_from_mpd(mpd_content)
        if not pssh_b64:
            print("❌ PSSH not found in MPD")
            return []
        
        device = Device.load(wvd_path)
        cdm = Cdm.from_device(device)
        
        pssh = PSSH(pssh_b64)
        session_id = cdm.open()
        challenge = cdm.get_license_challenge(session_id, pssh)
        
        lic_headers = {
            'user-agent': 'okhttp/4.9.3',
            'content-type': 'application/octet-stream'
        }
        
        lic_response = curl_request_with_retry(
            license_url,
            headers=lic_headers,
            method="POST",
            data=challenge,
            timeout=30
        )
        
        cdm.parse_license(session_id, lic_response.content)
        keys = cdm.get_keys(session_id)
        cdm.close(session_id)
        
        key_list = []
        for key in keys:
            if hasattr(key, 'kid') and hasattr(key, 'key'):
                kid = key.kid.hex()
                k = key.key.hex()
                if k and kid and len(k) == 32:
                    key_list.append(f"--key {kid}:{k}")
        
        print(f"✅ Extracted {len(key_list)} keys")
        return key_list
        
    except Exception as e:
        print(f"❌ Widevine error: {e}")
        return []

async def decrypt_and_merge_video(mpd_url, keys_string, output_path, output_name, quality="720"):
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    
    cmd1 = f'yt-dlp -f "bv[height<={quality}]+ba/b" -o "{output_path}/file.%(ext)s" --allow-unplayable-format --no-check-certificate --external-downloader aria2c "{mpd_url}"'
    print(f"Running: {cmd1}")
    os.system(cmd1)
    
    avDir = list(output_path.iterdir())
    video_decrypted = False
    audio_decrypted = False
    
    if keys_string and '--key' in keys_string:
        for data in avDir:
            if data.suffix == ".mp4" and not video_decrypted:
                cmd2 = f'mp4decrypt {keys_string} --show-progress "{data}" "{output_path}/video.mp4"'
                os.system(cmd2)
                if (output_path / "video.mp4").exists():
                    video_decrypted = True
                data.unlink()
            elif data.suffix == ".m4a" and not audio_decrypted:
                cmd3 = f'mp4decrypt {keys_string} --show-progress "{data}" "{output_path}/audio.m4a"'
                os.system(cmd3)
                if (output_path / "audio.m4a").exists():
                    audio_decrypted = True
                data.unlink()
    
    if not video_decrypted:
        for data in avDir:
            if data.suffix in ['.mp4', '.mkv', '.webm']:
                data.rename(output_path / "video.mp4")
                video_decrypted = True
                break
    
    if not audio_decrypted:
        for data in avDir:
            if data.suffix in ['.m4a', '.mp3', '.aac']:
                data.rename(output_path / "audio.m4a")
                audio_decrypted = True
                break
    
    if video_decrypted and audio_decrypted:
        cmd4 = f'ffmpeg -i "{output_path}/video.mp4" -i "{output_path}/audio.m4a" -c copy "{output_path}/{output_name}.mp4"'
        os.system(cmd4)
        for f in ["video.mp4", "audio.m4a"]:
            if (output_path / f).exists():
                (output_path / f).unlink()
    elif video_decrypted:
        (output_path / "video.mp4").rename(output_path / f"{output_name}.mp4")
    
    filename = output_path / f"{output_name}.mp4"
    if not filename.exists():
        raise FileNotFoundError("Video file not found")
    
    return str(filename)

async def download_video(url, cmd, name):
    download_cmd = f'{cmd} -R 25 --fragment-retries 25 --external-downloader aria2c --downloader-args "aria2c: -x 16 -j 32"'
    print(download_cmd)
    subprocess.run(download_cmd, shell=True)
    
    for ext in ['', '.webm', '.mkv', '.mp4']:
        fname = name + ext if ext else name
        if os.path.exists(fname):
            return fname
    
    return f"{name}.mp4"

def decrypt_file(file_path, key):
    if not os.path.exists(file_path):
        return False
    with open(file_path, "r+b") as f:
        num_bytes = min(28, os.path.getsize(file_path))
        with mmap.mmap(f.fileno(), length=num_bytes, access=mmap.ACCESS_WRITE) as mm:
            for i in range(num_bytes):
                mm[i] ^= ord(key[i]) if i < len(key) else i
    return True

async def download_and_decrypt_video(url, cmd, name, key):
    video_path = await download_video(url, cmd, name)
    if video_path and decrypt_file(video_path, key):
        return video_path
    return None
