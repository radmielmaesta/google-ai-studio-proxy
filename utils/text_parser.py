"""
Text parsing utilities for handling thinking and response content.
"""

from core.config import Config


def extract_thinking_and_response(content):
    """
    Extract thinking and response content with lenient parsing.
    Keeps </think> and <response> tags in the output to maintain them in chat history.
    Returns: (thinking_content, final_response, parsing_success)
    """

    # First, check if we have the ideal format
    think_start = content.find("<think>")
    think_end = content.find("</think>")
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
            thinking_content = content[think_start + 7 : think_end].strip()
            # Keep </think> and everything after in the response for chat history
            final_response = content[think_end:].strip()
            return thinking_content, final_response, True

    # Fallback 1: Look for </think> and treat everything before as thinking
    if think_end != -1:
        # Extract everything up to </think> as thinking (excluding the tag)
        thinking_part = content[:think_end]
        # Remove <think> tag if present
        if "<think>" in thinking_part:
            thinking_part = thinking_part.split("<think>", 1)[1]
        thinking_content = thinking_part.strip()

        # Keep </think> and everything after as the response
        final_response = content[think_end:].strip()

        if Config.ENABLE_THINKING and Config.DISPLAY_THINKING_IN_COLAB:
            print("INFO: Used lenient parsing with </think> marker")

        return thinking_content, final_response, False

    # Fallback 2: Look for <response> alone
    if response_start != -1:
        # Everything before <response> is thinking
        thinking_content = content[:response_start].strip()
        # Remove <think> tag if present
        if "<think>" in thinking_content:
            thinking_content = thinking_content.split("<think>", 1)[1].strip()

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
                if "<think>" in self.buffer:
                    # Explicit tags detected, go into strict lockdown
                    self.state = "searching"
                    continue
                elif len(self.buffer) > 15:
                    # 15 chars passed with no <think> tag.
                    # The model is using native thoughtSignature. Open the gates!
                    self.buffer = self.buffer.replace("<response>", "").replace(
                        "<respon", ""
                    )
                    self.state = "in_response"
                    continue
                else:
                    break

            elif self.state == "searching":
                # STRICT LOCKDOWN: We are inside the explicit thought.
                if "</think>" in self.buffer:
                    parts = self.buffer.split("</think>", 1)

                    # Extract the thinking part for the terminal
                    thinking_part = self.all_content[
                        : self.all_content.find("</think>")
                    ]
                    if "<think>" in thinking_part:
                        thinking_part = thinking_part.split("<think>", 1)[1]
                    self.thinking_content = thinking_part.strip()

                    if self.display_thinking_in_colab:
                        thinking_for_colab = self.thinking_content

                    # Drop </think> and move into the Airlock
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
                    self.buffer = parts[1]
                    self.state = "in_response"
                    continue
                elif len(self.buffer) > 40:
                    # If 40 chars pass without a response tag, it forgot. Open the gates.
                    self.buffer = self.buffer.replace("<response>", "").replace(
                        "<respon", ""
                    )
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
                self.buffer = ""
                break

        is_complete = self.state == "finished"
        return content_to_send, thinking_for_colab, is_complete
        is_complete = self.state == "finished"
        return content_to_send, thinking_for_colab, is_complete
