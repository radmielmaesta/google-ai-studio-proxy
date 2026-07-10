# Google AI Studio Proxy for Janitor AI

A lightweight, cross-platform proxy designed to connect Google AI Studio models (like Gemini and Gemma) directly to Janitor AI. This tool handles necessary formatting, manages safety filters, and routes the AI's internal "thinking" processes cleanly.

## Prerequisites
* **Google Studio API Key:** Required to access the models.
* **Python:** * **Windows:** Python 3.12 recommended.
  * **Linux / Mac:** Recent Python 3 distributions (3.10+).

---

## 1. Installation

### Step 1: Get the Repository

**Method A: Download as ZIP (For Beginners)**
1. Visit the repository: https://github.com/radmielmaesta/google-ai-studio-proxy
2. Click the green **Code** button and select **Download ZIP**.
3. Extract the ZIP file to a dedicated folder on your computer.
4. Open your terminal/command prompt and navigate to that folder:
   `cd path/to/extracted/folder`

**Method B: Clone with Git (For Advanced Users)**
1. Open your terminal or command prompt.
2. Run the following commands:
   `git clone https://github.com/radmielmaesta/google-ai-studio-proxy.git`
   `cd google-ai-studio-proxy`

### Step 2: Create a Virtual Environment
A virtual environment keeps the required packages isolated from your system.

**Windows (PowerShell or CMD):**
`python -m venv venv`
`.\venv\Scripts\activate`

**Linux / Mac (Bash/Zsh):**
`python3 -m venv venv`
`source venv/bin/activate`

*(Note: You will know it worked when you see `(venv)` appear at the beginning of your command line prompt.)*

### Step 3: Install Dependencies
With the virtual environment active, install the required packages.

**Windows:**
`pip install -r requirements.txt`

**Linux / Mac:**
`pip3 install -r requirements.txt`

---

## 2. Quickstart Guide

The proxy is pre-configured and ready to run immediately.

1. **Start the Proxy:**
   * Windows: `python main.py`
   * Linux/Mac: `python3 main.py`
2. **Locate the Cloudflare URL:**
   * Watch your terminal output. 
   * The program will automatically generate a Cloudflare tunnel link (e.g., `https://random-words.trycloudflare.com`).
   * Copy this URL.

---

## 3. Connecting to Janitor AI

1. Open **Janitor AI** and navigate to your API settings.
2. Select **OpenAI** as the API type.
3. **OpenAI URL:** Paste the Cloudflare URL generated in your terminal.
   * *CRITICAL:* Do **NOT** add `/chat/completions` or `/v1/chat/completions` to the end of the URL. Use the base link exactly as copied.
4. **API Key:** Paste your Google Studio API Key.
5. **Model:** Enter your desired model name (e.g., `gemma-4-31b-it`).
6. Save your settings. 

---

## Advanced Configuration (config.py)

If you wish to modify the default behavior, open the `core/config.py` file in any text editor. The variables are loaded automatically upon saving.

### Primary Settings
* `MODEL`: Set your default model here (currently defaults to `gemma-4-31b-it`).
* `GOOGLE_API_KEY`: Can be hardcoded here to avoid pasting it into Janitor AI.

### Feature Flags (Booleans: True or False)

* `ENABLE_NSFW` (Default: True)
  * Applies prompt injections to bypass strict content filters.
  * *Troubleshooting:* If Google continuously halts generation and you see PROHIBITED warnings in your terminal, toggle this to False to restore basic chatting functionality.
  
* `ENABLE_THINKING` (Default: True)
  * Allows models to utilize internal reasoning before responding.
  * *Warning:* Disabling this setting may result in empty or broken outputs depending on the model's architecture. It is highly recommended to leave this enabled.

* `DISPLAY_THINKING_IN_COLAB` (Default: True)
  * Determines if the AI's internal thought process is printed to your terminal.
  * Toggle this to False if you want to stop displaying the reasoning logs in your command line.