"""Request-scoped make selection for Flask."""

from __future__ import annotations

from flask import request, session

from vehicle_inventory.makes.registry import get_default_make_slug, get_make_profile

SESSION_MAKE_KEY = "selected_make"


def resolve_make_slug() -> str:
    raw = (request.args.get("make") or session.get(SESSION_MAKE_KEY) or "").strip().lower()
    if raw:
        try:
            return get_make_profile(raw).slug
        except KeyError:
            pass
    return get_default_make_slug()


def set_session_make(slug: str) -> str:
    profile = get_make_profile(slug)
    session[SESSION_MAKE_KEY] = profile.slug
    return profile.slug
