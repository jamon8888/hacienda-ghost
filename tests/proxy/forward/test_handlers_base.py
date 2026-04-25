"""Tests for the Handler base class contract."""
from __future__ import annotations

import pytest

from piighost.proxy.forward.handlers.base import Handler


def test_handler_is_abstract():
    with pytest.raises(TypeError):
        Handler()  # type: ignore[abstract]


def test_handler_subclass_must_implement_handle_request():
    class Incomplete(Handler):
        async def handle_response(self, flow):  # type: ignore[no-untyped-def]
            pass

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_handler_subclass_must_implement_handle_response():
    class Incomplete(Handler):
        async def handle_request(self, flow):  # type: ignore[no-untyped-def]
            pass

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_complete_subclass_instantiable():
    class Complete(Handler):
        async def handle_request(self, flow):  # type: ignore[no-untyped-def]
            return None

        async def handle_response(self, flow):  # type: ignore[no-untyped-def]
            return None

    Complete()  # no error
