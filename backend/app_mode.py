"""Site mode for public deployments (set APP_MODE in .env on the server; visitors can't change it).

demo    (default) - everything works, including live LLM calls.
inspect           - visitors can browse the app and the saved conversations, but nothing that
                    spends LLM credits runs. Deleting chats and re-ingesting the knowledge base
                    are also blocked, so the showcase stays intact for the next visitor.
"""
import os

from fastapi import HTTPException

DEFAULT_CONTACT = "harshvardhan.masalge@iiitgn.ac.in"


def app_mode() -> str:
    return "inspect" if os.getenv("APP_MODE", "demo").strip().lower() == "inspect" else "demo"


def is_inspect() -> bool:
    return app_mode() == "inspect"


def contact_email() -> str:
    return os.getenv("DEMO_CONTACT_EMAIL", "").strip() or DEFAULT_CONTACT


def inspect_message() -> str:
    return ("This deployment is in inspect mode: live AI analysis is turned off to save LLM credits. "
            "You can explore the app and the saved example conversations. "
            f"For a live demo, kindly contact {contact_email()}.")


class InspectModeError(RuntimeError):
    """Raised if anything tries to call an LLM while the site is in inspect mode."""


def require_demo_mode() -> None:
    """FastAPI dependency: refuse the request in inspect mode."""
    if is_inspect():
        raise HTTPException(status_code=403, detail=inspect_message())


def public_config() -> dict:
    return {"mode": app_mode(), "contact_email": contact_email(),
            "message": inspect_message() if is_inspect() else None}
