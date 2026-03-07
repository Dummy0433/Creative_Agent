"""Inspire session store 测试。"""

import time
from unittest.mock import patch

from models import InspireSession


def test_save_and_get():
    from pipeline import inspire_store
    inspire_store._store.clear()
    session = InspireSession(user_id="ou_1")
    inspire_store.save(session)
    result = inspire_store.get("ou_1")
    assert result is not None
    assert result.user_id == "ou_1"


def test_get_nonexistent():
    from pipeline import inspire_store
    inspire_store._store.clear()
    assert inspire_store.get("ou_nonexist") is None


def test_remove():
    from pipeline import inspire_store
    inspire_store._store.clear()
    session = InspireSession(user_id="ou_2")
    inspire_store.save(session)
    inspire_store.remove("ou_2")
    assert inspire_store.get("ou_2") is None


def test_ttl_expiry():
    from pipeline import inspire_store
    inspire_store._store.clear()
    session = InspireSession(user_id="ou_3")
    inspire_store.save(session)
    with patch("time.time", return_value=time.time() + 9999):
        assert inspire_store.get("ou_3") is None
