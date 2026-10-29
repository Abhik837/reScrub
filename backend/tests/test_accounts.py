"""Accounts CLI: `ensure` creates the first admin once (used by the local Docker stack)."""

import os
import sys

from rescrub import accounts, auth
from rescrub.settings import get_settings


def run(monkeypatch, *args):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setattr(sys, "argv", ["accounts", *args])
    get_settings.cache_clear()
    try:
        accounts.main()
    finally:
        get_settings.cache_clear()


def test_ensure_creates_an_admin_only_once(pool, monkeypatch, capsys):
    run(monkeypatch, "ensure", "Admin@Example.com")
    out = capsys.readouterr().out
    assert "Created admin admin@example.com" in out and "Password: " in out
    password = out.split("Password: ")[1].strip()
    assert auth.authenticate(pool, "admin@example.com", password)["role"] == "admin"

    run(monkeypatch, "ensure", "admin@example.com")
    assert "already has an account" in capsys.readouterr().out
    assert len(auth.list_users(pool)) == 1
    assert auth.authenticate(pool, "admin@example.com", password)  # password unchanged
