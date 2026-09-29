"""
Account and Cookie Pool Manager for HotBot
"""
import asyncio
import json
import logging
import os
import threading
from typing import Optional, List

from app.config import TOKENS_FILE, ACTIVE_POOL_FILE, ACTIVE_POOL_SIZE
from app.models import AccountState
from app.hotbot_client import HotBotRegister

log = logging.getLogger("hotbot_proxy.cookie_manager")
FAIL_THRESHOLD = int(os.environ.get("ACCOUNT_FAIL_THRESHOLD", "3"))

class CookieManager:
    def __init__(self):
        self.accounts: List[AccountState] = []
        self.active_pool: List[int] = []
        self._idx: int = 0
        self._idx_lock = asyncio.Lock()
        self._sync_lock = threading.Lock()
        self._replenish_lock = asyncio.Lock()
        self._replenishing: bool = False
        self.last_refresh: Optional[str] = None
        self.register = HotBotRegister()
        self.load()

    def load(self) -> None:
        if not TOKENS_FILE.exists():
            log.warning(f"File {TOKENS_FILE} does not exist. Initializing empty.")
            self.save()
            return
        try:
            raw_text = TOKENS_FILE.read_text(encoding="utf-8")
            data = json.loads(raw_text)
            with self._sync_lock:
                accounts = []
                for i, d in enumerate(data):
                    acc = AccountState(d, i + 1)
                    accounts.append(acc)
                self.accounts = accounts
            log.info(f"Loaded {len(self.accounts)} HotBot accounts from disk.")

            if ACTIVE_POOL_FILE.exists():
                try:
                    pool_data = json.loads(ACTIVE_POOL_FILE.read_text(encoding="utf-8"))
                    if isinstance(pool_data, list):
                        self.active_pool = [int(x) for x in pool_data]
                except Exception as pe:
                    log.warning(f"Failed to read {ACTIVE_POOL_FILE}: {pe}")
                    self.active_pool = []
            else:
                self.active_pool = []
        except Exception as e:
            log.error(f"Error loading {TOKENS_FILE}: {e}", exc_info=True)

    def save(self) -> None:
        with self._sync_lock:
            data = [a.to_dict() for a in self.accounts]
            TOKENS_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            ACTIVE_POOL_FILE.write_text(
                json.dumps(self.active_pool, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    async def async_save(self) -> None:
        await asyncio.to_thread(self.save)

    def _find_by_index(self, idx: int) -> Optional[AccountState]:
        return next((a for a in self.accounts if a.index == idx), None)

    @staticmethod
    def _account_is_eligible(acc: Optional[AccountState]) -> bool:
        if not acc:
            return False
        return acc.healthy and not acc.disabled and not acc.quota_exhausted

    async def replenish_active_pool(self) -> None:
        """Ensure active pool has enough healthy accounts; auto-registers if needed."""
        if self._replenishing:
            return
        async with self._replenish_lock:
            self._replenishing = True
            try:
                # Remove dead accounts from pool
                valid_pool = []
                for idx in self.active_pool:
                    acc = self._find_by_index(idx)
                    if self._account_is_eligible(acc):
                        valid_pool.append(idx)
                self.active_pool = valid_pool

                needed = ACTIVE_POOL_SIZE - len(self.active_pool)
                if needed <= 0:
                    self.save()
                    return

                # Try to recruit existing accounts
                with self._sync_lock:
                    for acc in self.accounts:
                        if acc.index not in self.active_pool and self._account_is_eligible(acc):
                            self.active_pool.append(acc.index)
                            needed -= 1
                            if needed <= 0:
                                break

                # Auto register if still needed
                while needed > 0:
                    log.info(f"Active pool requires {needed} more accounts. Auto-creating session account...")
                    acc_data = await self.register.create_session_account()
                    if not acc_data:
                        break
                    with self._sync_lock:
                        new_idx = len(self.accounts) + 1
                        new_acc = AccountState(acc_data, new_idx)
                        self.accounts.append(new_acc)
                        self.active_pool.append(new_idx)
                    needed -= 1

                self.save()
            finally:
                self._replenishing = False

    async def get_account(self) -> AccountState:
        """Round-robin selection of active account"""
        if not self.active_pool:
            await self.replenish_active_pool()

        if not self.active_pool:
            # Fallback: create temporary transient session account
            log.warning("No accounts available in pool. Creating transient account...")
            acc_data = await self.register.create_session_account()
            if acc_data:
                return AccountState(acc_data, 9999)
            raise RuntimeError("No available HotBot accounts in pool")

        async with self._idx_lock:
            self._idx = (self._idx + 1) % len(self.active_pool)
            target_idx = self.active_pool[self._idx]

        acc = self._find_by_index(target_idx)
        if not self._account_is_eligible(acc):
            asyncio.create_task(self.replenish_active_pool())
            return await self.get_account()

        return acc

    async def report_success(self, account: AccountState):
        account.usage_count += 1
        account.message_usage += 1
        account.fail_count = 0
        account.healthy = True
        if account.message_usage >= account.message_limit:
            account.mark_quota_exhausted()
            if account.index in self.active_pool:
                self.active_pool.remove(account.index)
            asyncio.create_task(self.replenish_active_pool())
        self.save()

    async def report_failure(self, account: AccountState, reason: str = ""):
        account.fail_count += 1
        log.warning(f"Account {account.email} failed ({account.fail_count}/{FAIL_THRESHOLD}): {reason}")
        if account.fail_count >= FAIL_THRESHOLD or "rate limit" in reason.lower() or "limit_guest" in reason.lower():
            account.healthy = False
            account.disabled = True
            if account.index in self.active_pool:
                self.active_pool.remove(account.index)
            asyncio.create_task(self.replenish_active_pool())
        self.save()

    
    async def get_next(self) -> AccountState:
        return await self.get_account()

    def record_usage(self, account: AccountState):
        asyncio.create_task(self.report_success(account))

    async def mark_failed_and_get_replacement(self, account: AccountState, reason: str = '', attempt: int = 1) -> AccountState:
        await self.report_failure(account, reason)
        return await self.get_account()

    def get_tokens_detail(self) -> dict:
        tokens_list = []
        alive_count = 0
        active_set = set(self.active_pool)

        with self._sync_lock:
            for acc in self.accounts:
                rem = acc.remaining
                if acc.healthy and not acc.disabled and rem > 0:
                    alive_count += 1

                tokens_list.append({
                    "index": acc.index,
                    "email": acc.email,
                    "token_hint": acc.token_hint,
                    "is_alive": acc.healthy and not acc.disabled,
                    "disabled": acc.disabled,
                    "is_active": acc.index in active_set,
                    "quota_exhausted": acc.quota_exhausted,
                    "remaining": rem,
                    "usage_count": acc.usage_count,
                    "fail_count": acc.fail_count,
                    "plan_type": acc.plan_type,
                })

        return {
            "tokens": tokens_list,
            "summary": {
                "total": len(self.accounts),
                "alive": alive_count,
                "active_pool_size": len(self.active_pool),
                "active_pool_target": ACTIVE_POOL_SIZE,
            },
        }

cm = CookieManager()
