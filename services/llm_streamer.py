import json
import re
import time
import traceback

import requests
from flask import Response, jsonify, stream_with_context

from core.config import Config
from utils.text_parser import StreamingParser, extract_thinking_and_response

# --- SMART CONNECTION POOLING ---
_http_session = requests.Session()
_server_error_count = 0
_success_count = 0

_ERROR_THRESHOLD = 100
_SUCCESS_STREAK_REQUIRED = 3


def reset_connection_pool():
    """Force-closes the existing connection pool and builds a brand new one."""
    global _http_session
    print(
        "\n🚨 Connection degraded! 3 Server errors reached. Tearing down HTTP pool..."
    )
    try:
        _http_session.close()
    except Exception:
        pass
    _http_session = requests.Session()


def record_server_error(status_code, attempt):
    """Logs a strike against the connection pool."""
    global _server_error_count, _success_count
    _server_error_count += 1
    _success_count = 0
    print(
        f"⚠️ Google AI status {status_code} (Strike {_server_error_count}/{_ERROR_THRESHOLD}) [Attempt {attempt}]"
    )
    if _server_error_count >= _ERROR_THRESHOLD:
        reset_connection_pool()
        _server_error_count = 0


def record_success():
    """Builds a success streak to clear past strikes."""
    global _server_error_count, _success_count
    if _server_error_count > 0:
        _success_count += 1
        if _success_count >= _SUCCESS_STREAK_REQUIRED:
            print(
                "🟢 Connection stable. 3 consistent successes reached. Clearing error strikes."
            )
            _server_error_count = 0
            _success_count = 0


# --------------------------------


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


# --- NEW: PURE PIPELINE TRANSFORMATION ---
def build_gemini_payload(messages, selected_model):
    """
    Extracts system components for the root instruction, enforces strict
    role alternation, and anchors constraints safely to the final user turn.
    """
    if not messages or not isinstance(messages, list):
        return [], None

    system_instructions = []
    clean_history = []

    # 1. Extract System Context & Flatten History
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "").strip()

        if not content:
            continue

        if role == "system":
            system_instructions.append(f"[System/Context]:\n{content}")
        elif role in ["user", "assistant"]:
            google_role = "user" if role == "user" else "model"

            # Collapse back-to-back duplicate roles
            if clean_history and clean_history[-1]["role"] == google_role:
                clean_history[-1]["parts"][0]["text"] += f"\n\n{content}"
            else:
                clean_history.append(
                    {"role": google_role, "parts": [{"text": content}]}
                )

    is_native_thinking = (
        "gemini-3" in selected_model
        or "gemma-4" in selected_model
        or "gemini-2.5" in selected_model
    )

    # 2. Add Proxy-Level System Instructions (Thinking rules, etc.)
    if getattr(Config, "ENABLE_THINKING", False):
        formatted_prompt = Config.get_formatted_thinking_prompt(
            is_native_thinking=is_native_thinking
        )
        system_instructions.append(f"[Core Instructions]:\n{formatted_prompt}")

    system_instruction_text = "\n\n---\n\n".join(system_instructions)
    system_instruction_payload = (
        {"role": "system", "parts": [{"text": system_instruction_text}]}
        if system_instruction_text
        else None
    )

    # 3. Anchor Dynamic Constraints
    constraint_text = ""
    if getattr(Config, "ENABLE_NSFW", False) and getattr(Config, "NSFW_PREFILL", ""):
        constraint_text += f"\n\n[SYSTEM REMINDER: {Config.NSFW_PREFILL}]"

    # NEW: Fetch the dynamically formatted reminder
    if getattr(Config, "ENABLE_THINKING", False) and getattr(Config, "REMINDER", ""):
        safe_reminder = Config.get_formatted_reminder(is_native_thinking)
        constraint_text += f"\n\n{safe_reminder}"

    # Safely anchor constraints with a fallback for edge cases
    if constraint_text:
        injected = False
        if clean_history:
            # Try to anchor to the most recent user message
            for i in range(len(clean_history) - 1, -1, -1):
                if clean_history[i]["role"] == "user":
                    clean_history[i]["parts"][0]["text"] += (
                        f"\n\n{constraint_text.strip()}"
                    )
                    injected = True
                    break

        # FALLBACK: If history is empty, or there was NO user message (e.g., swiping a greeting)
        if not injected:
            # Prepend a user turn to hold the rules, keeping the user->model alternation legal
            clean_history.insert(
                0, {"role": "user", "parts": [{"text": constraint_text.strip()}]}
            )

    return clean_history, system_instruction_payload


# ------------------------------------------


# Restored your Gemma/Gemini compatible transform logic exactly
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
    # Safe fallback if DEBUG_MODE isn't in your config yet
    debug_mode = getattr(Config, "DEBUG_MODE", True)

    try:
        request_time = time.strftime("%Y-%m-%d %H:%M:%S")
        if debug_mode:
            print(f"\n[{request_time}] Received request")

        selected_model = (
            json_data.get("model")
            if json_data.get("model") and json_data["model"] != "custom"
            else Config.MODEL
        )
        if debug_mode:
            print(f"Using model: {selected_model}")

        # --- APPLY THE NEW PIPELINE HERE ---
        # The old list mutation prefill logic has been deleted.
        google_ai_contents, system_instruction = build_gemini_payload(
            json_data.get("messages", []), selected_model
        )
        # -----------------------------------

        if not google_ai_contents:
            print("Error: Invalid or empty message format received.")
            return jsonify(
                create_error_response("Invalid or empty message format")
            ), 400

        generation_config = {
            "temperature": json_data.get("temperature", Config.TEMPERATURE),
            "maxOutputTokens": json_data.get("max_tokens", Config.MAX_TOKENS),
            "topP": json_data.get("top_p", Config.TOP_P),
            "topK": json_data.get("top_k", Config.TOP_K),
        }

        selected_model = selected_model.lower()

        # Conditionally inject thinking config based on the model series
        if "gemini-3" in selected_model or "gemma-4" in selected_model:
            generation_config["thinkingConfig"] = {
                "thinkingLevel": Config.THINKING_LEVEL,
                "includeThoughts": True,
            }
        elif "gemini-2.5" in selected_model:
            generation_config["thinkingConfig"] = {
                "thinkingBudget": Config.THINKING_BUDGET,
                "includeThoughts": True,
            }

        google_ai_request = {
            "contents": google_ai_contents,
            "generationConfig": generation_config,
            "safetySettings": get_safety_settings(selected_model),
        }

        if system_instruction:
            google_ai_request["systemInstruction"] = system_instruction

        if getattr(Config, "ENABLE_GOOGLE_SEARCH", False):
            google_ai_request["tools"] = [{"google_search": {}}]

        # --- DIAGNOSTIC PAYLOAD LOGGING ---
        if debug_mode:
            print("\n" + "=" * 60)
            print("🚀 OUTGOING PAYLOAD TO GOOGLE AI")
            try:
                # 1. Silently dump the massive full payload to a file
                with open("last_payload_debug.json", "w", encoding="utf-8") as f:
                    json.dump(google_ai_request, f, indent=2, ensure_ascii=False)

                # 2. Extract and print ONLY the newest message to the terminal
                contents = google_ai_request.get("contents", [])
                # Type guard: Proves to the linter that 'contents' is definitely a list
                if isinstance(contents, list) and contents:
                    last_msg = contents[-1]
                    role = last_msg.get("role", "unknown")
                    # Truncate text if it's ridiculously long, or just print it
                    text_delta = last_msg["parts"][0].get("text", "")

                    print(f"Total turns in context: {len(contents)}")
                    print(f"Latest Delta [{role.upper()}]:\n")
                    print(text_delta)
                else:
                    print("Warning: Payload contents are empty.")

            except Exception as e:
                print(f"Could not process debug payload: {e}")
            print("=" * 60 + "\n")
        # ----------------------------------

        endpoint = "streamGenerateContent" if is_streaming else "generateContent"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:{endpoint}?key={api_key}"

        if is_streaming:
            url += "&alt=sse"

        headers = {"Content-Type": "application/json"}
        max_retries = 1
        retry_delay = 4

        # 3. Handle Streaming
        if is_streaming:

            def generate_stream():
                parser = StreamingParser(
                    getattr(Config, "DISPLAY_THINKING_IN_COLAB", True)
                )
                response = None

                # Initial Connection Retries
                for attempt in range(1, max_retries + 1):
                    try:
                        if debug_mode:
                            print(
                                f"Connecting to Google AI for streaming (Attempt {attempt}/{max_retries})..."
                            )

                        response = _http_session.post(
                            url,
                            json=google_ai_request,
                            headers=headers,
                            stream=True,
                            timeout=Config.REQUEST_TIMEOUT_SECONDS,
                        )

                        if debug_mode:
                            print(
                                f"Google AI stream response status: {response.status_code}"
                            )

                        if response.status_code in [500, 502, 503, 504]:
                            record_server_error(response.status_code, attempt)
                            if attempt < max_retries:
                                time.sleep(retry_delay * attempt)
                                continue

                        # If it's a 4xx error or other bad status, this raises HTTPError
                        try:
                            response.raise_for_status()
                        except requests.exceptions.HTTPError as e:
                            print("\n🚨 GOOGLE API ERROR BODY 🚨")
                            print(
                                e.response.text
                            )  # Successfully logs the golden ticket
                            raise e  # Sent to outer except block to trigger a retry if attempts remain

                        record_success()
                        break

                    except (requests.RequestException, Exception) as e:
                        record_server_error(500, attempt)
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

                # Process Stream
                try:
                    has_sent_data = False
                    last_keepalive = time.time()  # <-- NEW: Track the heartbeat timer
                    is_printing_thoughts = False  # Tracks if our decoration box is open

                    for chunk in response.iter_lines():
                        if not chunk:
                            continue
                        chunk_str = chunk.decode("utf-8")

                        # --- AGGRESSIVE ERROR CATCHER ---
                        if debug_mode and (
                            "finishReason" in chunk_str or "error" in chunk_str
                        ):
                            # Clean up the massive signatures without reloading modules
                            printed_chunk = chunk_str
                            if "thoughtSignature" in printed_chunk:
                                printed_chunk = re.sub(
                                    r'("thoughtSignature":\s*")[^"]+(")',
                                    r"\1...[TRUNCATED SIGNATURE]\2",
                                    printed_chunk,
                                )
                            print(f"\n🚨 RAW GOOGLE API INTERCEPT:\n{printed_chunk}\n")
                        # --------------------------------

                        if not chunk_str.startswith("data: "):
                            continue
                        data_str = chunk_str[len("data: ") :].strip()
                        if data_str == "[DONE]":
                            if debug_mode:
                                print("Stream finished ([DONE] received).")
                            yield "data: [DONE]\n\n"
                            break

                        try:
                            data = json.loads(data_str)
                            # --- DIAGNOSTIC ERROR REPORTING ---
                            if debug_mode:
                                if "promptFeedback" in data and data[
                                    "promptFeedback"
                                ].get("blockReason"):
                                    print(
                                        f"\n🚨 GOOGLE BLOCKED THE PROMPT! Reason: {data['promptFeedback']['blockReason']}"
                                    )
                                    if "safetyRatings" in data["promptFeedback"]:
                                        print(
                                            f"🚨 Details: {json.dumps(data['promptFeedback']['safetyRatings'])}"
                                        )

                                if "candidates" in data and data["candidates"]:
                                    cand = data["candidates"][0]
                                    reason = cand.get("finishReason")
                                    if reason and reason not in ["STOP", None]:
                                        print(
                                            f"\n🚨 GENERATION KILLED! Reason: {reason}"
                                        )
                                        if "safetyRatings" in cand:
                                            print(
                                                f"🚨 Safety Trigger: {json.dumps(cand['safetyRatings'])}"
                                            )
                            # ----------------------------------

                            if "error" in data:
                                err_msg = data["error"].get(
                                    "message", "Unknown stream error"
                                )
                                print(f"Error in stream data: {err_msg}")
                                yield create_error_stream_chunk(
                                    f"Google AI Error: {err_msg}"
                                )
                                yield "data: [DONE]\n\n"
                                return

                            content_delta = ""
                            thought_delta = ""
                            finish_reason = None
                            if "candidates" in data and data["candidates"]:
                                candidate = data["candidates"][0]
                                if (
                                    "content" in candidate
                                    and "parts" in candidate["content"]
                                ):
                                    for part in candidate["content"]["parts"]:
                                        if "text" in part:
                                            if part.get("thought"):
                                                thought_delta += part["text"]
                                            else:
                                                content_delta += part["text"]
                                finish_reason = candidate.get("finishReason")

                            if debug_mode and getattr(
                                Config, "DISPLAY_THINKING_IN_COLAB", True
                            ):
                                import sys

                                # 1. If we have thoughts to print
                                if thought_delta:
                                    # Open the box if it isn't open yet
                                    if not is_printing_thoughts:
                                        print("\n" + "=" * 50)
                                        print("NATIVE THINKING PROCESS:")
                                        is_printing_thoughts = True

                                    # Stream the word smoothly
                                    sys.stdout.write(thought_delta)
                                    sys.stdout.flush()

                                # 2. If thoughts stopped and standard content starts
                                elif content_delta and is_printing_thoughts:
                                    # Close the box!
                                    print("\n" + "=" * 50 + "\n")
                                    is_printing_thoughts = False

                            if not content_delta and not finish_reason:
                                continue

                            if Config.ENABLE_THINKING:
                                content_to_send, thinking_for_colab, _ = (
                                    parser.process_chunk(content_delta)
                                )
                                if (
                                    debug_mode
                                    and thinking_for_colab
                                    and getattr(
                                        Config, "DISPLAY_THINKING_IN_COLAB", True
                                    )
                                ):
                                    # Print to colab silently without breaking the stream
                                    print("\n" + "=" * 50)
                                    print("SIMULATED THINKING PROCESS:")
                                    print(thinking_for_colab)
                                    print("=" * 50)
                                    pass
                            else:
                                content_to_send = content_delta

                            if content_to_send:
                                has_sent_data = True
                                yield f"data: {json.dumps(create_janitor_chunk(content_to_send, selected_model, finish_reason))}\n\n"
                            else:
                                # --- THE HEARTBEAT FIX ---
                                # We are buffering thought tags. Send an invisible pulse every 2 seconds to keep JanitorAI alive.
                                if time.time() - last_keepalive > 2:
                                    yield f"data: {json.dumps(create_janitor_chunk('\u200b', selected_model, None))}\n\n"
                                    last_keepalive = time.time()

                        except json.JSONDecodeError as json_err:
                            if debug_mode:
                                print(f"Warning: Could not decode JSON: {json_err}")
                            continue

                    if not has_sent_data:
                        print("Warning: No content was sent to JanitorAI.")
                        yield create_error_stream_chunk(
                            "No content received from Google AI."
                        )
                        yield "data: [DONE]\n\n"

                except Exception as e:
                    print(f"Error during streaming: {e}")
                    traceback.print_exc()
                    yield create_error_stream_chunk(
                        f"Error during streaming parsing: {e}"
                    )
                    yield "data: [DONE]\n\n"
                finally:
                    if response:
                        response.close()

            return Response(
                stream_with_context(generate_stream()),
                content_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",  # <-- This is critical
                    "Content-Encoding": "none",
                },
            )

        # 4. Handle Non-Streaming
        else:
            if debug_mode:
                print("Sending request to Google AI (non-streaming)...")
            response = None
            for attempt in range(1, max_retries + 1):
                try:
                    response = _http_session.post(
                        url,
                        json=google_ai_request,
                        headers=headers,
                        timeout=Config.REQUEST_TIMEOUT_SECONDS,
                    )
                    if debug_mode:
                        print(
                            f"Google AI non-stream response status: {response.status_code}"
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
                    record_server_error(500, attempt)
                    if attempt == max_retries:
                        return jsonify(
                            create_error_response(
                                f"Google AI non-stream request failed: {str(e)}"
                            )
                        ), 500
                    time.sleep(retry_delay * attempt)

            if not response:
                return jsonify(
                    create_error_response(
                        "Failed to establish connection to Google AI."
                    )
                ), 500

            try:
                google_response = response.json()
            except json.JSONDecodeError:
                return jsonify(
                    create_error_response(
                        "Google AI returned an invalid, non-JSON response."
                    )
                ), 502

            # Non-streaming autopsy builder
            if not google_response.get("candidates") or not google_response[
                "candidates"
            ][0].get("content"):
                finish_reason = google_response.get("candidates", [{}])[0].get(
                    "finishReason", "UNKNOWN"
                )
                prompt_feedback = google_response.get("promptFeedback")
                filter_msg = "No content received from Google AI."
                if finish_reason != "STOP":
                    filter_msg += f" Finish Reason: {finish_reason}."
                if prompt_feedback and prompt_feedback.get("blockReason"):
                    filter_msg += f" Block Reason: {prompt_feedback['blockReason']}."
                    details = prompt_feedback.get("safetyRatings")
                    if details:
                        filter_msg += f" Details: {json.dumps(details)}"

                print(f"Warning: {filter_msg}")
                return jsonify(create_error_response(filter_msg)), 200

            candidate = google_response["candidates"][0]
            native_thinking_text = ""
            visible_content_text = ""

            # --- SEPARATE NATIVE THOUGHTS FROM VISIBLE CONTENT ---
            if "content" in candidate and "parts" in candidate["content"]:
                for part in candidate["content"]["parts"]:
                    if "text" in part:
                        if part.get("thought"):
                            native_thinking_text += part["text"]
                        else:
                            visible_content_text += part["text"]

            # Print Native Thoughts to terminal console
            if native_thinking_text and getattr(
                Config, "DISPLAY_THINKING_IN_COLAB", True
            ):
                print("\n" + "=" * 50)
                print("NATIVE THINKING PROCESS (NON-STREAMING):")
                print(native_thinking_text.strip())
                print("=" * 50 + "\n")

            content = visible_content_text

            # --- NEW: Parse out thoughts for non-streaming mode ---
            if getattr(Config, "ENABLE_THINKING", False):
                thinking_content, parsed_response, _ = extract_thinking_and_response(
                    content
                )

                # Print thoughts to colab console if enabled
                if thinking_content and getattr(
                    Config, "DISPLAY_THINKING_IN_COLAB", True
                ):
                    print("\n" + "=" * 50)
                    print("SIMULATED THINKING PROCESS (NON-STREAMING):")
                    print(thinking_content)
                    print("=" * 50 + "\n")

                # Only send the cleaned response to Janitor
                if parsed_response:
                    content = parsed_response
            # ------------------------------------------------------

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
        print(f"Unexpected error in proxy handler: {str(e)}")
        traceback.print_exc()
        return jsonify(create_error_response(f"Proxy Internal Error: {str(e)}")), 500
