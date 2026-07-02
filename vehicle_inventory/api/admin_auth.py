"""Simple session auth for the /admin dashboard."""

from __future__ import annotations

import os
import secrets
from functools import wraps
from typing import Callable

from flask import Flask, current_app, jsonify, redirect, request, session, url_for


def configure_admin(app: Flask) -> None:
    app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "").strip()
    secret = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
    app.config["SECRET_KEY"] = secret
    app.secret_key = secret


def admin_enabled(app: Flask) -> bool:
    return bool(app.config.get("ADMIN_PASSWORD"))


def is_admin_authenticated() -> bool:
    return bool(session.get("admin_authenticated"))


def require_admin_page(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not admin_enabled(current_app):
            return view(*args, admin_enabled=False, authenticated=False, **kwargs)
        if not is_admin_authenticated():
            return redirect(url_for("admin_login"))
        return view(*args, admin_enabled=True, authenticated=True, **kwargs)

    return wrapped


def require_admin_api(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not admin_enabled(current_app):
            return jsonify({"error": "Admin is disabled. Set ADMIN_PASSWORD."}), 503
        if not is_admin_authenticated():
            return jsonify({"error": "Admin authentication required."}), 401
        return view(*args, **kwargs)

    return wrapped
