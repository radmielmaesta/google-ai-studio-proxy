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
from pyngrok import ngrok

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


def ensure_cloudflared_binary():
    """
    Checks if cloudflared is installed globally or locally.
    Downloads the binary for the current OS/architecture if missing.
    Returns the binary path string or None if resolution/download fails.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()
    is_windows = system == "windows"

    binary_name = "cloudflared.exe" if is_windows else "cloudflared"

    # 1. Check global installation via PATH
    if shutil.which(binary_name) is not None:
        return binary_name

    # 2. Check local binary
    local_binary = f"./{binary_name}"
    if os.path.exists(local_binary):
        return local_binary

    # 3. Download if missing
    print(f"ℹ️  '{binary_name}' not found. Auto-downloading locally...")
    base_url = "https://github.com/cloudflare/cloudflared/releases/latest/download"

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
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

        with (
            urllib.request.urlopen(req) as response,
            open(local_binary, "wb") as out_file,
        ):
            shutil.copyfileobj(response, out_file)

        if not is_windows:
            os.chmod(local_binary, 0o755)

        print(f"✅ Downloaded {binary_name} successfully.")
        return local_binary

    except Exception as e:
        print(f"⚠️ Failed to download cloudflared: {e}")
        if os.path.exists(local_binary):
            os.remove(local_binary)
        return None


def start_tunnel(port):
    """Auto-downloads cloudflared if missing, starts it, and prints the URL."""

    global tunnel_process
    provider = (Config.TUNNEL_PROVIDER or "").lower()

    if provider == "ngrok":
        print("\n" + "=" * 50)
        print("🚀 STARTING NGROK TUNNEL")
        print("=" * 50)

        auth_token = (Config.NGROK_TOKEN or "").strip()
        static_domain = (Config.NGROK_URL or "").strip()

        if auth_token:
            ngrok.set_auth_token(auth_token)
        else:
            print(
                "⚠️ WARNING: No Ngrok Auth Token provided. Tunnel may fail or time out."
            )

        options = {"bind_tls": True}

        # Use static domain to bypass random URL generation
        if static_domain:
            # 1. Clean leading/trailing whitespace
            static_domain = static_domain.strip()

            # 2. Strip protocol prefixes cleanly
            static_domain = static_domain.removeprefix("https://").removeprefix(
                "http://"
            )

            # 3. Strip leading "www." unconditionally (Ngrok never uses www.)
            static_domain = static_domain.removeprefix("www.")

            # 4. Strip any trailing slashes, paths, or query params (e.g., /status or ?foo=bar)
            static_domain = static_domain.split("/")[0].split("?")[0].strip()
            options["domain"] = static_domain

        try:
            public_url = ngrok.connect(port, **options).public_url
            return public_url
        except Exception as e:
            print(f"\n❌ Ngrok failed to start: {e}")
            print("Did you enter the correct Static Domain and Auth Token?")
            return None

    elif provider == "cloudflare":
        binary_name = ensure_cloudflared_binary()

        if not binary_name:
            return None

        system = platform.system().lower()

        try:
            # Start cloudflared directly
            tunnel_process = subprocess.Popen(
                [binary_name, "tunnel", "--url", f"http://localhost:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # Force Windows to flush text immediately instead of buffering
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if system == "windows" else 0
                ),
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
                        # Require at least 8 alphanumeric characters/dashes in the subdomain
                        match = re.search(
                            r"https://[a-zA-Z0-9-]{8,}\.trycloudflare\.com", line
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
