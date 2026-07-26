import time

from flask import Blueprint, Response, jsonify, request

from core.config import Config
from services.llm_streamer import create_error_response, process_llm_request

api_bp = Blueprint("api", __name__)
SERVER_START_TIME = time.time()


def format_uptime():
    uptime = int(time.time() - SERVER_START_TIME)

    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)

    return f"{h:02}h {m:02}m {s:02}s"


@api_bp.route("/health", methods=["GET"])
def health_check():
    print(f"💚 Health check from {request.remote_addr}", flush=True)
    return jsonify(
        {
            "status": "healthy",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model_selected": Config.MODEL,
            "nsfw_enabled": Config.ENABLE_NSFW,
            "thinking_enabled": Config.ENABLE_THINKING,
            "tunnel_provider": Config.TUNNEL_PROVIDER,
        }
    )


@api_bp.route("/status", methods=["GET"])
def status():
    print(f"🌱 Status page viewed", flush=True)
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Proxy Status</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #0f172a;
                color: #e2e8f0;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }}
            .card {{
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 2rem 2.5rem;
                min-width: 320px;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
            }}
            h1 {{
                font-size: 1.25rem;
                margin: 0 0 1.25rem 0;
            }}
            .row {{
                display: flex;
                justify-content: space-between;
                padding: 0.4rem 0;
                border-bottom: 1px solid #334155;
                font-size: 0.9rem;
            }}
            .row:last-child {{
                border-bottom: none;
            }}
            .label {{
                color: #94a3b8;
            }}
            .value {{
                font-weight: 600;
            }}
            .dot {{
                color: #22c55e;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1><span class="dot">&#9679;</span> Google AI Studio Proxy</h1>
            <div class="row"><span class="label">Status</span><span class="value">Online</span></div>
            <div class="row"><span class="label">Uptime</span><span class="value">{format_uptime()}</span></div>
            <div class="row"><span class="label">Current Time</span><span class="value">{time.strftime("%Y-%m-%d %H:%M:%S")}</span></div>
            <div class="row"><span class="label">Thinking</span><span class="value">{"Enabled" if Config.ENABLE_THINKING else "Disabled"}</span></div>
            <div class="row"><span class="label">NSFW</span><span class="value">{"Enabled" if Config.ENABLE_NSFW else "Disabled"}</span></div>
            <div class="row"><span class="label">Tunnel Provider</span><span class="value">{Config.TUNNEL_PROVIDER}</span></div>
        </div>
    </body>
    </html>
    """
    return Response(html, mimetype="text/html")


@api_bp.route("/", methods=["GET", "POST"])
@api_bp.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def handle_proxy():
    # --- BRUTE FORCE CORS PREFLIGHT ---
    if request.method == "OPTIONS":
        response = jsonify({})
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add(
            "Access-Control-Allow-Headers", "Content-Type, Authorization, x-api-key"
        )
        response.headers.add("Access-Control-Allow-Methods", "POST, OPTIONS")
        return response, 200
    # ----------------------------------

    if request.method == "GET":
        return health_check()

    try:
        json_data = request.json or {}
        is_streaming = json_data.get("stream", False)

        # Extract API key
        api_key = None
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header.split(" ")[1]
        elif request.headers.get("x-api-key"):
            api_key = request.headers.get("x-api-key")
        elif json_data.get("api_key"):
            api_key = json_data.get("api_key")
        elif request.args.get("api_key"):
            api_key = request.args.get("api_key")

        if not api_key:
            return jsonify(create_error_response("Google AI API key required.")), 401

        return process_llm_request(json_data, api_key, is_streaming)

    except Exception as e:
        return jsonify(create_error_response(f"Request Error: {str(e)}")), 500
