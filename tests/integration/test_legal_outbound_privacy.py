"""Privacy gate: no raw PII leaves the daemon to OpenLégi.

Mirrors test_no_pii_leak_phase2.py but for the outbound boundary.
Failing this test = compliance defect, not a bug.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from piighost.service.config import ServiceConfig, RerankerSection, OpenLegiSection
from piighost.service.core import PIIGhostService
from piighost.service.credentials import CredentialsService


_KNOWN_RAW_PII = [
    "Marie Curie",
    "marie.curie@acme.fr",
    "+33 6 12 34 56 78",
    "FR1420041010050500013M02606",
    "1 75 03 75 116 042 87",      # French SSN
]


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return tmp_path / "vault"


def _sse(payload):
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def _stub_anonymize_known_pii(text: str) -> str:
    """Stub anonymize that knows about the 5 test PII strings."""
    out = text
    for pii in _KNOWN_RAW_PII:
        out = out.replace(pii, "[REDACTED]")
    return out


@pytest.fixture()
def patched_redactor(monkeypatch):
    """Force OutboundRedactor to use our PII-aware stub regardless of
    what _legal_call passes in."""
    import piighost.legal.redactor as redactor_module
    _orig_init = redactor_module.OutboundRedactor.__init__

    def _patched_init(self, anonymize_fn):
        _orig_init(self, _stub_anonymize_known_pii)

    monkeypatch.setattr(
        redactor_module.OutboundRedactor, "__init__", _patched_init,
    )


def test_legal_outbound_no_pii_leak(vault_dir, monkeypatch, patched_redactor):
    """For 10 inputs combining each PII × legal-grammar context,
    the wire payload must never contain any raw PII."""

    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": []}}),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    # Capture the real httpx.Client BEFORE monkeypatching, otherwise the
    # lambda recurses into itself (httpx.Client is the same object as
    # piighost.legal.piste_client.httpx.Client — they share the module).
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    CredentialsService().set_openlegi_token("test-token")
    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=True),
    )
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))

    # 10 inputs combining each PII with legal-grammar context
    inputs = [
        f"{pii} a invoqué l'article 1240 du Code civil"
        for pii in _KNOWN_RAW_PII
    ] + [
        f"Cass. civ. 1re, 15 mars 2023, n°21-12.345 — partie: {pii}"
        for pii in _KNOWN_RAW_PII
    ]

    for input_text in inputs:
        asyncio.run(svc.legal_search(query=input_text, source="code"))

    # 10 inputs → 10 captured payloads
    assert len(captured_payloads) == 10

    # Every captured payload must be PII-free
    for i, payload in enumerate(captured_payloads):
        serialized = json.dumps(payload)
        for pii in _KNOWN_RAW_PII:
            assert pii not in serialized, (
                f"PII '{pii}' leaked in payload #{i}: {serialized}"
            )

    # AND the legal grammar must have survived (article numbers / pourvoi)
    for i, payload in enumerate(captured_payloads):
        serialized = json.dumps(payload)
        assert (
            "1240" in serialized or "21-12.345" in serialized
        ), f"legal grammar lost in payload #{i}: {serialized}"

    asyncio.run(svc.close())


def test_legal_outbound_redactor_strips_placeholder_format(vault_dir, monkeypatch):
    """Even if the caller already anonymised to <<label:HASH>> form,
    we strip that pattern — it leaks our redaction scheme. This test
    does NOT need the patched redactor — the placeholder strip is
    unconditional in OutboundRedactor.redact()."""

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": []}}),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    CredentialsService().set_openlegi_token("test-token")
    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=True),
    )
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))

    asyncio.run(svc.legal_search(
        query="<<nom_personne:abc12345>> article 1240", source="code",
    ))

    serialized = json.dumps(captured[0])
    assert "<<nom_personne:abc12345>>" not in serialized
    assert "1240" in serialized

    asyncio.run(svc.close())


def test_legal_outbound_real_anonymize_redacts_pii(vault_dir, monkeypatch):
    """Without the patched_redactor fixture — proves _legal_call's
    OWN anonymize wiring redacts PII (closes I-1).

    Uses the real default-project anonymize (with stub detector for
    determinism in tests). Stub detector recognizes a small set of
    test fixtures including 'Alice' (PERSON) and 'Paris' (LOC).
    """
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": []}}),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    CredentialsService().set_openlegi_token("test-token")
    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=True),
    )
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))

    # Use a name the stub detector knows ("Alice") — query also has
    # legal grammar ("article 1240") that must survive.
    asyncio.run(svc.legal_search(
        query="Alice habite à Paris et invoque l'article 1240 du Code civil",
        source="code",
    ))

    assert len(captured) == 1
    serialized = json.dumps(captured[0])
    # Stub detector tags "Alice" / "Paris" — those should be replaced
    # with <<label:HASH>> placeholders by anonymize, then stripped by
    # the redactor.
    assert "Alice" not in serialized
    assert "Paris" not in serialized
    # Legal grammar survives the anonymize pass (no PII labels for
    # article numbers + code names)
    assert "1240" in serialized
    assert "Code civil" in serialized

    asyncio.run(svc.close())
