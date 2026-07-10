🤖 Google AI to JanitorAI Proxy
This is a lightweight bridge that allows you to use Google's powerful Gemini AI models (like Gemini 3.5 Flash and Gemini 1.5 Pro) completely free in JanitorAI.

It features built-in formatting for roleplay, bypasses for creative/unfiltered narratives, and support for Gemini's "Thinking" process to make the AI smarter.

🛠️ What You Need Before Starting
A Google AI Studio API Key: Get one for free at Google AI Studio.

Python: You need Python installed on your computer.

🚀 Step 1: Install Python (Crucial Step)
For Windows Users:

Download Python from python.org.

Open the installer.

⚠️ STOP! DO NOT CLICK NEXT YET! At the very bottom of the first window, check the box that says "Add Python.exe to PATH". (If you skip this, nothing will work).

Click "Install Now".

For Mac Users:
Open your "Terminal" app and type python3 --version. If it asks you to install developer tools, say yes. Otherwise, download the Mac installer from python.org.

📥 Step 2: Download and Setup
Download this code: Click the green Code button at the top of this GitHub page and select Download ZIP. Extract the folder to your Desktop.

Open your Terminal (or Command Prompt):

Windows: Press the Windows Key, type cmd, and press Enter.

Mac/Linux: Open the Terminal app.

Navigate to the folder: Type cd followed by a space, then drag and drop the extracted folder from your desktop into the terminal window and press Enter.
(It should look something like: cd C:\Users\Name\Desktop\google-ai-proxy)

Install the requirements: Type the following command and press Enter to install the necessary background files:

Bash
pip install -r requirements.txt
(Mac/Linux users: If that fails, try pip3 install -r requirements.txt)

⚙️ Step 3: Configuration
You can customize how the bot acts by editing the config file.

Open the core folder and find the config.py file.

Right-click it and open it with Notepad (Windows) or TextEdit (Mac).

Here you can change settings like:

MODEL = "gemini-3.5-flash" (Change which AI model you want to use).

ENABLE_NSFW = True (Keeps the creative writing filters lenient).

ENABLE_THINKING = True (Allows the AI to reason before speaking).

Save the file and close it.

▶️ Step 4: Run the Proxy
In your terminal (make sure you are still in the proxy folder), type:

Bash
python main.py
(Mac/Linux users: Try python3 main.py)

You will see the server boot up. Because this proxy has built-in Cloudflare tunneling, you do not need to mess with router settings.

Look at your terminal screen. After a few seconds, it will print a link that looks like this:

[https://random-words-here.trycloudflare.com](https://random-words-here.trycloudflare.com)

Copy that entire link. Leave this terminal window open and running in the background while you roleplay!

🔗 Step 5: Connect to JanitorAI
Open JanitorAI and go to any character chat.

Click the API Settings button (the little plug/hamburger menu at the top right).

Select OpenAI as your API type.

OpenAI URL: Paste your Cloudflare link here (e.g., [https://random-words-here.trycloudflare.com/v1/chat/completions](https://random-words-here.trycloudflare.com/v1/chat/completions)). Note: JanitorAI usually adds /v1/chat/completions automatically, but if it doesn't, add it yourself.

OpenAI Key: Paste your Google AI Studio API Key here.

Click Check Proxy. If it says valid, click Save Settings.

You are ready to chat!
