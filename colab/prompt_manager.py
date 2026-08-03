import json
import os
import sys
import time

import ipywidgets as widgets
import requests
from IPython.display import HTML, display

from core.config import Config

# --- Constants ---
REPO_PATH = "/content/google-ai-studio-proxy"
CLIENT_ID = "Ov23lioFdp07HTGBYuuD"
GIST_DESCRIPTION = "proxy-prompts"
GIST_FILENAME = "prompts.json"
CACHE_PATH = os.path.join(REPO_PATH, "prompts.json")


def check_environment():
    if not os.path.isdir(REPO_PATH):
        print("""\033[1;31m
══════════════════════════════════════════════════════════════

          ⚠️  SETUP REQUIRED\033[0m

Please run: ▶ Cell 1 – Setup Proxy Environment

before running this cell.

\033[1;31m══════════════════════════════════════════════════════════════
\033[0m""")
        sys.exit()


# --- Cache ---
def _read_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(data):
    try:
        with open(CACHE_PATH, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


# --- Gist API ---
def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _find_gist_id(token):
    r = requests.get(
        "https://api.github.com/gists",
        headers=_headers(token),
        params={"per_page": 100},
    )
    if r.status_code != 200:
        return None
    for g in r.json():
        if g.get("description") == GIST_DESCRIPTION:
            return g["id"]
    return None


def _read_gist(token):
    gid = _find_gist_id(token)
    if not gid:
        return None
    r = requests.get(f"https://api.github.com/gists/{gid}", headers=_headers(token))
    if r.status_code != 200:
        return None
    try:
        content = r.json()["files"][GIST_FILENAME]["content"]
        data = json.loads(content)
        _write_cache(data)
        return data
    except Exception:
        return None


def write_gist(token, data):
    payload = {
        "description": GIST_DESCRIPTION,
        "public": False,
        "files": {GIST_FILENAME: {"content": json.dumps(data, indent=2)}},
    }
    gid = _find_gist_id(token)
    if gid:
        requests.patch(
            f"https://api.github.com/gists/{gid}", headers=_headers(token), json=payload
        )
    else:
        requests.post(
            "https://api.github.com/gists", headers=_headers(token), json=payload
        )
    _write_cache(data)


def load_prompts(token):
    cached = _read_cache()
    if cached:
        return cached
    from_gist = _read_gist(token)
    if from_gist:
        return from_gist
    return {"nsfw_prefill": "", "thinking_prompt": ""}


# --- OAuth Flow ---
def start_auth_flow():
    print("One-time GitHub login — your prompts will be saved to a private Gist.\n")

    r = requests.post(
        "https://github.com/login/device/code",
        data={"client_id": CLIENT_ID, "scope": "gist"},
        headers={"Accept": "application/json"},
    )
    codes = r.json()

    _show_code_card(codes["user_code"], codes["verification_uri"])

    expires_min = codes.get("expires_in", 900) // 60
    print(f"Waiting for you to authorize… (code expires in {expires_min} min)\n")

    new_token = _poll_for_token(codes["device_code"], codes.get("interval", 5))

    if new_token:
        _show_token_card(new_token)
    else:
        print("❌ Code expired. Rerun this cell to try again.")


def _poll_for_token(device_code, interval):
    from urllib.parse import parse_qs

    while True:
        time.sleep(interval)
        r = requests.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
        )

        if not r.text.strip():
            continue

        try:
            resp = r.json()
        except Exception:
            parsed = parse_qs(r.text)
            resp = {k: v[0] for k, v in parsed.items()}

        if "access_token" in resp:
            return resp["access_token"]

        error = resp.get("error", "")
        if error == "slow_down":
            interval += 5
        elif error == "expired_token":
            return None


# --- UI Elements & Rendering ---
def _inject_css():
    display(
        HTML("""<style>
.prompt-tabs.jupyter-widgets.widget-tab > .p-TabBar .p-TabBar-tab {
    background: #474747; color: rgba(255,255,255,0.75);
    padding: 10px 20px; margin-right: 2px; font-family: monospace; font-size: 13px; width: 4rem;
}
.prompt-tabs.jupyter-widgets.widget-tab > .p-TabBar .p-TabBar-tab.p-mod-current {
    background: #fff; color: #000;
}
.prompt-tabs.jupyter-widgets.widget-tab > .p-TabBar .p-TabBar-tabLabel {
    flex: 0 0 auto;
    overflow: visible;
    white-space: normal;
}
.prompt-textarea textarea {
    background: #1e1e1e !important; color: #e0e0e0 !important;
    border: 1px solid #444 !important; border-radius: 0 6px 6px 6px !important;
    font-family: monospace; font-size: 13px; padding: 10px;
}
</style>""")
    )


def _show_code_card(user_code, url):
    display(
        HTML(f"""
<div style="font-family:monospace;font-size:13px;padding:16px;background:#1e1e1e;
            border-radius:8px;color:#e0e0e0;max-width:520px;margin:8px 0">
  <div style="margin-bottom:14px">
    <span style="color:#888">① Open in your browser</span><br>
    <a href="{url}" target="_blank" style="color:#58a6ff;font-size:14px">{url}</a>
  </div>
  <div style="display:flex;align-items:center;gap:10px">
    <span style="color:#888">② Enter this code</span>
    <span style="font-size:20px;font-weight:bold;letter-spacing:3px;background:#2d2d2d;
                 padding:6px 14px;border-radius:6px;border:1px solid #555;color:#fff">{user_code}</span>
    <button onclick="navigator.clipboard.writeText('{user_code}')
                       .then(()=>this.textContent='Copied!')
                       .catch(()=>this.textContent='See above')"
            style="background:#1f6feb;color:#fff;border:none;padding:6px 14px;
                   border-radius:6px;cursor:pointer;font-size:12px">Copy</button>
  </div>
</div>""")
    )


def _show_token_card(new_token):
    display(
        HTML(f"""
<div style="font-family:monospace;font-size:13px;padding:16px;background:#1e1e1e;
            border-radius:8px;color:#e0e0e0;max-width:600px;margin:8px 0">
  <div style="color:#3fb950;font-weight:bold;margin-bottom:12px">✅  Authorized!</div>
  <div style="color:#888;margin-bottom:8px">Your token — copy it before closing this cell:</div>
  <div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:16px">
    <span style="background:#2d2d2d;padding:8px 10px;border-radius:6px;border:1px solid #555;
                 word-break:break-all;color:#e0e0e0;flex:1;font-size:12px">{new_token}</span>
    <button onclick="navigator.clipboard.writeText('{new_token}')
                       .then(()=>this.textContent='Copied!')
                       .catch(()=>this.textContent='Select manually')"
            style="background:#238636;color:#fff;border:none;padding:8px 16px;
                   border-radius:6px;cursor:pointer;font-size:12px;white-space:nowrap">Copy</button>
  </div>
  <div style="color:#ccc;line-height:2">
    <div style="color:#e0e0e0;font-weight:bold;margin-bottom:4px">Save it as a Colab secret (one-time):</div>
    <div>① Click the <b>🔑 key icon</b> in the left sidebar</div>
    <div>② Click <b>+ Add new secret</b></div>
    <div>③ Name: &nbsp;<span style="background:#2d2d2d;padding:2px 8px;border-radius:4px">DATA_TOKEN</span></div>
    <div>④ Value: paste the token above</div>
    <div>⑤ Enable the toggle next to this notebook</div>
    <div>⑥ <b>Rerun this cell</b></div>
  </div>
</div>""")
    )


def render_editor(token):
    _inject_css()
    saved = load_prompts(token)

    nsfw_box = widgets.Textarea(
        value=saved.get("nsfw_prefill") or Config.NSFW_PREFILL.strip(),
        layout=widgets.Layout(width="100%", height="300px"),
    )
    nsfw_box.add_class("prompt-textarea")

    thinking_box = widgets.Textarea(
        value=saved.get("thinking_prompt") or Config.THINKING_PROMPT_DEFINITION.strip(),
        layout=widgets.Layout(width="100%", height="300px"),
    )
    thinking_box.add_class("prompt-textarea")

    tabs = widgets.Tab(children=[nsfw_box, thinking_box])
    tabs.set_title(0, "Realism Prompt")
    tabs.set_title(1, "Thinking Prompt")
    tabs.add_class("prompt-tabs")

    save_btn = widgets.Button(description="Save", button_style="success")
    status = widgets.Output()

    def on_save(_):
        data = {
            "nsfw_prefill": nsfw_box.value.strip(),
            "thinking_prompt": thinking_box.value.strip(),
        }
        write_gist(token, data)

        # Inject the overrides back into the Colab notebook's main namespace safely
        import __main__

        __main__.NSFW_PREFILL_OVERRIDE = data["nsfw_prefill"]
        __main__.THINKING_PROMPT_OVERRIDE = data["thinking_prompt"]

        with status:
            status.clear_output()
            print("✅ Saved to GitHub Gist and cached locally.")

    save_btn.on_click(on_save)
    display(tabs, save_btn, status)
