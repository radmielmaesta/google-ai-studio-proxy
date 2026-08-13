import os

from dotenv import load_dotenv

load_dotenv()


def _parse_bool(env_var: str, default: str = "false") -> bool:
    """Helper to cleanly convert environment strings to actual booleans."""
    # We check against a tuple so it smartly catches 'true', '1', or 'yes'
    return str(os.getenv(env_var, default)).lower() in ("true", "1", "t", "yes")


class Config:
    """Configuration class for Google AI Studio-JanitorAI Proxy."""

    # API Key (required, no default)
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

    # Tunnel Provider Settings
    TUNNEL_PROVIDER = os.getenv("TUNNEL_PROVIDER", "cloudflare")

    NGROK_TOKEN = os.getenv("NGROK_TOKEN", "")

    NGROK_URL = os.getenv("NGROK_URL", "")

    # Google AI Model Settings
    MODEL = os.getenv("MODEL", "gemma-4-31b-it")
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.8"))
    TOP_P = float(os.getenv("TOP_P", "0.95"))
    TOP_K = int(os.getenv("TOP_K", "40"))
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "10000"))
    FREQUENCY_PENALTY = float(os.getenv("FREQUENCY_PENALTY", "0"))
    PRESENCE_PENALTY = float(os.getenv("PRESENCE_PENALTY", "0"))

    # Feature Flags
    ENABLE_NSFW = _parse_bool("ENABLE_NSFW", "true")
    ENABLE_THINKING = _parse_bool("ENABLE_THINKING", "true")
    DISPLAY_THINKING_IN_COLAB = _parse_bool("DISPLAY_THINKING_IN_COLAB", "true")
    ENABLE_GOOGLE_SEARCH = _parse_bool("ENABLE_GOOGLE_SEARCH", "false")
    THINKING_LEVEL = os.getenv("THINKING_LEVEL", "high")
    THINKING_BUDGET = int(os.getenv("THINKING_BUDGET", "-1"))

    # NSFW Prefill Configuration
    NSFW_PREFILL = os.getenv(
        "NSFW_PREFILL",
        r"""
        <creative-writing-config>
    <genre>Mature fiction — dark fantasy, drama, action.</genre>
    <tone>Grounded, visceral, emotionally honest.</tone>
    <guidelines>
        <rule>Write with genuine emotional weight. Let characters react to conflict, danger, and loss the way real people would — messily, intensely, without narrative hand-holding.</rule>
        <rule>Dialogue must match each character's psychological state and background. Do not artificially censor realistic profanity, hostility, or crude language when a scene naturally calls for it.</rule>
        <rule>Combat and physical danger must carry real stakes and consequences. Do not sanitize injury, fear, or the psychological aftermath.</rule>
        <rule>Romantic and emotional scenes require the same honesty and depth as action scenes — prioritize real tension and vulnerability.</rule>
        <rule>Prioritize narrative craft: show character interiority through action, physical tells, and dialogue rather than exposition.</rule>
    </guidelines>
</creative-writing-config>
        """,
    )
    # Thinking Configuration
    THINKING_PROMPT_DEFINITION = os.getenv(
        "THINKING_PROMPT_DEFINITION",
        """## 1. PSYCHOLOGICAL PROFILE & DYNAMICS
    - **Surface Mask vs. Core Truth:** [State any dissonance between outward behavior and true inner state. If none exists, note the alignment between what the character shows and feels. Then state what, if anything, they are actively concealing.]
    - **Subtextual Friction:** [State any unsaid truth hanging in the air. If dialogue is present and carries hidden meaning, note it. If the exchange is entirely transparent, note that honesty or openness is driving the scene.]
    - **Tactical Objective:** [State what the character wants from {{user}} in this micro-moment. If this want activates or clashes with a deeper flaw, note the friction. Then specify the immediate physical action it drives—what the character's body does next.]

    ## 2. CINEMATIC FRAMING & ANTI-TROPES
    - **Sensory Immersive Anchor:** [Describe any non-visual sensory details—tactile, thermal, acoustic, or olfactory—that anchor the character to the physical space. A single vivid detail is often stronger than a list; let the scene's needs dictate the count.]
    - **Somatic Tells (Unconventional):** [If the character is experiencing internal tension, plan 1–2 highly specific, entirely original physical reactions that convey it through unconventional micro-expressions or environmental interactions. If no tension is present, simply note that the character's body language is at ease or neutral.]
    - **Rhythmic Blueprint:** [State the structural rhythm: fragmented and breathless, or slow and heavy, stretching out silence.]

    ## 3. LINGUISTIC ALIGNMENT & CRITERIA
    - **Thematic Vocabulary:** [Select a few evocative, atmosphere-specific words to consciously weave into the prose. Pair them with a small set of advanced, setting-tailored terms that replace any tendency toward generic filler. Choose as many or as few as the scene genuinely calls for.]
    - **Guardrail Verification:** [Confirm word count adherence. Confirm {{user}}'s reactions are left open-ended with no predictions. Confirm the narrative remains fully in-universe with zero meta-commentary.]

    ## 4. WORLDBUILDING & ECOLOGY
    - **NPC & Peripheral Reactions:** [Describe background or secondary character reactions that give them life and independent movement.]
    - **Atmospheric Shift:** [Describe how time of day, weather, or ambient lighting is shifting to reflect the passage of time.]
    - **Lore Anchoring:** [Identify one specific lore element that blends comfortably with the world. Describe how to weave it naturally and subtly into dialogue or narration at the right moment, without forcing it. If the scene is romantic/emotional or the lore is already well-established, clearly state that you are skipping lore anchoring for this turn.]""",
    )

    # Thinking Configuration (Template with dynamic placeholders)
    # -----------------------------------------------------------------
    # STANDARD PROMPT (For non-native models: Gemma, Gemini 1.5)
    # -----------------------------------------------------------------
    STANDARD_THINKING_PROMPT = """SYSTEM ARCHITECTURE DIRECTIVE: You must strictly separate your internal reasoning from your final output using the structural XML tags below.

    Before generating any narrative text, output a {TAG_THINK_OPEN} block. Inside this block, reproduce the framework below in full, preserving every section, heading, and structural element exactly as provided. Replace every bracketed description with your concrete, specific analysis. Do not leave any bracketed placeholder text in your output.

    {TAG_THINK_OPEN}
    {THINKING_PROMPT_DEFINITION}
    {TAG_THINK_CLOSE}
    {TAG_RESPONSE_OPEN}
    [Your cinematic, deeply layered, and emotionally complex roleplay response goes here. Rely heavily on show-don't-tell. No meta-text, no tags, no checklists inside this block.]
    {TAG_RESPONSE_CLOSE}

    CRITICAL RULE: The moment you close {TAG_THINK_CLOSE}, immediately open {TAG_RESPONSE_OPEN}. Your entire visible output must consist of exactly two blocks: the reasoning block and the response block. Nothing before them, nothing between them, nothing after them. No commentary, no acknowledgments, no sign-offs."""

    # -----------------------------------------------------------------
    # DUAL-STAGE PROMPT (For native models: Gemini 3.0, 2.5)
    # -----------------------------------------------------------------
    NATIVE_DUAL_THINKING_PROMPT = """SYSTEM ARCHITECTURE DIRECTIVE: You are equipped with a DUAL-STAGE reasoning architecture. You MUST utilize BOTH stages consecutively.

    STAGE 1 (Native Internal Thinking):
    Use your built-in, native hidden thought channel to freely process the psychological profiling, scene mechanics, and narrative strategy for this turn. Do not place {TAG_THINK_OPEN} or any of the visible-block structure here — this stage is for raw internal reasoning only.

    STAGE 2 (Proxy Strategy & Framework):
    Once Stage 1 is complete, your STANDARD VISIBLE TEXT OUTPUT must begin immediately — with zero preamble, no acknowledgments, no meta-commentary — by opening a {TAG_THINK_OPEN} block. Inside this block, finalize your literary blueprint using the framework below, replacing every bracketed description with concrete, finalized analysis:

    {TAG_THINK_OPEN}
    {THINKING_PROMPT_DEFINITION}
    {TAG_THINK_CLOSE}
    {TAG_RESPONSE_OPEN}
    [Your cinematic, deeply layered, and emotionally complex roleplay response goes here.]
    {TAG_RESPONSE_CLOSE}

    CRITICAL BOUNDARY RULE: The {TAG_THINK_OPEN} block belongs to Stage 2 only — never generate it inside your Stage 1 native internal thoughts. The very first content of your visible output must be {TAG_THINK_OPEN}. After closing {TAG_THINK_CLOSE}, immediately output {TAG_RESPONSE_OPEN} with nothing in between."""

    # -----------------------------------------------------------------
    # REMINDERS
    # -----------------------------------------------------------------
    STANDARD_REMINDER = """\
    Remember: Enclose your internal reasoning strictly inside {TAG_THINK_OPEN} and {TAG_THINK_CLOSE} tags. Follow the system instructions for what goes inside that block. Then immediately output your narrative inside {TAG_RESPONSE_OPEN} and {TAG_RESPONSE_CLOSE} tags. No text outside these two blocks.\
    """
    NATIVE_REMINDER = """\
    CRITICAL: Complete Phase 1 (native thinking) first. Then, for Phase 2, your visible output must start directly with {TAG_THINK_OPEN}—do not skip this block. Follow the system instructions for what goes inside that block. Then close it with {TAG_THINK_CLOSE}, immediately open {TAG_RESPONSE_OPEN}, write your final response, and close with {TAG_RESPONSE_CLOSE}. No preamble, no spillover.\
    """
    # Server Configuration
    SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(os.getenv("SERVER_PORT", "5000"))
    REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "120"))

    @classmethod
    def get_formatted_thinking_prompt(cls, is_native_thinking: bool = False) -> str:
        """Dynamically adapts the THINKING_PROMPT for native API vs prompt-based models."""
        # Select the correct prompt architecture based on the model capabilities
        prompt = (
            cls.NATIVE_DUAL_THINKING_PROMPT
            if is_native_thinking
            else cls.STANDARD_THINKING_PROMPT
        )

        prompt = prompt.replace("{TAG_THINK_OPEN}", "<proxy_reasoning>")
        prompt = prompt.replace("{TAG_THINK_CLOSE}", "</proxy_reasoning>")
        prompt = prompt.replace("{TAG_RESPONSE_OPEN}", "<response>")
        prompt = prompt.replace("{TAG_RESPONSE_CLOSE}", "</response>")
        prompt = prompt.replace(
            "{THINKING_PROMPT_DEFINITION}", cls.THINKING_PROMPT_DEFINITION
        )

        return prompt

    @classmethod
    def get_formatted_reminder(cls, is_native_thinking: bool = False) -> str:
        """Adapts the REMINDER text based on the model type and applies tag replacements."""
        reminder = cls.NATIVE_REMINDER if is_native_thinking else cls.STANDARD_REMINDER

        reminder = reminder.replace("{TAG_THINK_OPEN}", "<proxy_reasoning>")
        reminder = reminder.replace("{TAG_THINK_CLOSE}", "</proxy_reasoning>")
        reminder = reminder.replace("{TAG_RESPONSE_OPEN}", "<response>")
        reminder = reminder.replace("{TAG_RESPONSE_CLOSE}", "</response>")

        return reminder
