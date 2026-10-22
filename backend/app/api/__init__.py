"""HTTP routers for the console, the assistant, voice, and journeys.

Each builder receives its dependencies explicitly instead of importing a module
global. Tests can build a fresh app with its own state and get fresh routers,
which is the same reason `create_app` takes explicit settings.
"""

from app.api.assistant import build_assistant_router
from app.api.auth import build_auth_router
from app.api.call import build_call_router
from app.api.journeys import build_journeys_router
from app.api.meta import build_meta_router
from app.api.privacy import build_privacy_router
from app.api.state import build_state_router
from app.api.voice import build_voice_router

__all__ = [
    "build_assistant_router",
    "build_auth_router",
    "build_call_router",
    "build_journeys_router",
    "build_meta_router",
    "build_privacy_router",
    "build_state_router",
    "build_voice_router",
]
