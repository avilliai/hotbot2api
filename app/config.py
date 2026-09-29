"""
HotBot configuration settings
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Tokens and accounts file
TOKENS_FILE = Path("./hotbot_tokens.json")
ACTIVE_POOL_FILE = Path("./active_pool.json")

ACTIVE_POOL_SIZE = int(os.environ.get("ACTIVE_POOL_SIZE", "5"))

HOTBOT_BASE_URL = "https://www.hotbot.com"
HOTBOT_API_URL = "https://www.hotbot.com/api"

HTTP_PROXY = os.getenv("HTTP_PROXY", os.getenv("PROXY", "http://127.0.0.1:10809"))
HTTPS_PROXY = os.getenv("HTTPS_PROXY", os.getenv("PROXY", "http://127.0.0.1:10809"))
PROXY_API_KEY = os.getenv("PROXY_API_KEY", "endlesswork")
PORT = int(os.getenv("PORT", "8077"))

COMMON_HEADERS = {
    "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}
