import json
import time
import traceback

import requests
from flask import Response, jsonify, stream_with_context

from core.config import Config
from utils.text_parser import StreamingParser

# --- SMART CONNECTION POOLING ---
_http_session = requests.Session()
_server_error_count = 0
_success_count = 0

_ERROR_THRESHOLD = 3
_SUCCESS_STREAK_REQUIRED = 3


def reset_connection_pool():
    """Force-closes the existing connection pool and builds a brand new one."""
    global _http_session
    print("🚨 Connection degraded! 3 Server errors reached. Tearing down HTTP pool...")
    try:
        _http_session.close()
    except Exception:
        pass
    _http_session = requests.Session()


def record_server_error(status_code, attempt):
    """Logs a strike against the connection pool."""
    global _server_error_count, _success_count

    _server_error_count += 1
    _success_count = 0  # Break any ongoing success streak

    print(
        f"⚠️ Google AI status {status_code} (Strike {_server_error_count}/{_ERROR_THRESHOLD}) [Attempt {attempt}]"
    )

    if _server_error_count >= _ERROR_THRESHOLD:
        reset_connection_pool()
        _server_error_count = 0  # Reset the strike counter after taking action


def record_success():
    """Builds a success streak to clear past strikes."""
    global _server_error_count, _success_count

    # Only bother tracking successes if we actually have strikes against us
    if _server_error_count > 0:
        _success_count += 1
        if _success_count >= _SUCCESS_STREAK_REQUIRED:
            print(
                "🟢 Connection stable. 3 consistent successes reached. Clearing error strikes."
            )
            _server_error_count = 0
            _success_count = 0


def create_error_response(error_message):
    clean_message = json.dumps(
        str(error_message).replace("Error: ", "", 1)
        if str(error_message).startswith("Error: ")
        else str(error_message)
    )[1:-1]
    return {
        "choices": [{"message": {"content": clean_message}, "finish_reason": "error"}]
    }


def create_error_stream_chunk(error_message):
    clean_message = json.dumps(
        str(error_message).replace("Error: ", "", 1)
        if str(error_message).startswith("Error: ")
        else str(error_message)
    )[1:-1]
    error_chunk = {
        "choices": [{"delta": {"content": clean_message}, "finish_reason": "error"}]
    }
    return f"data: {json.dumps(error_chunk)}\n\n"


def get_safety_settings(model_name):
    if not model_name:
        return []
    return [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]


def transform_janitor_to_google_ai(messages):
    if not messages or not isinstance(messages, list):
        return []
    google_ai_contents = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if not content or role not in ["user", "assistant", "system"]:
            continue

        google_role = "user" if role in ["user", "system"] else "model"

        if google_ai_contents and google_ai_contents[-1]["role"] == google_role:
            google_ai_contents[-1]["parts"][0]["text"] += f"\n\n{content}"
        else:
            google_ai_contents.append(
                {"role": google_role, "parts": [{"text": content}]}
            )

    if google_ai_contents and google_ai_contents[-1]["role"] == "model":
        google_ai_contents.pop()

    return google_ai_contents


def create_janitor_chunk(content, model_name, finish_reason=None):
    return {
        "id": f"chatcmpl-stream-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": finish_reason
                if finish_reason and finish_reason != "STOP"
                else None,
            }
        ],
    }


def process_llm_request(json_data, api_key, is_streaming):
    global _http_session
    try:
        # 1. Prefill Logic
        if Config.ENABLE_NSFW or Config.ENABLE_THINKING:
            messages = json_data.get("messages", [])

            if messages and messages[-1].get("role") == "user":
                if Config.ENABLE_NSFW and Config.NSFW_PREFILL:
                    messages.append({"content": Config.NSFW_PREFILL, "role": "system"})
                if Config.ENABLE_THINKING:
                    messages.append(
                        {"content": Config.THINKING_PROMPT, "role": "system"}
                    )
                    messages.append({"content": Config.REMINDER, "role": "system"})
                messages.append(
                    {
                        "content": Config.get_custom_assistant_prompt(),
                        "role": "assistant",
                    }
                )

            elif messages and messages[-1].get("role") == "assistant":
                existing_content = messages[-1].get("content", "")
                last_assistant = messages.pop()

                if Config.ENABLE_NSFW and Config.NSFW_PREFILL:
                    messages.append({"content": Config.NSFW_PREFILL, "role": "system"})
                if Config.ENABLE_THINKING:
                    messages.append(
                        {"content": Config.THINKING_PROMPT, "role": "system"}
                    )
                    messages.append({"content": Config.REMINDER, "role": "system"})

                if existing_content.strip() and (
                    not Config.ENABLE_NSFW
                    or existing_content.strip() != Config.NSFW_PREFILL.strip()
                ):
                    messages.append(last_assistant)

                messages.append(
                    {
                        "content": Config.get_custom_assistant_prompt(),
                        "role": "assistant",
                    }
                )

            json_data["messages"] = messages

        # 2. Setup Google AI Request
        selected_model = (
            json_data.get("model")
            if json_data.get("model") and json_data["model"] != "custom"
            else Config.MODEL
        )
        google_ai_contents = transform_janitor_to_google_ai(
            json_data.get("messages", [])
        )

        if not google_ai_contents:
            return jsonify(
                create_error_response("Invalid or empty message format")
            ), 400

        generation_config = {
            "temperature": json_data.get("temperature", Config.TEMPERATURE),
            "maxOutputTokens": json_data.get("max_tokens", Config.MAX_TOKENS),
            "topP": json_data.get("top_p", Config.TOP_P),
            "topK": json_data.get("top_k", Config.TOP_K),
        }

        google_ai_request = {
            "contents": google_ai_contents,
            "generationConfig": generation_config,
        }

        if "gemini" in selected_model.lower():
            google_ai_request["safetySettings"] = get_safety_settings(selected_model)
            if json_data.get("frequency_penalty") is not None:
                generation_config["frequencyPenalty"] = json_data.get(
                    "frequency_penalty"
                )
            if json_data.get("presence_penalty") is not None:
                generation_config["presencePenalty"] = json_data.get("presence_penalty")

        if Config.ENABLE_GOOGLE_SEARCH:
            google_ai_request["tools"] = [{"google_search": {}}]

        endpoint = "streamGenerateContent" if is_streaming else "generateContent"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:{endpoint}?key={api_key}"
        if is_streaming:
            url += "&alt=sse"

        headers = {"Content-Type": "application/json"}

        # 3. Handle Streaming with Retry & Connection Reset Support
        if is_streaming:

            def generate_stream():
                parser = StreamingParser(Config.DISPLAY_THINKING_IN_COLAB)
                response = None
                max_retries = 3
                retry_delay = 1.5

                # Initial HTTP connection retry loop
                for attempt in range(1, max_retries + 1):
                    try:
                        response = _http_session.post(
                            url,
                            json=google_ai_request,
                            headers=headers,
                            stream=True,
                            timeout=Config.REQUEST_TIMEOUT_SECONDS,
                        )

                        # If upstream hits a server error (500/503), trigger connection recovery
                        if response.status_code in [500, 502, 503, 504]:
                            print(
                                f"⚠️ Google AI returned status {response.status_code} (Attempt {attempt}/{max_retries})"
                            )
                            record_server_error(response.status_code, attempt)
                            if attempt < max_retries:
                                time.sleep(retry_delay * attempt)  # Progressive backoff
                                continue

                        response.raise_for_status
                        record_success()
                        break  # Successfully connected, break out of retry loop

                    except (requests.RequestException, Exception) as e:
                        print(
                            f"⚠️ Connection error on attempt {attempt}/{max_retries}: {str(e)}"
                        )
                        reset_connection_pool()
                        if attempt == max_retries:
                            yield create_error_stream_chunk(
                                f"Proxy Connection failed after {max_retries} attempts: {str(e)}"
                            )
                            yield "data: [DONE]\n\n"
                            return
                        time.sleep(retry_delay * attempt)

                if not response:
                    yield create_error_stream_chunk(
                        "Failed to establish connection to Google AI."
                    )
                    yield "data: [DONE]\n\n"
                    return

                # Process the established data stream
                try:
                    has_sent_data = False
                    for chunk in response.iter_lines():
                        if not chunk:
                            continue
                        chunk_str = chunk.decode("utf-8")

                        if not chunk_str.startswith("data: "):
                            continue
                        data_str = chunk_str[len("data: ") :].strip()
                        if data_str == "[DONE]":
                            yield "data: [DONE]\n\n"
                            break

                        data = json.loads(data_str)
                        if "error" in data:
                            yield create_error_stream_chunk(
                                f"Google AI Error: {data['error'].get('message')}"
                            )
                            yield "data: [DONE]\n\n"
                            return

                        content_delta = ""
                        finish_reason = None
                        if "candidates" in data and data["candidates"]:
                            candidate = data["candidates"][0]
                            if (
                                "content" in candidate
                                and "parts" in candidate["content"]
                            ):
                                for part in candidate["content"]["parts"]:
                                    if "text" in part:
                                        content_delta += part["text"]
                            finish_reason = candidate.get("finishReason")

                        if not content_delta:
                            continue

                        if Config.ENABLE_THINKING:
                            content_to_send, _, _ = parser.process_chunk(content_delta)
                        else:
                            content_to_send = content_delta

                        if content_to_send:
                            has_sent_data = True
                            yield f"data: {json.dumps(create_janitor_chunk(content_to_send, selected_model, finish_reason))}\n\n"

                    if not has_sent_data:
                        yield create_error_stream_chunk(
                            "No content received from Google AI."
                        )
                        yield "data: [DONE]\n\n"

                except Exception as e:
                    yield create_error_stream_chunk(
                        f"Error during streaming parsing: {e}"
                    )
                    yield "data: [DONE]\n\n"
                finally:
                    if response:
                        response.close()

            return Response(
                stream_with_context(generate_stream()), content_type="text/event-stream"
            )

        # 4. Handle Non-Streaming with Retry Support
        else:
            max_retries = 3
            retry_delay = 1.5
            response = None

            for attempt in range(1, max_retries + 1):
                try:
                    response = _http_session.post(
                        url,
                        json=google_ai_request,
                        headers=headers,
                        timeout=Config.REQUEST_TIMEOUT_SECONDS,
                    )
                    if response.status_code in [500, 502, 503, 504]:
                        record_server_error(response.status_code, attempt)
                        if attempt < max_retries:
                            time.sleep(retry_delay * attempt)
                            continue
                    response.raise_for_status()
                    record_success()
                    break
                except Exception as e:
                    reset_connection_pool()
                    if attempt == max_retries:
                        return jsonify(
                            create_error_response(
                                f"Google AI non-stream request failed after retries: {str(e)}"
                            )
                        ), 500
                    time.sleep(retry_delay * attempt)

            # 1. Guard against empty responses (e.g., max_retries = 0)
            if not response:
                return jsonify(
                    create_error_response(
                        "Failed to establish connection to Google AI."
                    )
                ), 500

            # 2. Guard against invalid JSON (e.g., HTML firewall intercepts)
            try:
                google_response = response.json()
            except json.JSONDecodeError:
                return jsonify(
                    create_error_response(
                        "Google AI returned an invalid, non-JSON response."
                    )
                ), 502

            candidate = google_response["candidates"][0]
            content = "".join(
                [
                    part["text"]
                    for part in candidate["content"]["parts"]
                    if "text" in part
                ]
            )

            janitor_response = {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": selected_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": candidate.get("finishReason", "stop"),
                    }
                ],
            }
            return jsonify(janitor_response)

    except Exception as e:
        traceback.print_exc()
        return jsonify(create_error_response(f"Proxy Internal Error: {str(e)}")), 500
