"""
Model list and model routing for HotBot
"""
from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter()

DEFAULT_MODEL = "openai/gpt-4o-mini"

# Map standard public OpenAI model IDs to HotBot backend model slugs
MODEL_MAPPING = {
    # OpenAI series
    "gpt-4o-mini": "openai/gpt-4o-mini",
    "gpt-4o": "openai/gpt-4o",
    "chatgpt-4o-latest": "openai/gpt-4o",
    "chatgpt-4o-mini": "openai/gpt-4o-mini",
    "chatgpt-5": "openai/gpt-4o",
    "chatgpt-5-mini": "openai/gpt-4o-mini",
    "gpt-5": "openai/gpt-4o",
    "gpt-5-2": "openai/gpt-4o",
    
    # Anthropic series (HotBot routes to claude-3.5-haiku / claude-sonnet-4)
    "claude-3-5-haiku": "anthropic/claude-3.5-haiku",
    "claude-haiku": "anthropic/claude-3.5-haiku",
    "claude-3-5-sonnet": "anthropic/claude-sonnet-4",
    "claude-sonnet": "anthropic/claude-sonnet-4",
    "claude-sonnet-4": "anthropic/claude-sonnet-4",
    "claude-sonnet-46": "anthropic/claude-sonnet-4",
    
    # Open-source / meta
    "llama-3.3-70b": "meta-llama/llama-3.3-70b-instruct",
    "llama-4-maverick": "meta-llama/llama-3.3-70b-instruct",
    "hotbot-chat": "hotbot-chat",
}

AVAILABLE_MODELS = [
    {
        "id": "gpt-4o-mini",
        "object": "model",
        "created": 1715500000,
        "owned_by": "openai",
        "permission": [],
        "root": "gpt-4o-mini",
        "parent": None,
    },
    {
        "id": "gpt-4o",
        "object": "model",
        "created": 1715500000,
        "owned_by": "openai",
        "permission": [],
        "root": "gpt-4o",
        "parent": None,
    },
    {
        "id": "chatgpt-4o-latest",
        "object": "model",
        "created": 1715500000,
        "owned_by": "openai",
        "permission": [],
        "root": "chatgpt-4o-latest",
        "parent": None,
    },
    {
        "id": "claude-3-5-haiku",
        "object": "model",
        "created": 1715500000,
        "owned_by": "anthropic",
        "permission": [],
        "root": "claude-3-5-haiku",
        "parent": None,
    },
    {
        "id": "claude-3-5-sonnet",
        "object": "model",
        "created": 1715500000,
        "owned_by": "anthropic",
        "permission": [],
        "root": "claude-3-5-sonnet",
        "parent": None,
    },
    {
        "id": "hotbot-chat",
        "object": "model",
        "created": 1715500000,
        "owned_by": "hotbot",
        "permission": [],
        "root": "hotbot-chat",
        "parent": None,
    },
]

def resolve_model(model_name: str) -> str:
    """Resolve an incoming model request to the proper HotBot backend slug"""
    if not model_name:
        return DEFAULT_MODEL
    cleaned = model_name.strip().lower()
    if cleaned in MODEL_MAPPING:
        return MODEL_MAPPING[cleaned]
    # Direct match if caller passed backend slug like openai/gpt-4o
    for v in MODEL_MAPPING.values():
        if cleaned == v.lower():
            return v
    # Fallback to gpt-4o-mini
    return DEFAULT_MODEL

@router.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": AVAILABLE_MODELS
    }
