import json
import re
import sys
import time
import traceback

import requests
from flask import Response, jsonify, stream_with_context

from core.config import Config
from utils.text_parser import StreamingParser, extract_thinking_and_response

# Model configuration registry (ordered by priority, but order doesn't matter due to distinct patterns)
MODEL_REGISTRY = [
    {
        "pattern": r"gemini-([3-9]|\d{2,})",
        "sampling_supported": False,
        "thinking_key": "thinkingLevel",
        "non_thinking_mode": None,
    },
    {
        "pattern": r"gemma-4",
        "sampling_supported": True,
        "thinking_key": "thinkingLevel",
        "non_thinking_mode": "minimal",
    },
    {
        "pattern": r"gemini-2\.5",
        "sampling_supported": True,
        "thinking_key": "thinkingBudget",
        "non_thinking_mode": 0,
    },
]

MAX_RETRIES = 1
RETRY_DELAY = 4

# Safe fallback if DEBUG_MODE isn't in your config yet
debug_mode = getattr(Config, "DEBUG_MODE", True)


def get_model_config(model_name: str) -> dict:
    """Registry entry for the model. Unmatched models fall back to the first row (Gemini 3+)."""
    name = model_name.lower()
    for entry in MODEL_REGISTRY:
        if re.search(entry["pattern"], name):
            return entry
    return MODEL_REGISTRY[0]


class ErrorHandler:
    def __init__(self):
        pass

    def _format_error_message(self, error_message):
        """Centralized error message formatting"""
        return json.dumps(
            str(error_message).replace("Error: ", "", 1)
            if str(error_message).startswith("Error: ")
            else str(error_message)
        )[1:-1]

    def create_error_response(self, error_message):
        """Unified error response for both streaming and non-streaming"""
        # Centralized error message formatting
        clean_message = self._format_error_message(error_message)
        # Standard OpenAI Error Format
        return {"error": {"message": clean_message, "type": "proxy_error"}}

    def create_error_stream_chunk(self, error_message):
        """Streaming-specific error chunk"""
        clean_message = self._format_error_message(error_message)
        # Standard OpenAI Error Format for streams
        error_chunk = {"error": {"message": clean_message, "type": "proxy_error"}}
        return f"data: {json.dumps(error_chunk)}\n\n"


_error_handler = ErrorHandler()


# --- State Management ---
class _State:
    def __init__(self):
        self.http_session = requests.Session()
        self.server_error_count = 0
        self.success_count = 0
        self.error_threshold = 100
        self.success_streak_required = 3

    def reset_connection_pool(self):
        """Force-closes the existing connection pool and builds a brand new one."""
        print(
            "\n🚨 Connection degraded! 3 Server errors reached. Tearing down HTTP pool..."
        )
        try:
            self.http_session.close()
        except Exception:
            pass
        self.http_session = requests.Session()

    def record_server_error(self, status_code, attempt):
        """Logs a strike against the connection pool."""
        self.server_error_count += 1
        self.success_count = 0
        print(
            f"⚠️ Google AI status {status_code} (Strike {self.server_error_count}/{self.error_threshold}) [Attempt {attempt}]"
        )
        if self.server_error_count >= self.error_threshold:
            self.reset_connection_pool()
            self.server_error_count = 0

    def record_success(self):
        """Builds a success streak to clear past strikes."""
        if self.server_error_count > 0:
            self.success_count += 1
            if self.success_count >= self.success_streak_required:
                print(
                    "🟢 Connection stable. 3 consistent successes reached. Clearing error strikes."
                )
                self.server_error_count = 0
                self.success_count = 0


# Create a single instance of the state (replaces your globals)
_state = _State()


class ThinkingDisplay:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self._native_open = False

    def _separator(self):
        print("\n" + "=" * 50)

    def native_stream(self, text):
        """Print incremental native thinking text. Call repeatedly."""
        if not self.enabled or not text:
            return
        if not self._native_open:
            self._separator()
            print("NATIVE THINKING PROCESS:")
            self._native_open = True
        sys.stdout.write(text)
        sys.stdout.flush()

    def close_native_stream(self):
        """Close the native thinking box when normal content starts."""
        if self._native_open:
            print("\n" + "=" * 50 + "\n")
            self._native_open = False

    def block(self, title, text):
        """Print a complete thinking block (non‑stream or simulated)."""
        if not self.enabled or not text:
            return
        self._separator()
        print(title)
        print(text)
        self._separator()


def log_raw_stream_chunk(chunk_str):
    """
    Print a truncated version of any raw SSE chunk that contains
    a finishReason or an error. Called before JSON parsing.
    """
    if not debug_mode:
        return

    if "finishReason" in chunk_str or "error" in chunk_str:
        printed = chunk_str
        if "thoughtSignature" in printed:
            printed = re.sub(
                r'("thoughtSignature":\s*")[^"]+(")',
                r"\1...[TRUNCATED SIGNATURE]\2",
                printed,
            )
        print(f"\n🚨 RAW GOOGLE API INTERCEPT:\n{printed}\n")


def log_parsed_response(data, is_streaming):
    if not debug_mode:
        return

    # Token usage: only for non‑streaming (streaming raw print already contains it)
    if not is_streaming and "usageMetadata" in data:
        print("\n📊 TOKEN USAGE:")
        print(json.dumps(data["usageMetadata"], indent=2))

    # Safety blocks
    prompt_feedback = data.get("promptFeedback")
    if prompt_feedback and prompt_feedback.get("blockReason"):
        print(
            f"\n🚨 GOOGLE BLOCKED THE PROMPT! Reason: {prompt_feedback['blockReason']}"
        )
        if "safetyRatings" in prompt_feedback:
            print(
                f"🚨 Details: {json.dumps(prompt_feedback['safetyRatings'], indent=2)}"
            )

    # Unusual finish reasons
    candidates = data.get("candidates")
    if candidates:
        reason = candidates[0].get("finishReason")
        if reason and reason not in ("STOP", None):
            print(f"\n🚨 GENERATION KILLED! Reason: {reason}")
            if "safetyRatings" in candidates[0]:
                print(
                    f"🚨 Safety Trigger: {json.dumps(candidates[0]['safetyRatings'], indent=2)}"
                )


def log_diagnostic_payload(google_ai_request):
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


def get_safety_settings(model_name):
    if not model_name:
        return []
    return [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]


def build_janitor_response(object_type, id_prefix, model_name, choice):
    now = int(time.time())
    return {
        "id": f"{id_prefix}{now}",
        "object": object_type,
        "created": now,
        "model": model_name,
        "choices": [{"index": 0, **choice}],
    }


def build_gemini_payload(json_data, selected_model):
    """
    Extracts system components for the root instruction, enforces strict
    role alternation, and anchors constraints safely to the final user turn.
    """

    messages = json_data.get("messages", [])

    if not messages or not isinstance(messages, list):
        return None

    system_instructions = []
    google_ai_contents = []

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
            if google_ai_contents and google_ai_contents[-1]["role"] == google_role:
                google_ai_contents[-1]["parts"][0]["text"] += f"\n\n{content}"
            else:
                google_ai_contents.append(
                    {"role": google_role, "parts": [{"text": content}]}
                )

    model_registry = get_model_config(selected_model)
    model_thinking_type = model_registry["thinking_key"]

    # Map the thinking key to its corresponding Config value
    THINKING_VALUE_MAP = {
        "thinkingLevel": Config.THINKING_LEVEL,
        "thinkingBudget": Config.THINKING_BUDGET,
    }

    is_native_thinking = (
        THINKING_VALUE_MAP[model_thinking_type] != model_registry["non_thinking_mode"]
    )

    # 2. Add Proxy-Level System Instructions (Thinking rules, etc.)
    if getattr(Config, "ENABLE_THINKING", False):
        formatted_prompt = Config.get_formatted_thinking_prompt(
            is_native_thinking=is_native_thinking
        )
        system_instructions.append(f"[Core Instructions]:\n{formatted_prompt}")

    system_instruction_text = "\n\n---\n\n".join(system_instructions)

    system_instruction = (
        {"role": "system", "parts": [{"text": system_instruction_text}]}
        if system_instruction_text
        else None
    )

    # 3. Anchor Dynamic Constraints
    constraint_text = ""
    if getattr(Config, "ENABLE_NSFW", False) and getattr(Config, "NSFW_PREFILL", ""):
        constraint_text += f"\n\n[SYSTEM REMINDER: {Config.NSFW_PREFILL}]"

    # NEW: Fetch the dynamically formatted reminder
    if getattr(Config, "ENABLE_THINKING", False):
        safe_reminder = Config.get_formatted_reminder(is_native_thinking)
        constraint_text += f"\n\n{safe_reminder}"

    # Safely anchor constraints with a fallback for edge cases
    if constraint_text:
        injected = False
        if google_ai_contents:
            # Try to anchor to the most recent user message
            for i in range(len(google_ai_contents) - 1, -1, -1):
                if google_ai_contents[i]["role"] == "user":
                    google_ai_contents[i]["parts"][0]["text"] += (
                        f"\n\n{constraint_text.strip()}"
                    )
                    injected = True
                    break

        # FALLBACK: If history is empty, or there was NO user message (e.g., swiping a greeting)
        if not injected:
            # Prepend a user turn to hold the rules, keeping the user->model alternation legal
            google_ai_contents.insert(
                0, {"role": "user", "parts": [{"text": constraint_text.strip()}]}
            )

    if not google_ai_contents:
        return None

    model_config = get_model_config(selected_model)

    generation_config = {
        "maxOutputTokens": Config.MAX_TOKENS,
    }

    if model_config["sampling_supported"]:
        generation_config["temperature"] = json_data.get(
            "temperature", Config.TEMPERATURE
        )
        generation_config["topP"] = json_data.get("top_p", Config.TOP_P)
        generation_config["topK"] = json_data.get("top_k", Config.TOP_K)

    # Map the thinking key to its corresponding Config value
    THINKING_VALUE_MAP = {
        "thinkingLevel": Config.THINKING_LEVEL,
        "thinkingBudget": Config.THINKING_BUDGET,
    }

    generation_config["thinkingConfig"] = {
        model_config["thinking_key"]: THINKING_VALUE_MAP[model_config["thinking_key"]],
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
        google_ai_request["tools"] = [{"googleSearch": {}}]

    return google_ai_request


def _extract_google_error(response, debug_mode):
    """Extract a clean error message from a non-200 Google response."""
    if debug_mode:
        print("\n🚨 GOOGLE API ERROR BODY 🚨")
        print(response.text + "\n")
    clean_error_msg = f"HTTP {response.status_code} Error"
    try:
        error_data = response.json()
        if "error" in error_data and "message" in error_data["error"]:
            clean_error_msg = (
                f"{response.status_code}: {error_data['error']['message']}"
            )
    except Exception:
        pass
    return clean_error_msg


def _post_with_retry(url, headers, payload, stream, debug_mode):
    """Make HTTP POST with retry. Returns a Response or raises."""
    response = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if debug_mode:
                print(f"Connecting to Google AI (Attempt {attempt}/{MAX_RETRIES})...")

            response = _state.http_session.post(
                url,
                json=payload,
                headers=headers,
                stream=stream,
                timeout=Config.REQUEST_TIMEOUT_SECONDS,
            )

            if debug_mode:
                print(f"Google AI response status: {response.status_code}")

            # Retryable server errors
            if response.status_code in [500, 502, 503, 504]:
                _state.record_server_error(response.status_code, attempt)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
                    continue
                # If last attempt, fall through to non-200 handling
                # (no double counting because we already recorded above)

            # Any non-200 error
            if response.status_code != 200:
                clean_error_msg = _extract_google_error(response, debug_mode)
                raise Exception(clean_error_msg)

            # Success
            _state.record_success()
            return response

        except Exception as e:
            # If the exception was raised by our own code (HTTP error), we already recorded.
            # Only record here for network-level exceptions or other unexpected errors.
            if response is None or response.status_code not in [500, 502, 503, 504]:
                _state.record_server_error(500, attempt)  # network/unexpected

            if attempt == MAX_RETRIES:
                raise Exception(
                    f"Proxy connection failed after {MAX_RETRIES} attempts: {str(e)}"
                )
            time.sleep(RETRY_DELAY * attempt)

    # This line is now truly unreachable, but kept as a safety net (or remove it)
    raise Exception("Failed to establish connection to Google AI.")


def _extract_parts(candidate):
    """Return (native_thinking_text, visible_content_text) from a candidate."""
    native_thinking_text = ""
    visible_content_text = ""
    if "content" in candidate and "parts" in candidate["content"]:
        for part in candidate["content"]["parts"]:
            if "text" in part:
                if part.get("thought"):
                    native_thinking_text += part["text"]
                else:
                    visible_content_text += part["text"]
    return native_thinking_text, visible_content_text


def build_block_message(data):
    candidates = data.get("candidates") or [{}]
    finish_reason = candidates[0].get("finishReason")
    prompt_feedback = data.get("promptFeedback") or {}
    msg = "No content received from Google AI."
    if finish_reason and finish_reason != "STOP":
        msg += f" Finish Reason: {finish_reason}."
    if prompt_feedback.get("blockReason"):
        msg += f" Block Reason: {prompt_feedback['blockReason']}."
        details = prompt_feedback.get("safetyRatings")
        if details:
            msg += f" Details: {json.dumps(details)}"
    return msg


def generate_stream(selected_model, url, google_ai_request, headers, debug_mode):

    parser = StreamingParser(getattr(Config, "DISPLAY_THINKING_IN_COLAB", True))

    display = ThinkingDisplay(
        debug_mode and getattr(Config, "DISPLAY_THINKING_IN_COLAB", True)
    )

    # Establish connection with retries
    try:
        response = _post_with_retry(url, headers, google_ai_request, True, debug_mode)
    except Exception as e:
        yield _error_handler.create_error_stream_chunk(str(e))
        yield "data: [DONE]\n\n"
        return

    # Process Stream
    try:
        has_sent_data = False
        last_keepalive = time.time()  # <-- NEW: Track the heartbeat timer

        for chunk in response.iter_lines():
            if not chunk:
                continue

            chunk_str = chunk.decode("utf-8")

            # --- AGGRESSIVE ERROR CATCHER ---
            log_raw_stream_chunk(chunk_str)
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
                log_parsed_response(data, is_streaming=True)
                # ----------------------------------

                if "error" in data:
                    err_msg = data["error"].get("message", "Unknown stream error")
                    print(f"Error in stream data: {err_msg}")
                    yield _error_handler.create_error_stream_chunk(
                        f"Google AI Error: {err_msg}"
                    )
                    yield "data: [DONE]\n\n"
                    return

                candidate = (data.get("candidates") or [{}])[0]
                thought_delta, content_delta = _extract_parts(candidate)
                finish_reason = candidate.get("finishReason")

                if debug_mode and getattr(Config, "DISPLAY_THINKING_IN_COLAB", True):
                    if thought_delta:
                        display.native_stream(thought_delta)
                    elif content_delta:
                        display.close_native_stream()

                if not content_delta and not finish_reason:
                    continue

                if Config.ENABLE_THINKING:
                    content_to_send, thinking_for_colab, is_complete = (
                        parser.process_chunk(content_delta)
                    )

                    if thinking_for_colab:
                        display.block("SIMULATED THINKING PROCESS:", thinking_for_colab)

                    # The stream is ending (Google sent a finishReason)
                    # but the parser never saw a full, well-formed set
                    # of tags -- e.g. an unbounded preamble before
                    # <proxy_reasoning>, a MAX_TOKENS cutoff, or a
                    # model that skipped the tags entirely. Fall back
                    # to the same lenient logic the non-streaming path
                    # already uses instead of leaking or losing the turn.

                    if finish_reason and not is_complete:
                        finalize_text, finalize_thinking, _ = parser.finalize()

                        if finalize_thinking:
                            display.block(
                                "SIMULATED THINKING PROCESS (finalize):",
                                finalize_thinking,
                            )

                        content_to_send = (content_to_send or "") + finalize_text

                else:
                    content_to_send = content_delta

                if content_to_send:
                    has_sent_data = True
                    choice = {
                        "delta": {"content": content_to_send},
                        "finish_reason": finish_reason
                        if finish_reason and finish_reason != "STOP"
                        else None,
                    }
                    chunk = build_janitor_response(
                        "chat.completion.chunk",
                        "chatcmpl-stream-",
                        selected_model,
                        choice,
                    )
                    yield f"data: {json.dumps(chunk)}\n\n"
                else:
                    # --- THE HEARTBEAT FIX ---
                    # We are buffering thought tags. Send an invisible pulse every 2 seconds to keep JanitorAI alive.
                    if time.time() - last_keepalive > 2:
                        yield ": heartbeat\n\n"
                        last_keepalive = time.time()

            except json.JSONDecodeError as json_err:
                if debug_mode:
                    print(f"Warning: Could not decode JSON: {json_err}")
                continue

        if not has_sent_data:
            print("Warning: No content was sent to JanitorAI.")
            yield _error_handler.create_error_stream_chunk(
                "No content received from Google AI."
            )
            yield "data: [DONE]\n\n"

    except Exception as e:
        print(f"Error during streaming: {e}")
        traceback.print_exc()
        yield _error_handler.create_error_stream_chunk(
            f"Error during streaming parsing: {e}"
        )
        yield "data: [DONE]\n\n"

    finally:
        if response:
            response.close()


def generate_non_stream(selected_model, url, google_ai_request, headers, debug_mode):

    if debug_mode:
        print("Sending request to Google AI (non-streaming)...")

    display = ThinkingDisplay(getattr(Config, "DISPLAY_THINKING_IN_COLAB", True))

    try:
        response = _post_with_retry(url, headers, google_ai_request, False, debug_mode)
    except Exception as e:
        return jsonify(_error_handler.create_error_response(str(e))), 500

    try:
        google_response = response.json()
    except json.JSONDecodeError:
        return jsonify(
            _error_handler.create_error_response(
                "Google AI returned an invalid, non-JSON response."
            )
        ), 502

    # --- NEW: NON-STREAMING DIAGNOSTICS & USAGE METADATA ---
    log_parsed_response(google_response, is_streaming=False)
    # -------------------------------------------------------

    # Non-streaming autopsy builder
    candidates = google_response.get("candidates")
    if not candidates or not candidates[0].get("content"):
        filter_msg = build_block_message(google_response)
        print(f"Warning: {filter_msg}")
        return jsonify(_error_handler.create_error_response(filter_msg)), 200

    candidate = candidates[0]
    native_thinking_text, visible_content_text = _extract_parts(candidate)

    # Print Native Thoughts to terminal console
    if native_thinking_text:
        display.block(
            "NATIVE THINKING PROCESS (NON‑STREAMING):", native_thinking_text.strip()
        )

    content = visible_content_text

    # --- NEW: Parse out thoughts for non-streaming mode ---
    if getattr(Config, "ENABLE_THINKING", False):
        thinking_content, parsed_response, _ = extract_thinking_and_response(content)

        # Print thoughts to colab console if enabled
        if thinking_content:
            display.block(
                "SIMULATED THINKING PROCESS (NON‑STREAMING):", thinking_content
            )

        # Only send the cleaned response to Janitor
        if parsed_response:
            content = parsed_response
    # ------------------------------------------------------

    choice = {
        "message": {"role": "assistant", "content": content},
        "finish_reason": candidate.get("finishReason", "stop"),
    }
    response_body = build_janitor_response(
        "chat.completion", "chatcmpl-", selected_model, choice
    )
    return jsonify(response_body)


def process_llm_request(json_data, api_key, is_streaming):

    try:
        if debug_mode:
            request_time = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{request_time}] Received request")

        selected_model = (
            json_data.get("model")
            if json_data.get("model") and json_data["model"] != "custom"
            else Config.MODEL
        )

        if debug_mode:
            print(f"Using model: {selected_model}")

        google_ai_request = build_gemini_payload(json_data, selected_model)

        if google_ai_request is None:
            print("Error: Invalid or empty message format received.")
            return jsonify(
                _error_handler.create_error_response("Invalid or empty message format")
            ), 400

        # --- DIAGNOSTIC PAYLOAD LOGGING ---
        log_diagnostic_payload(google_ai_request)
        # ----------------------------------

        endpoint = "streamGenerateContent" if is_streaming else "generateContent"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:{endpoint}?key={api_key}"

        if is_streaming:
            url += "&alt=sse"

        headers = {"Content-Type": "application/json"}

        # ---------------------------------------------
        # True Processing Starts Over Here
        # ---------------------------------------------

        # 3. Handle Streaming
        if is_streaming:
            return Response(
                stream_with_context(
                    generate_stream(
                        selected_model, url, google_ai_request, headers, debug_mode
                    )
                ),
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
            return generate_non_stream(
                selected_model, url, google_ai_request, headers, debug_mode
            )

    except Exception as e:
        print(f"Unexpected error in proxy handler: {str(e)}")
        traceback.print_exc()
        return jsonify(
            _error_handler.create_error_response(f"Proxy Internal Error: {str(e)}")
        ), 500
