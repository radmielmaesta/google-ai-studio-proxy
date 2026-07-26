# MUST be first — before any stdlib is imported
import gevent
from gevent import monkey

monkey.patch_all()

import os
import platform
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

from flask import Flask
from flask_cors import CORS
from gevent.pywsgi import WSGIServer

from api.routes import api_bp
from core.config import Config

app = Flask(__name__)
CORS(app)
app.register_blueprint(api_bp)

tunnel_process = None


import shutil  # <-- Add this import at the top of your file


def heartbeat():
    """Periodically prints a heartbeat so Colab users know the server is alive."""
    start = time.time()

    while True:
        uptime = int(time.time() - start)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)

        print(
            f"💤 [{datetime.now():%H:%M:%S}] "
            f"Server running | Uptime {h:02}:{m:02}:{s:02}",
            flush=True,
        )

        gevent.sleep(900)


def start_tunnel(port):
    """Auto-downloads cloudflared if missing, starts it, and prints the URL."""
    global tunnel_process
    provider = (Config.TUNNEL_PROVIDER or "").lower()

    if provider != "cloudflare":
        return None

    # Detect OS environment
    system = platform.system().lower()
    machine = platform.machine().lower()
    is_windows = system == "windows"

    # Define binary name correctly per OS
    binary_name = "cloudflared.exe" if is_windows else "cloudflared"

    # Check if cloudflared is installed globally using cross-platform Python native tool
    is_installed = shutil.which(binary_name) is not None

    if not is_installed:
        # Crucial fix: Separate the filename string clean across OS platforms
        local_binary = f"./{binary_name}"

        # Check if we already downloaded it locally
        if not is_installed:
            local_binary = f"./{binary_name}"

            if not os.path.exists(local_binary):
                print(f"ℹ️  '{binary_name}' not found. Auto-downloading locally...")

                # Restore the actual binary distribution payloads
                base_url = (
                    "https://github.com/cloudflare/cloudflared/releases/latest/download"
                )
                if system == "linux" and "x86_64" in machine:
                    url = f"{base_url}/cloudflared-linux-amd64"
                elif system == "linux" and "aarch64" in machine:
                    url = f"{base_url}/cloudflared-linux-arm64"
                elif system == "darwin":
                    url = f"{base_url}/cloudflared-darwin-amd64.tgz"
                elif is_windows:
                    url = f"{base_url}/cloudflared-windows-amd64.exe"
                else:
                    print(f"⚠️ Unsupported system for auto-download: {system} {machine}")
                    return None

                try:
                    # Cleaner streaming context: uses a minimalist browser signature bypass
                    req = urllib.request.Request(
                        url, headers={"User-Agent": "Mozilla/5.0"}
                    )

                    with (
                        urllib.request.urlopen(req) as response,
                        open(local_binary, "wb") as out_file,
                    ):
                        shutil.copyfileobj(response, out_file)

                    if not is_windows:
                        os.chmod(local_binary, 0o755)
                    print(f"✅ Downloaded {binary_name} successfully.")
                except Exception as e:
                    print(f"⚠️ Failed to download cloudflared: {e}")
                    if os.path.exists(local_binary):
                        os.remove(local_binary)
                    return None

            binary_name = local_binary

    try:
        # Start cloudflared directly
        tunnel_process = subprocess.Popen(
            [binary_name, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            # Force Windows to flush text immediately instead of buffering
            creationflags=(subprocess.CREATE_NO_WINDOW if system == "windows" else 0),
        )

        print("⏳ Waiting for Cloudflare Tunnel URL...")

        # We read characters instead of whole buffered lines to bypass Windows stream traps
        buffer = ""
        while True:
            # Check if process died early
            if tunnel_process.poll() is not None:
                break

            char = tunnel_process.stdout.read(1)
            if not char:
                break

            buffer += char
            if "\n" in buffer:
                line = buffer.strip()
                buffer = ""  # Reset loop buffer

                if "trycloudflare.com" in line:
                    match = re.search(
                        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line
                    )
                    if match:
                        return match.group(0)

        # If the loop ends without returning, something went wrong
        print("⚠️ Failed to capture Tunnel URL.")
        tunnel_process.terminate()
        return None

    except Exception as e:
        print(f"⚠️ Tunnel failed: {e}")
        return None


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🚀 3-Tier Proxy Server Starting...")
    print(f"   Model    : {Config.MODEL}")
    print(f"   Thinking : {'On' if Config.ENABLE_THINKING else 'Off'}")
    print(f"   NSFW     : {'On' if Config.ENABLE_NSFW else 'Off'}")
    print("=" * 60 + "\n")

    url = start_tunnel(Config.SERVER_PORT)
    if url:
        print("\n" + "=" * 60)
        print(f"\n🌐 Proxy API URL   : {url}")
        print("\n" + "=" * 60)

    else:
        print("ℹ️  Running locally (no tunnel).\n")

    print(f"\n🌍 WSGIServer → {Config.SERVER_HOST}:{Config.SERVER_PORT}")
    print(f"\n🌱 Status Page     : {url}/status\n")

    # log=None prevents gevent from printing every single chunk to the console
    server = WSGIServer(
        (Config.SERVER_HOST, Config.SERVER_PORT), app, log=None, error_log=None
    )

    try:
        gevent.spawn(heartbeat)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server...")
        server.stop()
        if tunnel_process:
            tunnel_process.terminate()
            print("🛑 Cloudflare tunnel closed.")
