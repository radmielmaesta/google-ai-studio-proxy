Proposed Folder Structure

google-ai-proxy/
├── routers/
│   ├── __init__.py
│   └── proxy_router.py
├── services/
│   ├── __init__.py
│   ├── google_ai_service.py
│   └── message_transform_service.py
├── utils/
│   ├── __init__.py
│   ├── response_utils.py
│   └── streaming_utils.py
├── config.py
└── main.py

my_ai_proxy/
├── main.py                 # The entry point (starts the server)
├── core/                   
│   └── config.py           # Environment variables and API keys
├── api/                    
│   └── routes.py           # The @app.route endpoints
├── services/               
│   └── llm_streamer.py     # The connection retry loops and API calls
├── utils/                  
│   └── text_parser.py      # The <think> tag extraction logic
└── models/                 
    └── schemas.py          # Data validation for the incoming JanitorAI payload

How to prompt the Agent for success
If you are going to use an agent to build this out, do not ask it to do the whole thing in one single prompt. That is how you get truncated code and broken imports. Break it down like a project manager:

Prompt 1 (The Blueprint): "Here is my monolithic Python script. I want to refactor this into a 3-tier architecture (Routers, Services, Utils). Do not write the code yet. Just give me the proposed folder structure and tell me exactly which functions from the monolith will go into which file."

Prompt 2 (The Config): "Great. Now write the core/config.py file to handle all the global variables and settings."

Prompt 3 (The Utils): "Now write utils/text_parser.py using the parser class from the monolith."

Prompt 4 (The Services): "Now write services/llm_streamer.py. Make sure you import the config and the text parser correctly."

Prompt 5 (The Router): "Finally, write api/routes.py and main.py to tie it all together."

By forcing the agent to do it sequentially, you are practicing actual AI orchestration. You provide the architectural guardrails, and the agent acts as a junior developer doing the manual copy-pasting and formatting.


Prompt 1: The Reset & The Parser
"I am refactoring the attached Python proxy script into a lean 3-tier architecture.
We already have core/config.py completed.

Write the code for utils/text_parser.py.

Extract the StreamingParser class and the extract_thinking_and_response function from the original script and put them here.

Do not change the lenient parsing logic. Keep it exactly as it is.

Output only the complete Python code for this file."

Prompt 2: The Core Engine
"Now write the code for services/llm_streamer.py.

Extract the transform_janitor_to_google_ai, create_janitor_chunk, create_error_response, and create_error_stream_chunk functions here.

Extract the core API call logic (the generate_stream function and the non-streaming logic) into a single function called process_llm_request(json_data, is_streaming).

Import the StreamingParser from utils.text_parser.

Import Config from core.config.

Output only the complete Python code for this file."

Prompt 3: The Traffic Cop
"Now write api/routes.py.

Set up a Blueprint or standard Flask routes for / and /v1/chat/completions.

This file should ONLY handle the HTTP request headers, extract the API key, and pass the JSON payload to the process_llm_request function we just made in the services file.

Import process_llm_request from services.llm_streamer.

Include the /health check endpoint here.

Output only the complete Python code for this file."

Prompt 4: The Start Button
"Finally, write main.py.

Initialize the Flask app and CORS.

Import and register the routes from api.routes.

Include the Cloudflare/Localtunnel setup logic at the bottom so it runs exactly like the original Colab script.

Output only the complete Python code for this file."
