"""Tests for coverage-matrix routing in the forward-proxy dispatcher."""

from __future__ import annotations

from piighost.proxy.forward.dispatch import (
    CoverageMatrix,
    Dispatcher,
)
from piighost.proxy.forward.handlers.passthrough import PassthroughHandler
from piighost.proxy.forward.handlers.unknown import UnknownEndpointHandler


def test_known_method_path_returns_matching_handler():
    h = PassthroughHandler()
    matrix: CoverageMatrix = {("GET", "/v1/models"): h}
    dispatcher = Dispatcher(
        matrix=matrix, default=UnknownEndpointHandler(audit_writer=None)
    )

    result = dispatcher.dispatch(method="GET", path="/v1/models")

    assert result is h


def test_unknown_method_path_returns_default_handler():
    default = UnknownEndpointHandler(audit_writer=None)
    matrix: CoverageMatrix = {("GET", "/v1/models"): PassthroughHandler()}
    dispatcher = Dispatcher(matrix=matrix, default=default)

    result = dispatcher.dispatch(method="POST", path="/v1/wat")

    assert result is default


def test_path_with_trailing_query_string_is_normalized():
    h = PassthroughHandler()
    matrix: CoverageMatrix = {("GET", "/v1/models"): h}
    dispatcher = Dispatcher(
        matrix=matrix, default=UnknownEndpointHandler(audit_writer=None)
    )

    result = dispatcher.dispatch(
        method="GET", path="/v1/models?include_deprecated=true"
    )

    assert result is h


def test_method_is_case_insensitive():
    h = PassthroughHandler()
    matrix: CoverageMatrix = {("GET", "/v1/models"): h}
    dispatcher = Dispatcher(
        matrix=matrix, default=UnknownEndpointHandler(audit_writer=None)
    )

    result = dispatcher.dispatch(method="get", path="/v1/models")

    assert result is h


def test_id_path_segments_match_with_pattern():
    """`/v1/files/{id}` in matrix should match `/v1/files/file_abc123`."""
    h = PassthroughHandler()
    matrix: CoverageMatrix = {("GET", "/v1/files/{id}"): h}
    dispatcher = Dispatcher(
        matrix=matrix, default=UnknownEndpointHandler(audit_writer=None)
    )

    result = dispatcher.dispatch(method="GET", path="/v1/files/file_abc123")

    assert result is h


def test_id_pattern_does_not_overmatch():
    """`/v1/files/{id}` should not match `/v1/files/file_abc/sub`."""
    h = PassthroughHandler()
    matrix: CoverageMatrix = {("GET", "/v1/files/{id}"): h}
    default = UnknownEndpointHandler(audit_writer=None)
    dispatcher = Dispatcher(matrix=matrix, default=default)

    result = dispatcher.dispatch(method="GET", path="/v1/files/file_abc/sub")

    assert result is default


def test_default_matrix_includes_messages_and_models(stub_service):
    from piighost.proxy.forward.dispatch import build_default_dispatcher

    dispatcher = build_default_dispatcher(
        service=stub_service,
        audit=None,
    )

    msg_handler = dispatcher.dispatch(method="POST", path="/v1/messages")
    models_handler = dispatcher.dispatch(method="GET", path="/v1/models")
    unknown_handler = dispatcher.dispatch(method="POST", path="/v1/wat")

    from piighost.proxy.forward.handlers.messages import MessagesHandler
    from piighost.proxy.forward.handlers.passthrough import PassthroughHandler
    from piighost.proxy.forward.handlers.unknown import UnknownEndpointHandler

    assert isinstance(msg_handler, MessagesHandler)
    assert isinstance(models_handler, PassthroughHandler)
    assert isinstance(unknown_handler, UnknownEndpointHandler)
