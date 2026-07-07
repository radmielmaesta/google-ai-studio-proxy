from api.routes import api_bp
from core.config import Config
from flask import Flask
from flask_cors import CORS

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Register endpoints
app.register_blueprint(api_bp)

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🚀 3-Tier Proxy Server Starting...")
    print(f" Model: {Config.MODEL}")
    print(f" Thinking Mode: {'Enabled' if Config.ENABLE_THINKING else 'Disabled'}")
    print(f" NSFW Mode: {'Enabled' if Config.ENABLE_NSFW else 'Disabled'}")
    print("=" * 60 + "\n")

    # Setup tunnel provider (Cloudflare or LocalTunnel)
    try:
        if Config.TUNNEL_PROVIDER.lower() == "cloudflare":
            from flask_cloudflared import run_with_cloudflared

            run_with_cloudflared(app)
        else:
            from flask_lt import run_with_lt

            run_with_lt(app)
    except ImportError:
        print("⚠️ Tunnel libraries not found. Running strictly local.")

    # Start the server
    app.run(host=Config.SERVER_HOST, port=Config.SERVER_PORT)
