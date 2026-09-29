"""
Admin and registration router for HotBot
"""
import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from app.cookie_manager import cm
from app.hotbot_client import HotBotRegister
from app.models import AccountState

log = logging.getLogger("hotbot_proxy.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

class RegisterRequest(BaseModel):
    count: int = 1
    type: str = "session"  # "session" or "email"

@router.get("/tokens/detail")
async def get_tokens_detail():
    """Return status of all accounts in the pool"""
    return cm.get_tokens_detail()

@router.post("/register/start")
async def start_registration(req: RegisterRequest, background_tasks: BackgroundTasks):
    """
    Trigger registration of new HotBot accounts (session-based or email-based)
    """
    async def _do_register(count: int, reg_type: str):
        reg = HotBotRegister()
        for i in range(count):
            try:
                if reg_type == "email":
                    acc_data = await reg.register_by_email()
                else:
                    acc_data = await reg.create_session_account()

                if acc_data:
                    new_idx = len(cm.accounts) + 1
                    acc = AccountState(acc_data, new_idx)
                    cm.accounts.append(acc)
                    if new_idx not in cm.active_pool:
                        cm.active_pool.append(new_idx)
                    cm.save()
                    log.info(f"Registered HotBot account ({i+1}/{count}): {acc.email}")
                else:
                    log.warning(f"Failed to register account ({i+1}/{count})")
            except Exception as e:
                log.error(f"Error registering account: {e}", exc_info=True)
            await asyncio.sleep(1)

    background_tasks.add_task(_do_register, req.count, req.type)
    return {
        "status": "started",
        "count": req.count,
        "type": req.type,
        "message": f"Registration task for {req.count} HotBot accounts initiated."
    }

@router.post("/pool/refresh")
async def refresh_pool():
    """Trigger replenishment of active pool"""
    asyncio.create_task(cm.replenish_active_pool())
    return {"status": "pool_replenish_scheduled"}
