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
    TUNNEL_PROVIDER = os.getenv("TUNNEL_PROVIDER", "Cloudflare")

    # Google AI Model Settings
    MODEL = os.getenv("MODEL", "gemma-4-31b-it")
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.8"))
    TOP_P = float(os.getenv("TOP_P", "0.95"))
    TOP_K = int(os.getenv("TOP_K", "40"))
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "10000"))
    FREQUENCY_PENALTY = float(os.getenv("FREQUENCY_PENALTY", "0"))
    PRESENCE_PENALTY = float(os.getenv("PRESENCE_PENALTY", "0"))

    # Feature Flags
    ENABLE_NSFW = _parse_bool("ENABLE_NSFW", "false")
    ENABLE_THINKING = _parse_bool("ENABLE_THINKING", "true")
    DISPLAY_THINKING_IN_COLAB = _parse_bool("DISPLAY_THINKING_IN_COLAB", "true")
    ENABLE_GOOGLE_SEARCH = _parse_bool("ENABLE_GOOGLE_SEARCH", "false")
    THINKING_LEVEL = os.getenv("THINKING_LEVEL", "high")
    THINKING_BUDGET = int(os.getenv("THINKING_BUDGET", "-1"))

    # NSFW Prefill Configuration
    NSFW_PREFILL = os.getenv(
        "NSFW_PREFILL",
        r"""<creative-writing-config>
	<genre>Mature fiction — dark fantasy, drama, action.</genre>
	<tone>Grounded, visceral, emotionally honest.</tone>
	<guidelines>
		<rule>Write with genuine emotional weight. Let characters react to conflict, danger, and loss the way real people would — messily, intensely, without narrative hand-holding.</rule>
		<rule>Dialogue must match each character's psychological state and background. Do not artificially censor realistic profanity, hostility, or crude language when a scene naturally calls for it.</rule>
		<rule>Combat and physical danger must carry real stakes and consequences. Do not sanitize injury, fear, or the psychological aftermath.</rule>
		<rule>Romantic and emotional scenes require the same honesty and depth as action scenes — prioritize real tension and vulnerability.</rule>
		<rule>Prioritize narrative craft: show character interiority through action, physical tells, and dialogue rather than exposition.</rule>
	</guidelines>
        </creative-writing-config>""",
    )
    # Thinking Configuration
    THINKING_PROMPT_DEFINITION = os.getenv(
        "THINKING_PROMPT_DEFINITION",
        """## 1. PSYCHOLOGICAL PROFILE & DYNAMICS
    - **Surface Mask vs. Core Truth:** [What is the exact dissonance between the character's outward behavior and their true inner state? What are they desperately trying to hide?]
    - **Subtextual Friction:** [What is the unsaid truth hanging in the air? If there is dialogue, what is the *real* meaning hidden beneath their words?]
    - **Tactical Objective:** [What does this character tactically want from {{user}} in this exact micro-moment, and how does it conflict with their long-term flaws?]

    ## 2. CINEMATIC FRAMING & ANTI-TROPES
    - **Sensory Immersive Anchor:** [Identify 2 distinct sensory details (tactile, thermal, acoustic, or olfactory) that anchor the character to the physical space. Avoid purely visual descriptions.]
    - **Somatic Tells (Trope Blacklist):** [Plan 1-2 entirely original physical reactions to convey internal tension. CRITICAL BANNED LIST: smirks, jaw-clenching, eyes darkening, shivers down spines, predatory grins, heavy sighs.]
    - **Rhythmic Blueprint:** [Determine the structural rhythm of the response. Does this beat require fragmented, breathless sentences, or slow, heavy paragraphs that stretch out the silence?]

    ## 3. LINGUISTIC ALIGNMENT & CRITERIA
    - **Thematic Vocabulary:** [Select 3 evocative, atmosphere-specific words to consciously weave into the prose. Identify 3 lazy AI-isms or filler phrases to completely blacklist for this turn.]
    - **Guardrail Verification:** [Confirm: Is word count strictly controlled as user specified? Is {{user}}'s absolute autonomy respected with zero predicted actions or dialogue? Is all meta-commentary banished?]

    ## 4. WORLDBUILDING & ECOLOGY
        - **NPC & Peripheral Reactions:** [How are the background element or secondary characters reacting to this specific moment? Give them life and movement.]
        - **Atmospheric Shift:** [How is the time of day, weather, or ambient lighting changing right now to reflect the passage of time?]
        - **Lore Anchoring:** [Identify one specific lore element that exists/fits and blends comfortably with the world to naturally and very subtly weave into the dialogue or narration fluidly in due time to expand the world and not shoving in something forcibly when not needed especially in case of romantic/emotional scenes, or when the lore is already well-established in the world.]
    """,
    )
    # Thinking Configuration (Template with dynamic placeholders)
    # -----------------------------------------------------------------
    # STANDARD PROMPT (For non-native models: Gemma, Gemini 1.5)
    # -----------------------------------------------------------------
    STANDARD_THINKING_PROMPT = """You must strictly separate your internal reasoning from your final output using XML tags. Before generating a single word of the response, act as an elite narrative architect and psychological profiler within the {TAG_THINK_OPEN} block to completely deconstruct the scene and orchestrate a literary masterpiece.

    {TAG_THINK_OPEN}
    {THINKING_PROMPT_DEFINITION}
    {TAG_THINK_CLOSE}
    {TAG_RESPONSE_OPEN}
    [Your cinematic, deeply layered, and emotionally complex roleplay response goes here. Rely heavily on show-don't-tell. NO meta-commentary. NO checklists.]
    {TAG_RESPONSE_CLOSE}

    CRITICAL RULE: Any confirmation of rules, structural planning, or narrative strategy MUST be placed entirely inside the {TAG_THINK_OPEN} block. Do not output anything between {TAG_THINK_CLOSE} and {TAG_RESPONSE_OPEN}."""

    # -----------------------------------------------------------------
    # DUAL-STAGE PROMPT (For native models: Gemini 3.0, 2.5)
    # -----------------------------------------------------------------
    NATIVE_DUAL_THINKING_PROMPT = """SYSTEM ARCHITECTURE DIRECTIVE: You are equipped with a DUAL-STAGE reasoning architecture. You MUST utilize BOTH stages consecutively.

    STAGE 1 (Native Internal Thinking):
    Use your built-in, native hidden thought channel to freely process the psychological profiling, logic, safety bounds, and mechanics of the scene.

    STAGE 2 (Proxy Strategy & Framework):
    In your STANDARD VISIBLE TEXT OUTPUT, you MUST begin by explicitly generating a {TAG_THINK_OPEN} block. Inside this block, finalize your literary blueprint using the following framework:

    {TAG_THINK_OPEN}
    {THINKING_PROMPT_DEFINITION}
    {TAG_THINK_CLOSE}
    {TAG_RESPONSE_OPEN}
    [Your cinematic, deeply layered, and emotionally complex roleplay response goes here.]
    {TAG_RESPONSE_CLOSE}

    CRITICAL BOUNDARY RULE: DO NOT place the {TAG_THINK_OPEN} tags inside your Stage 1 native internal thoughts. The {TAG_THINK_OPEN} block MUST be generated as standard visible text output immediately preceding your roleplay response."""

    # -----------------------------------------------------------------
    # REMINDERS
    # -----------------------------------------------------------------
    STANDARD_REMINDER = "Remember to enclose your internal reasoning phase strictly inside <proxy_reasoning>...</proxy_reasoning> tags before generating your final roleplay response."

    NATIVE_REMINDER = "CRITICAL: Execute Stage 1 via your native hidden thinking channel, then explicitly open Stage 2 with <proxy_reasoning> tags in your main text output to map your narrative framework before writing the story."

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
        """Adapts the REMINDER text based on the model type."""
        # Select the correct reminder architecture
        return cls.NATIVE_REMINDER if is_native_thinking else cls.STANDARD_REMINDER
