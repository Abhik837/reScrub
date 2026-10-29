"""When the database can't be used, db.connect says why (the pool alone reports only a timeout)."""

import socket

import pytest

from rescrub import db


def test_connection_failure_names_the_cause_without_the_password():
    with socket.socket() as s:  # a port nothing listens on
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"postgresql://rescrub:secret-pw-123@127.0.0.1:{port}/rescrub?connect_timeout=2"
    with pytest.raises(RuntimeError) as err:
        db.connect(url, wait_sec=2)
    message = str(err.value)
    assert f"127.0.0.1:{port}/rescrub" in message and "refused" in message.lower()
    assert "secret-pw-123" not in message
