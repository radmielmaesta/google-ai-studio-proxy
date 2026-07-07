# MUST be first — before any stdlib is imported
from gevent import monkey

monkey.patch_all()

import os
import platform
import re
import subprocess
import sys
import urllib.request

from flask import Flask
from flask_cors import CORS
from gevent.pywsgi import WSGIServer

from api.routes import api_bp
from core.config import Config

app = Flask(__name__)
CORS(app)
app.register_blueprint(api_bp)

tunnel_process = None


def start_tunnel(port):
    """Auto-downloads cloudflared if missing, starts it, and prints the URL."""
    global tunnel_process
    provider = (Config.TUNNEL_PROVIDER or "").lower()

    if provider != "cloudflare":
        return None

    binary_name = "cloudflared"
    # Check if cloudflared is installed globally
    is_installed = (
        subprocess.call(
            ["which", binary_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        == 0
    )

    if not is_installed:
        local_binary = "./cloudflared"
        # Check if we already downloaded it locally
        if not os.path.exists(local_binary):
            print("ℹ️  'cloudflared' not found. Auto-downloading locally...")
            system = platform.system().lower()
            machine = platform.machine().lower()

            if system == "linux" and "x86_64" in machine:
                url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
            elif system == "linux" and "aarch64" in machine:
                url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
            elif system == "darwin":
                url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"
            else:
                print(f"⚠️ Unsupported system for auto-download: {system} {machine}")
                return None

            try:
                urllib.request.urlretrieve(url, local_binary)
                os.chmod(local_binary, 0o755)
                print("✅ Downloaded cloudflared successfully.")
            except Exception as e:
                print(f"⚠️ Failed to download cloudflared: {e}")
                return None

        binary_name = local_binary

    try:
        # Start cloudflared directly
        tunnel_process = subprocess.Popen(
            [binary_name, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        print("⏳ Waiting for Cloudflare Tunnel URL...")
        # Read output line-by-line to find the generated URL
        for line in iter(tunnel_process.stdout.readline, ""):
            if "trycloudflare.com" in line:
                match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if match:
                    return match.group(0)

        # If the loop ends without returning, something went wrong with cloudflared
        print("⚠️ Failed to capture Tunnel URL. Output:")
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
        print(f"\n✅ Cloudflare Tunnel: {url}\n")
    else:
        print("ℹ️  Running locally (no tunnel).\n")

    print(f"🌍 WSGIServer → {Config.SERVER_HOST}:{Config.SERVER_PORT}")

    # log=None prevents gevent from printing every single chunk to the console
    server = WSGIServer(
        (Config.SERVER_HOST, Config.SERVER_PORT), app, log=None, error_log=None
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server...")
        server.stop()
        if tunnel_process:
            tunnel_process.terminate()
            print("🛑 Cloudflare tunnel closed.")
