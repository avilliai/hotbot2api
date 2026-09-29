"""
HotBot client for registration and chat streaming
"""
import asyncio
import json
import logging
import random
import re
import uuid
from typing import AsyncIterator, Optional, List, Dict, Any
from urllib.parse import urlparse, parse_qs

from curl_cffi.requests import AsyncSession

from app.config import HOTBOT_BASE_URL, HOTBOT_API_URL, HTTP_PROXY, COMMON_HEADERS
from app.email_service import EmailService
from app.models import AccountState

log = logging.getLogger("hotbot_proxy.client")
IMPERSONATE = "chrome120"

class EmptyResponseError(RuntimeError):
    pass

class ServerError(RuntimeError):
    pass

def generate_random_ip() -> str:
    """Generate a random public IPv4 (prefer US Cloudflare range 104.28.x.x for best latency/bypass)"""
    return f"104.28.{random.randint(1, 250)}.{random.randint(1, 250)}"

def messages_to_hotbot(messages: list[dict]) -> tuple[list[dict], Optional[str]]:
    """
    Format standard OpenAI messages to HotBot messages list.
    Extract system message if present to place in prompt or first user instruction.
    """
    system_prompt = None
    hotbot_messages = []
    
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content") or ""
        if not content and "tool_calls" in msg:
            continue
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            content = "\n".join(parts)
            
        if role == "system":
            system_prompt = content
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            hotbot_messages.append({
                "role": "user",
                "content": f"[Tool Result for {tool_call_id}]: {content}"
            })
        else:
            hotbot_messages.append({
                "role": role,
                "content": content
            })

    if not hotbot_messages and system_prompt:
        hotbot_messages.append({"role": "user", "content": system_prompt})
    elif system_prompt and hotbot_messages:
        # Prepend system instruction to the first user message
        first = hotbot_messages[0]
        if first.get("role") == "user":
            first["content"] = f"[System Context: {system_prompt}]\n\n{first['content']}"
        else:
            hotbot_messages.insert(0, {"role": "user", "content": f"[System Context: {system_prompt}]"})

    return hotbot_messages, system_prompt


class HotBotRegister:
    """
    Handles account creation on HotBot:
    1. Fast Session Generator (Guest/Session registration with dedicated session & clean IP).
    2. Email magic link registration (triggers HotBot magic link API to CF Worker mail).
    """
    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy or HTTP_PROXY
        self.email_service = EmailService()

    async def create_session_account(self) -> Optional[dict]:
        """
        Creates an initialized, verified HotBot account session.
        Validates that it can successfully exchange messages.
        """
        fake_ip = generate_random_ip()
        guest_uuid = str(uuid.uuid4())
        chat_id = str(uuid.uuid4())
        
        headers = {
            **COMMON_HEADERS,
            "Content-Type": "application/json",
            "Referer": "https://www.hotbot.com/",
            "Origin": "https://www.hotbot.com",
            "X-Forwarded-For": fake_ip,
            "CF-Connecting-IP": fake_ip,
        }

        cookies = {
            "guest_chat_session": guest_uuid,
            "chatai_language": "en"
        }

        # Verify chat capability with a quick ping
        payload = {
            "messages": [{"role": "user", "content": "ping"}],
            "model": "openai/gpt-4o-mini",
            "chatId": chat_id,
            "effort": "light",
            "camp": False
        }

        try:
            async with AsyncSession(proxy=self.proxy or None, impersonate=IMPERSONATE) as s:
                r = await s.post(
                    f"{HOTBOT_API_URL}/chat",
                    json=payload,
                    headers=headers,
                    cookies=cookies,
                    timeout=30
                )
                if r.status_code == 200:
                    resp_cookie = s.cookies.get("guest_chat_session") or guest_uuid
                    log.info(f"Successfully generated HotBot session account: {resp_cookie[:8]}... (IP: {fake_ip})")
                    return {
                        "account_id": f"guest_{guest_uuid[:8]}",
                        "email": f"guest_{guest_uuid[:8]}@hotbot.local",
                        "guest_chat_session": resp_cookie,
                        "session_token": resp_cookie,
                        "cookies": {"guest_chat_session": resp_cookie},
                        "plan_type": "guest_active",
                        "message_limit": 500,
                        "message_usage": 0
                    }
                else:
                    log.warning(f"Session generation failed with HTTP {r.status_code}: {r.text[:100]}")
                    return None
        except Exception as e:
            log.error(f"Error during HotBot session generation: {e}")
            return None

    async def register_by_email(self) -> Optional[dict]:
        """
        Register / Login via Email Magic Link using Cloudflare Worker mail.
        """
        jwt, email_addr = self.email_service.create_email()
        if not jwt or not email_addr:
            log.error("Failed to generate temp email from Cloudflare Worker")
            return None

        log.info(f"Triggering HotBot email magic link for: {email_addr}")
        try:
            async with AsyncSession(proxy=self.proxy or None, impersonate=IMPERSONATE) as s:
                # 1. Fetch /login to get CSRF token
                r_login = await s.get("https://www.hotbot.com/login", timeout=20)
                csrf = s.cookies.get("hbscsrfst") or ""
                
                headers = {
                    **COMMON_HEADERS,
                    "Origin": "https://www.hotbot.com",
                    "Referer": "https://www.hotbot.com/login",
                    "X-CSRF-Token": csrf,
                    "X-Requested-With": "XMLHttpRequest",
                }
                
                r_req = await s.post(
                    "https://www.hotbot.com/login/request-magic.json",
                    data={"email": email_addr},
                    headers=headers,
                    timeout=20
                )
                
                res_json = r_req.json()
                if res_json.get("code") != 0:
                    log.error(f"HotBot magic request rejected: {res_json}")
                    return None
                    
                log.info(f"HotBot magic link requested for {email_addr}. Polling inbox...")
                # Poll inbox for magic link
                magic_url = None
                for _ in range(15):
                    await asyncio.sleep(2)
                    raw_mail = self.email_service.fetch_first_email(jwt)
                    if raw_mail:
                        # Extract magic link url
                        urls = re.findall(r'https?://[^\s<>"]+(?:auth|login|token)[^\s<>"]*', raw_mail)
                        if urls:
                            magic_url = urls[0]
                            log.info(f"Found magic link URL: {magic_url}")
                            break

                if not magic_url:
                    log.info(f"Note: External mail delivery may be delayed/filtered for new domain. Falling back to session generation.")
                    return await self.create_session_account()

                # Open magic URL
                r_magic = await s.get(magic_url, allow_redirects=True, timeout=30)
                cookies_dict = dict(s.cookies)
                return {
                    "account_id": f"acc_{email_addr.split('@')[0]}",
                    "email": email_addr,
                    "session_token": cookies_dict.get("session") or cookies_dict.get("hbscsrfst", ""),
                    "cookies": cookies_dict,
                    "plan_type": "email_member",
                    "message_limit": 1000,
                    "message_usage": 0
                }
        except Exception as e:
            log.error(f"Email register failed: {e}", exc_info=True)
            return None


async def stream_hotbot_response(
    account: Optional[AccountState],
    model: str,
    messages: list[dict],
    chat_id: str,
    mode: Optional[str] = None
) -> AsyncIterator[dict]:
    """
    Stream chat completion from HotBot API.
    Yields chunks: {"delta": text}, {"tool_calls": [...]}, {"finish_reason": "stop"|"length"|"tool_calls"}
    """
    fake_ip = generate_random_ip()
    headers = {
        **COMMON_HEADERS,
        "Content-Type": "application/json",
        "Referer": "https://www.hotbot.com/",
        "Origin": "https://www.hotbot.com",
        "X-Forwarded-For": fake_ip,
        "CF-Connecting-IP": fake_ip,
    }

    cookies = {}
    if account and account.cookies:
        cookies.update(account.cookies)
    elif account and account.guest_chat_session:
        cookies["guest_chat_session"] = account.guest_chat_session
    else:
        cookies["guest_chat_session"] = str(uuid.uuid4())

    hotbot_messages, _ = messages_to_hotbot(messages)

    payload = {
        "messages": hotbot_messages,
        "model": model,
        "chatId": chat_id,
        "effort": "light",
        "camp": False
    }
    if mode in ("web_search", "deep_research"):
        payload["mode"] = mode

    async with AsyncSession(proxy=HTTP_PROXY or None, impersonate=IMPERSONATE) as s:
        resp = await s.post(
            f"{HOTBOT_API_URL}/chat",
            json=payload,
            headers=headers,
            cookies=cookies,
            stream=True,
            timeout=120
        )

        if resp.status_code != 200:
            err_text = resp.text
            raise ServerError(f"HotBot API returned status {resp.status_code}: {err_text[:200]}")

        # Check content type
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" not in content_type:
            # Maybe returned json rate limit error
            err_text = resp.text
            try:
                err_json = json.loads(err_text)
                if "rate_limit" in err_json.get("type", "") or "rate_limit" in err_json.get("code", ""):
                    raise ServerError(f"HotBot rate limit: {err_json.get('detail', 'Rate limited')}")
            except Exception:
                pass
            raise ServerError(f"Unexpected non-stream response: {err_text[:200]}")

        # Stream SSE lines
        has_content = False
        async for line in resp.aiter_lines():
            line_str = line.decode("utf-8", errors="ignore").strip() if isinstance(line, (bytes, bytearray)) else str(line).strip()
            if not line_str or line_str.startswith(":"):
                continue

            if line_str == "data: [DONE]":
                yield {"finish_reason": "stop"}
                return

            if line_str.startswith("data: "):
                raw_data = line_str[6:].strip()
                try:
                    data = json.loads(raw_data)
                except Exception:
                    continue

                if "content" in data:
                    c = data["content"]
                    has_content = True
                    yield {"delta": c}
                elif "tool_calls" in data:
                    has_content = True
                    yield {"tool_calls": data["tool_calls"]}
                elif "finish_reason" in data:
                    yield {"finish_reason": data["finish_reason"]}

        if not has_content:
            raise EmptyResponseError("HotBot returned empty response stream")
