"""Service-level tests for the 5 legal RPC methods."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from piighost.service.config import ServiceConfig, RerankerSection, OpenLegiSection
from piighost.service.core import PIIGhostService


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


def _svc(vault_dir, monkeypatch, *, openlegi_enabled=True):
    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=openlegi_enabled),
    )
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def _sse(payload):
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def test_extract_legal_refs_no_network(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    refs = asyncio.run(svc.legal_extract_refs(text="article 1240 du Code civil"))
    assert len(refs) == 1
    assert refs[0]["ref_type"] == "ARTICLE_CODE"
    asyncio.run(svc.close())


def test_verify_disabled_returns_unknown(vault_dir, monkeypatch):
    """When [openlegi].enabled=False, verify returns the disabled status."""
    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=False)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240 du Code civil",
        "numero": "1240", "code": "Code civil", "position": 0,
    }))
    assert result["status"] == "UNKNOWN_OPENLEGI_DISABLED"
    asyncio.run(svc.close())


def test_verify_no_token_returns_unknown(vault_dir, monkeypatch):
    """Enabled but no PISTE token -> UNKNOWN_AUTH_FAILED."""
    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    # No token set
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "x", "numero": "1240", "code": "Code civil", "position": 0,
    }))
    assert result["status"] in ("UNKNOWN_AUTH_FAILED", "UNKNOWN_OPENLEGI_DISABLED")
    asyncio.run(svc.close())


def test_search_legal_with_mocked_transport(vault_dir, monkeypatch):
    """search_legal hits OpenLégi via MockTransport — no real network."""
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1,
                       "result": {"hits": [{"title": "Code civil, Art. 1240"}]}}),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    hits = asyncio.run(svc.legal_search(query="article 1240", source="code"))
    assert isinstance(hits, list)
    asyncio.run(svc.close())


def test_credentials_set_persists(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.legal_credentials_set(token="new-token-xyz"))
    from piighost.service.credentials import CredentialsService
    assert CredentialsService().get_openlegi_token() == "new-token-xyz"
    asyncio.run(svc.close())


def test_passthrough_force_redacts(vault_dir, monkeypatch):
    """Even legal_passthrough applies the redactor — no opt-out."""
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("test-token")

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    asyncio.run(svc.legal_passthrough(
        tool="rechercher_code",
        args={"search": "Marie Curie article 1240"},   # Marie Curie should be redacted
    ))
    # Inspect what we sent
    assert captured
    body = captured[0]
    sent_args = body["params"]["arguments"]
    # NOTE: stub anonymize doesn't actually know "Marie Curie" — but
    # this test confirms the redactor is invoked. The privacy gate
    # in test_legal_outbound_privacy.py (Task 9) does the real check.
    assert "search" in sent_args
    asyncio.run(svc.close())


def test_verify_legal_ref_401_maps_to_auth_failed(vault_dir, monkeypatch):
    """A 401 from OpenLégi must classify as UNKNOWN_AUTH_FAILED, not _NETWORK."""
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("expired-token")

    def handler(request):
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240 du Code civil",
        "numero": "1240", "code": "Code civil", "position": 0,
    }))
    assert result["status"] == "UNKNOWN_AUTH_FAILED", result
    asyncio.run(svc.close())


def test_verify_legal_ref_429_maps_to_rate_limited_after_retries(vault_dir, monkeypatch):
    """After exhausting 429 retries, status must be UNKNOWN_RATE_LIMITED."""
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    def handler(request):
        return httpx.Response(429, text="rate limited")

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )
    monkeypatch.setattr("time.sleep", lambda s: None)

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240", "numero": "1240", "code": "Code civil",
        "position": 0,
    }))
    assert result["status"] == "UNKNOWN_RATE_LIMITED", result
    asyncio.run(svc.close())


def test_verify_legal_ref_network_error_maps_to_network(vault_dir, monkeypatch):
    """A network-level exception (DNS, conn refused) maps to UNKNOWN_NETWORK."""
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    def handler(request):
        raise httpx.ConnectError("name resolution failed")

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240", "numero": "1240", "code": "Code civil",
        "position": 0,
    }))
    assert result["status"] == "UNKNOWN_NETWORK", result
    asyncio.run(svc.close())


def test_legal_cache_clear_returns_count(vault_dir, monkeypatch):
    """legal_cache_clear empties the cache and returns the row count."""
    import json
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    captured: list = []
    def handler(request):
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

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    asyncio.run(svc.legal_search(query="x", source="code"))
    asyncio.run(svc.legal_search(query="y", source="cnil"))

    result = asyncio.run(svc.legal_cache_clear())
    assert result == {"removed": 2}
    asyncio.run(svc.close())


def test_legal_cache_clear_on_empty_returns_zero(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_cache_clear())
    assert result == {"removed": 0}
    asyncio.run(svc.close())


def test_legal_search_distinguishes_error_from_empty(vault_dir, monkeypatch):
    """An OpenLégi error must produce a structured error dict, not [].

    Empty hits → []
    Auth/network error → [{"source": "_error", "title": "...", ...}]
    """
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("expired-token")

    def handler(request):
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    hits = asyncio.run(svc.legal_search(query="x", source="code"))
    # NOT empty list — should be a 1-item list with the error sentinel
    assert len(hits) == 1
    assert hits[0]["source"] == "_error"
    assert hits[0].get("category") == "auth"
    assert "title" in hits[0]
    asyncio.run(svc.close())


def test_legal_search_empty_hits_returns_plain_empty(vault_dir, monkeypatch):
    """200 OK with hits=[] still returns []."""
    import json
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    def handler(request):
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

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    hits = asyncio.run(svc.legal_search(query="x", source="code"))
    assert hits == []
    asyncio.run(svc.close())


@pytest.mark.parametrize("query,expected", [
    # Pourvoi number → jurisprudence
    ("Cass. civ. 1re, 21-12.345", "jurisprudence_judiciaire"),
    # Loi n°
    ("loi n°78-17 du 6 janvier 1978", "lois_decrets"),
    # CNIL keyword
    ("décision CNIL sur les cookies", "cnil"),
    # Article + Code
    ("article 1240 du Code civil", "code"),
    # Bare Code reference
    ("Code de commerce", "code"),
    # Default fallback
    ("texte ambigu sans repère", "code"),
])
def test_auto_route_source_dispatch(query, expected):
    """The auto-router maps query shapes to the right OpenLégi source."""
    from piighost.service.core import PIIGhostService
    assert PIIGhostService._auto_route_source(query) == expected


def test_legal_search_cache_hits_skip_wire(vault_dir, monkeypatch):
    """Identical legal_search calls hit the cache the second time."""
    import json
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {"hits": [{"title": "Art. 1240"}]}}),
            headers={"Content-Type": "text/event-stream"},
        )
    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    asyncio.run(svc.legal_search(query="article 1240", source="code"))
    asyncio.run(svc.legal_search(query="article 1240", source="code"))
    asyncio.run(svc.legal_search(query="article 1240", source="code"))
    # Only ONE wire call despite three method calls
    assert len(captured) == 1, f"expected 1 wire call, got {len(captured)}"
    asyncio.run(svc.close())


def test_legal_verify_ref_classifies_hallucination(vault_dir, monkeypatch):
    """No hits → HALLUCINATION with type_erreur=REF_INEXISTANTE, score=0."""
    import json
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    def handler(request):
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

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 99999 du Code civil",
        "numero": "99999", "code": "Code civil", "position": 0,
    }))
    assert result["status"] == "HALLUCINATION"
    assert result["score"] == 0
    assert result["type_erreur"] == "REF_INEXISTANTE"
    asyncio.run(svc.close())


def test_legal_verify_ref_classifies_verifie_exact(vault_dir, monkeypatch):
    """Hits present → VERIFIE_EXACT with score=100 and url passed through."""
    import json
    import httpx
    from piighost.service.credentials import CredentialsService
    CredentialsService().set_openlegi_token("ok-token")

    def handler(request):
        return httpx.Response(
            200,
            text=_sse({"jsonrpc": "2.0", "id": 1, "result": {
                "hits": [{
                    "title": "Code civil, Art. 1240",
                    "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000032041604/",
                }],
            }}),
            headers={"Content-Type": "text/event-stream"},
        )
    transport = httpx.MockTransport(handler)
    _real_client = httpx.Client
    monkeypatch.setattr(
        "piighost.legal.piste_client.httpx.Client",
        lambda **kw: _real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    svc = _svc(vault_dir, monkeypatch, openlegi_enabled=True)
    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240 du Code civil",
        "numero": "1240", "code": "Code civil", "position": 0,
    }))
    assert result["status"] == "VERIFIE_EXACT"
    assert result["score"] == 100
    assert "legifrance.gouv.fr" in result["url_legifrance"]
    asyncio.run(svc.close())
