"""
Text parsing utilities for handling thinking and response content.
"""

from core.config import Config


def extract_thinking_and_response(content):
    """
    Extract thinking and response content with lenient parsing.
    Keeps </proxy_reasoning> and <response> tags in the output to maintain them in chat history.
    Returns: (thinking_content, final_response, parsing_success)
    """

    # First, check if we have the ideal format
    think_start = content.find("<proxy_reasoning>")
    think_end = content.find("</proxy_reasoning>")
    response_start = content.find("<response>")
    response_end = content.find("</response>")

    # Ideal case: all tags present in correct order
    if (
        think_start != -1
        and think_end != -1
        and response_start != -1
        and response_end != -1
    ):
        if think_start < think_end < response_start < response_end:
            thinking_content = content[think_start + 17 : think_end].strip()
            # Keep </proxy_reasoning> and everything after in the response for chat history
            tag_length = len("</proxy_reasoning>")
            final_response = content[think_end + tag_length :].strip()
            return thinking_content, final_response, True

    # Fallback 1: Look for </proxy_reasoning> and treat everything before as thinking
    if think_end != -1:
        # Extract everything up to </proxy_reasoning> as thinking (excluding the tag)
        thinking_part = content[:think_end]
        # Remove <proxy_reasoning> tag if present
        if "<proxy_reasoning>" in thinking_part:
            thinking_part = thinking_part.split("<proxy_reasoning>", 1)[1]
        thinking_content = thinking_part.strip()

        # Keep </proxy_reasoning> and everything after as the response
        tag_length = len("</proxy_reasoning>")
        final_response = content[think_end + tag_length :].strip()

        if Config.ENABLE_THINKING and Config.DISPLAY_THINKING_IN_COLAB:
            print("INFO: Used lenient parsing with </proxy_reasoning> marker")

        return thinking_content, final_response, False

    # Fallback 2: Look for <response> alone
    if response_start != -1:
        # Everything before <response> is thinking
        thinking_content = content[:response_start].strip()
        # Remove <proxy_reasoning> tag if present
        if "<proxy_reasoning>" in thinking_content:
            thinking_content = thinking_content.split("<proxy_reasoning>", 1)[1].strip()

        # Keep <response> and everything after as the response
        final_response = content[response_start:].strip()

        if Config.ENABLE_THINKING and Config.DISPLAY_THINKING_IN_COLAB:
            print("INFO: Used lenient parsing with <response> marker only")

        return thinking_content, final_response, False

    # No tags found - treat entire content as response
    if Config.ENABLE_THINKING:
        print(
            "WARNING: No thinking separation tags found, treating entire content as response"
        )

    return None, content, False


class StreamingParser:
    def __init__(self, display_thinking_in_colab):
        self.reset()
        self.display_thinking_in_colab = display_thinking_in_colab

    def reset(self):
        # Start in a detection phase, NOT immediate lockdown
        self.state = "detecting"
        self.thinking_content = ""
        self.response_content = ""
        self.buffer = ""
        self.all_content = ""

    def process_chunk(self, chunk_content):
        self.buffer += chunk_content
        self.all_content += chunk_content
        content_to_send = ""
        thinking_for_colab = ""

        while True:
            if self.state == "detecting":
                if "<proxy_reasoning>" in self.buffer:
                    # Explicit tags detected, go into strict lockdown
                    self.state = "searching"
                    continue

                # Strip leading whitespace to accurately check the first visible character
                stripped_buffer = self.buffer.lstrip()

                if stripped_buffer.startswith("<"):
                    # The stream is starting with a bracket. It might be building our tag.
                    # Wait patiently, but implement a 30-character fail-safe just in case.
                    if len(self.buffer) >= 30:
                        self.buffer = self.buffer.replace("<response>", "").replace(
                            "<respon", ""
                        )
                        self.state = "in_response"
                        continue
                    else:
                        # Wait for the next chunk to complete the tag
                        break

                elif len(stripped_buffer) > 0:
                    # Starting with normal text, strip any accidental leading newlines
                    # This is definitely not a proxy_reasoning block. Open the gates instantly!
                    self.buffer = self.buffer.lstrip()
                    self.state = "in_response"
                    continue

                else:
                    # The buffer is still empty or just whitespace. Keep waiting.
                    break

            elif self.state == "searching":
                # STRICT LOCKDOWN: We are inside the explicit thought.
                if "</proxy_reasoning>" in self.buffer:
                    parts = self.buffer.split("</proxy_reasoning>", 1)

                    # Extract the thinking part for the terminal
                    thinking_part = self.all_content[
                        : self.all_content.find("</proxy_reasoning>")
                    ]
                    if "<proxy_reasoning>" in thinking_part:
                        thinking_part = thinking_part.split("<proxy_reasoning>", 1)[1]
                    self.thinking_content = thinking_part.strip()

                    if self.display_thinking_in_colab:
                        thinking_for_colab = self.thinking_content

                    # Drop </proxy_reasoning> and move into the Airlock
                    self.buffer = parts[1]
                    self.state = "waiting_for_response"
                    continue
                else:
                    # Eat the text. Send absolutely nothing to JanitorAI.
                    break

            elif self.state == "waiting_for_response":
                # AIRLOCK: Now we actively look for the real <response> tag to delete it.
                if "<response>" in self.buffer:
                    parts = self.buffer.split("<response>", 1)
                    # .lstrip() eats all \n and spaces sitting between <response> and the story
                    self.buffer = parts[1].lstrip()
                    self.state = "in_response"
                    continue
                elif len(self.buffer) > 40:
                    # If 40 chars pass without a response tag, it forgot. Open the gates.
                    self.buffer = (
                        self.buffer.replace("<response>", "")
                        .replace("<respon", "")
                        .lstrip()
                    )  # Clean leading newlines here as well
                    self.state = "in_response"
                    continue
                else:
                    break

            elif self.state == "in_response":
                # Gates are open. Send the pure story to JanitorAI.
                if "</response>" in self.buffer:
                    parts = self.buffer.split("</response>", 1)
                    content_to_send = parts[0]
                    self.response_content += parts[0]
                    self.buffer = ""
                    self.state = "finished"
                else:
                    content_to_send = self.buffer
                    self.response_content += self.buffer
                    self.buffer = ""
                break

            elif self.state == "finished":
                self.response_content = self.response_content.rstrip()
                self.buffer = ""
                break

        is_complete = self.state == "finished"
        return content_to_send, thinking_for_colab, is_complete
