import time

from core.config import Config
from flask import Blueprint, jsonify, request
from services.llm_streamer import create_error_response, process_llm_request

api_bp = Blueprint("api", __name__)


@api_bp.route("/health", methods=["GET"])
def health_check():
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


@api_bp.route("/", methods=["GET", "POST"])
@api_bp.route("/v1/chat/completions", methods=["POST"])
def handle_proxy():
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
