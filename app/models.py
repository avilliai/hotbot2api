"""
Account state data model for HotBot
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any

ACCOUNT_QUOTA = 1000

class AccountState:
    def __init__(self, d: dict, index: int = 1):
        self.index = index
        self.email = d.get("email", "")
        self.account_id = d.get("account_id", "")
        self.session_token = d.get("session_token", "")
        self.guest_chat_session = d.get("guest_chat_session", "")
        self.cookies: Dict[str, str] = d.get("cookies", {})
        self.disabled = d.get("disabled", False)
        self.healthy = d.get("healthy", True)
        self.usage_count = d.get("usage_count", 0)
        self.message_limit = d.get("message_limit", ACCOUNT_QUOTA)
        self.message_usage = d.get("message_usage", self.usage_count)
        self.quota_exhausted_flag = d.get("quota_exhausted", False)
        self.fail_count = d.get("fail_count", 0)
        self.plan_type = d.get("plan_type", "guest_or_member")
        self.created_at = d.get("created_at", datetime.now(timezone.utc).isoformat())

        if not self.cookies and self.guest_chat_session:
            self.cookies = {"guest_chat_session": self.guest_chat_session}
        elif self.cookies and "guest_chat_session" in self.cookies and not self.guest_chat_session:
            self.guest_chat_session = self.cookies["guest_chat_session"]

    @property
    def remaining(self) -> int:
        limit = self.message_limit if self.message_limit > 0 else ACCOUNT_QUOTA
        return max(0, limit - self.message_usage)

    @property
    def is_alive(self) -> bool:
        return self.healthy and not self.disabled and not self.quota_exhausted

    @property
    def quota_exhausted(self) -> bool:
        if self.quota_exhausted_flag:
            return True
        limit = self.message_limit if self.message_limit > 0 else ACCOUNT_QUOTA
        return self.message_usage >= limit

    def mark_quota_exhausted(self) -> None:
        self.quota_exhausted_flag = True
        self.disabled = True

    def mark_recovered(self) -> None:
        self.quota_exhausted_flag = False
        self.disabled = False
        self.healthy = True
        self.fail_count = 0

    @property
    def token_hint(self) -> str:
        s = self.guest_chat_session or self.session_token
        if s and len(s) > 16:
            return f"{s[:6]}...{s[-6:]}"
        return self.email or "guest-account"

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "account_id": self.account_id,
            "session_token": self.session_token,
            "guest_chat_session": self.guest_chat_session,
            "cookies": self.cookies,
            "disabled": self.disabled,
            "healthy": self.healthy,
            "usage_count": self.usage_count,
            "message_limit": self.message_limit,
            "message_usage": self.message_usage,
            "quota_exhausted": self.quota_exhausted_flag,
            "fail_count": self.fail_count,
            "plan_type": self.plan_type,
            "created_at": self.created_at,
        }
