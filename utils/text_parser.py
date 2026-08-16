"""
Text parsing utilities for handling thinking and response content.

Refactor notes vs. the original:
  - One shared primitive (_dangling_prefix_len) decides "does the tail of
    this buffer look like the start of a delimiter we care about" instead
    of three independently-written heuristics (30-char check, 40-char
    check, and a generic "any '<' within 15 chars" check) that drifted
    from each other and caused the original leak bug.
  - States are an Enum instead of raw strings.
  - The in_response sliding-buffer lookahead now only holds back text that
    could actually be forming "</response>", instead of holding back any
    '<...' pattern (so in-story text like "<3" or "<em>" streams normally).
"""

from enum import Enum, auto

from core.config import Config

OPEN_THINK = "<proxy_reasoning>"
CLOSE_THINK = "</proxy_reasoning>"
OPEN_RESPONSE = "<response>"
CLOSE_RESPONSE = "</response>"

def _dangling_prefix_len(buffer, *delimiters):
    """
    Returns the length of the longest suffix of `buffer` that is a proper
    prefix of ANY given delimiter. That suffix might be the start of a
    delimiter that hasn't fully arrived yet in this chunk, so it isn't
    safe to treat as ordinary text yet -- hold it back and wait for more.

    Unlike a generic "any '<' near the end" heuristic, this only holds
    back text that could genuinely still become one of our delimiters.
    """
    if not buffer:
        return 0
    longest_possible = max(len(d) for d in delimiters) - 1
    max_check = min(longest_possible, len(buffer))
    for i in range(max_check, 0, -1):
        tail = buffer[-i:]
        if any(d.startswith(tail) for d in delimiters):
            return i
    return 0


def extract_thinking_and_response(content):
    """
    Extract thinking and response content with lenient parsing.
    Keeps </proxy_reasoning> and <response> tags in the output to maintain them in chat history.
    Returns: (thinking_content, final_response, parsing_success)
    """
    think_start = content.find(OPEN_THINK)
    think_end = content.find(CLOSE_THINK)
    response_start = content.find(OPEN_RESPONSE)
    response_end = content.find(CLOSE_RESPONSE)

    if (
        think_start != -1
        and think_end != -1
        and response_start != -1
        and response_end != -1
    ):
        if think_start < think_end < response_start < response_end:
            thinking_content = content[think_start + len(OPEN_THINK) : think_end].strip()
            final_response = content[think_end + len(CLOSE_THINK) :].strip()
            return thinking_content, final_response, True

    if think_end != -1:
        thinking_part = content[:think_end]
        if OPEN_THINK in thinking_part:
            thinking_part = thinking_part.split(OPEN_THINK, 1)[1]
        thinking_content = thinking_part.strip()
        final_response = content[think_end + len(CLOSE_THINK) :].strip()

        if Config.ENABLE_THINKING and Config.DISPLAY_THINKING_IN_COLAB:
            print("INFO: Used lenient parsing with </proxy_reasoning> marker")

        return thinking_content, final_response, False

    if response_start != -1:
        thinking_content = content[:response_start].strip()
        if OPEN_THINK in thinking_content:
            thinking_content = thinking_content.split(OPEN_THINK, 1)[1].strip()
        final_response = content[response_start:].strip()

        if Config.ENABLE_THINKING and Config.DISPLAY_THINKING_IN_COLAB:
            print("INFO: Used lenient parsing with <response> marker only")

        return thinking_content, final_response, False

    if Config.ENABLE_THINKING:
        print(
            "WARNING: No thinking separation tags found, treating entire content as response"
        )

    return None, content, False


class _State(Enum):
    DETECTING = auto()
    SEARCHING = auto()
    WAITING_FOR_RESPONSE = auto()
    IN_RESPONSE = auto()
    FINISHED = auto()


class StreamingParser:
    def __init__(self, display_thinking_in_colab):
        self.reset()
        self.display_thinking_in_colab = display_thinking_in_colab

    def reset(self):
        self.state = _State.DETECTING
        self.thinking_content = ""
        self.response_content = ""
        self.buffer = ""
        self.all_content = ""
        self.is_first_text_chunk = True

    def process_chunk(self, chunk_content):
        self.buffer += chunk_content
        self.all_content += chunk_content
        content_to_send = ""
        thinking_for_colab = ""

        while True:
            if self.state == _State.DETECTING:
                if OPEN_THINK in self.buffer:
                    self.state = _State.SEARCHING
                    continue
                # No budget by design: an unbounded model preamble (e.g. an
                # unrequested "*Internal Thought:*" ramble) can't be told
                # apart from "the tag is still forming" by length alone.
                # Wait for either the tag or end-of-stream (see finalize()).
                break

            elif self.state == _State.SEARCHING:
                # No budget here by design: if the model never closes the
                # reasoning block (e.g. truncated by MAX_TOKENS), we deliberately
                # swallow it rather than ever leak raw chain-of-thought text.
                if CLOSE_THINK in self.buffer:
                    parts = self.buffer.split(CLOSE_THINK, 1)

                    thinking_part = self.all_content[: self.all_content.find(CLOSE_THINK)]
                    if OPEN_THINK in thinking_part:
                        thinking_part = thinking_part.split(OPEN_THINK, 1)[1]
                    self.thinking_content = thinking_part.strip()

                    if self.display_thinking_in_colab:
                        thinking_for_colab = self.thinking_content

                    self.buffer = parts[1]
                    self.state = _State.WAITING_FOR_RESPONSE
                    continue
                else:
                    break

            elif self.state == _State.WAITING_FOR_RESPONSE:
                if OPEN_RESPONSE in self.buffer:
                    parts = self.buffer.split(OPEN_RESPONSE, 1)
                    self.buffer = parts[1].lstrip()
                    self.state = _State.IN_RESPONSE
                    continue
                # No budget here either, same reasoning as DETECTING.
                break

            elif self.state == _State.IN_RESPONSE:
                if self.is_first_text_chunk:
                    self.buffer = self.buffer.lstrip()
                    if not self.buffer:
                        break
                    self.is_first_text_chunk = False

                if CLOSE_RESPONSE in self.buffer:
                    parts = self.buffer.split(CLOSE_RESPONSE, 1)
                    content_to_send = parts[0].rstrip()
                    self.response_content += content_to_send
                    self.buffer = ""
                    self.state = _State.FINISHED
                    break

                # Hold back from the end of the buffer: first any tail that
                # could still be forming CLOSE_RESPONSE (not any arbitrary
                # '<' -- so in-story markup like "<3" or "<em>" isn't
                # needlessly delayed), THEN any whitespace immediately
                # before that. The whitespace has to be included in the
                # hold too: until we know whether the dangling tail turns
                # into a real close tag, we can't know yet whether that
                # whitespace is trailing (needs rstrip) or just mid-text.
                buf = self.buffer
                hold_from = len(buf) - _dangling_prefix_len(buf, CLOSE_RESPONSE)
                while hold_from > 0 and buf[hold_from - 1].isspace():
                    hold_from -= 1

                content_to_send = buf[:hold_from]
                self.buffer = buf[hold_from:]
                if content_to_send:
                    self.response_content += content_to_send
                break

            elif self.state == _State.FINISHED:
                self.response_content = self.response_content.rstrip()
                self.buffer = ""
                break

        is_complete = self.state == _State.FINISHED
        return content_to_send, thinking_for_colab, is_complete

    def finalize(self):
        """
        Call this once when the underlying stream ends (finish_reason
        received) if is_complete was never True. Handles every state that
        never got its expected closing delimiter, instead of guessing with
        a per-state character budget.
        Returns: (content_to_send, thinking_for_colab, is_complete=True)
        """
        if self.state == _State.FINISHED:
            return "", "", True

        if self.state == _State.IN_RESPONSE:
            # Model finished without ever sending </response> -- flush
            # whatever was safely held back.
            leftover = self.buffer.rstrip()
            self.response_content += leftover
            self.buffer = ""
            self.state = _State.FINISHED
            return leftover, "", True

        if self.state == _State.SEARCHING:
            # Reasoning block never closed. By design we never leak partial
            # chain-of-thought, so this turn produces no visible text.
            self.state = _State.FINISHED
            return "", "", True

        # DETECTING or WAITING_FOR_RESPONSE: the stream ended without ever
        # matching our expected tag shape at all (e.g. an unbounded
        # preamble, or a model that skipped the tags entirely). Fall back
        # to the same lenient logic the non-streaming path already trusts,
        # instead of a second, different heuristic.
        thinking, response, _ = extract_thinking_and_response(self.all_content)
        self.thinking_content = thinking or ""
        self.response_content = response
        self.buffer = ""
        self.state = _State.FINISHED
        thinking_for_colab = thinking if (self.display_thinking_in_colab and thinking) else ""
        return response, thinking_for_colab, True