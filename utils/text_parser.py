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
        self.state = "searching"  # States: "searching", "found_think_end", "in_response", "finished"
        self.thinking_content = ""
        self.response_content = ""
        self.buffer = ""
        self.all_content = ""  # Keep track of all content
        self.think_end_sent = False  # Track if we've sent </think>

    def process_chunk(self, chunk_content):
        """
        Process a chunk with lenient tag detection.
        Keeps </think> and <response> tags in the output.
        Returns: (content_to_send, thinking_for_colab, is_complete)
        """
        self.buffer += chunk_content
        self.all_content += chunk_content
        content_to_send = ""
        thinking_for_colab = ""

        while True:
            if self.state == "searching":
                # Look for </think> as our first marker
                if "</think>" in self.buffer:
                    parts = self.buffer.split("</think>", 1)
                    # Everything before </think> is thinking
                    thinking_part = self.all_content[
                        : self.all_content.find("</think>")
                    ]
                    # Remove <think> if present
                    if "<think>" in thinking_part:
                        thinking_part = thinking_part.split("<think>", 1)[1]
                    self.thinking_content = thinking_part.strip()

                    if self.display_thinking_in_colab:
                        thinking_for_colab = self.thinking_content

                    # Keep </think> in buffer to send it
                    self.buffer = "</think>" + parts[1]
                    self.state = "found_think_end"
                    continue
                elif "<response>" in self.buffer:
                    # Found <response> without </think>
                    parts = self.buffer.split("<response>", 1)
                    # Everything before <response> is thinking
                    thinking_part = self.all_content[
                        : self.all_content.find("<response>")
                    ]
                    # Remove <think> if present
                    if "<think>" in thinking_part:
                        thinking_part = thinking_part.split("<think>", 1)[1]
                    self.thinking_content = thinking_part.strip()

                    if self.display_thinking_in_colab:
                        thinking_for_colab = self.thinking_content

                    # Keep <response> in buffer to send it
                    self.buffer = "<response>" + parts[1]
                    self.state = "in_response"
                    continue
                else:
                    # Keep buffering
                    break

            elif self.state == "found_think_end":
                # Send </think> and everything after
                content_to_send = self.buffer
                self.response_content += self.buffer
                self.buffer = ""
                self.state = "in_response"
                break

            elif self.state == "in_response":
                # Send everything as response
                content_to_send = self.buffer
                self.response_content += self.buffer
                self.buffer = ""

                # Check if we've reached the end
                if "</response>" in self.response_content:
                    self.state = "finished"
                break

            elif self.state == "finished":
                # We've processed the main content
                # Discard any remaining buffer content
                self.buffer = ""
                break

        is_complete = self.state == "finished"
        return content_to_send, thinking_for_colab, is_complete
