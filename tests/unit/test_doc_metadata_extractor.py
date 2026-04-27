"""Tests for build_metadata + pick_doc_date + dossier_id extraction."""
from __future__ import annotations

from pathlib import Path

from piighost.models import Detection, Span
from piighost.service.doc_metadata_extractor import (
    build_metadata,
    pick_doc_date,
    _extract_dossier_id,
    _parse_iso_to_epoch,
)


def _det(
    text: str,
    label: str,
    start: int = 0,
    end: int = 0,
    confidence: float = 0.9,
) -> Detection:
    return Detection(
        text=text,
        label=label,
        position=Span(start_pos=start, end_pos=end or len(text)),
        confidence=confidence,
    )


def test_pick_doc_date_prefers_kreuzberg_creation():
    meta = {"created_at": "2026-04-15T10:30:00Z"}
    epoch, source = pick_doc_date(meta, content="", detections=[])
    assert source == "kreuzberg_creation"
    assert epoch == _parse_iso_to_epoch("2026-04-15T10:30:00Z")


def test_pick_doc_date_falls_back_to_modified():
    meta = {"modified_at": "2026-04-10T08:00:00Z"}
    epoch, source = pick_doc_date(meta, content="", detections=[])
    assert source == "kreuzberg_modified"
    assert epoch is not None


def test_pick_doc_date_returns_none_when_nothing_works():
    epoch, source = pick_doc_date({}, content="no dates here", detections=[])
    assert epoch is None
    assert source == "none"


def test_extract_dossier_id_first_subfolder(tmp_path):
    project_root = tmp_path / "cabinet"
    project_root.mkdir()
    (project_root / "client_acme").mkdir()
    (project_root / "client_acme" / "contracts").mkdir()
    file_path = project_root / "client_acme" / "contracts" / "foo.pdf"
    file_path.write_text("x")
    assert _extract_dossier_id(file_path, project_root) == "client_acme"


def test_extract_dossier_id_root_file_returns_empty(tmp_path):
    project_root = tmp_path / "cabinet"
    project_root.mkdir()
    file_path = project_root / "foo.pdf"
    file_path.write_text("x")
    assert _extract_dossier_id(file_path, project_root) == ""


def test_build_metadata_uses_kreuzberg_title_and_authors(tmp_path):
    project_root = tmp_path / "cabinet"
    project_root.mkdir()
    (project_root / "client1").mkdir()
    fp = project_root / "client1" / "contract.pdf"
    fp.write_text("x")

    meta = build_metadata(
        doc_id="abc123",
        file_path=fp,
        project_root=project_root,
        content="Article 1 - Objet du contrat",
        kreuzberg_meta={
            "title": "Service Agreement 2026",
            "authors": ["Jean Martin"],
            "format_type": "pdf",
            "page_count": 5,
            "language": "fr",
            "created_at": "2026-04-15T10:00:00Z",
        },
        detections=[],
    )
    assert meta.doc_title == "Service Agreement 2026"
    assert meta.doc_authors == ["Jean Martin"]
    assert meta.doc_format == "pdf"
    assert meta.doc_page_count == 5
    assert meta.doc_language == "fr"
    assert meta.doc_date_source == "kreuzberg_creation"
    assert meta.doc_type == "contrat"  # filename "contract.pdf" matches
    assert meta.dossier_id == "client1"


def test_build_metadata_with_pii_detections_populates_parties(tmp_path):
    project_root = tmp_path / "cabinet"
    project_root.mkdir()
    (project_root / "client1").mkdir()
    fp = project_root / "client1" / "note.txt"
    fp.write_text("x")

    meta = build_metadata(
        doc_id="abc",
        file_path=fp,
        project_root=project_root,
        content="Marie Dupont travaille chez Acme.",
        kreuzberg_meta={},
        detections=[
            _det("Marie Dupont", "nom_personne", 0, 12),
            _det("Acme", "organisation", 27, 31),
            _det("2026-04-15", "date", 35, 45),  # not a party
        ],
    )
    assert len(meta.parties) == 2
    # Parties contain stable identifiers computed with the same scheme
    # as LabelHashPlaceholderFactory: <<label:sha256(text.lower():label)[:8]>>
    for p in meta.parties:
        assert isinstance(p, str)
    # Ensure the date detection didn't leak into parties
    assert not any("date" in p for p in meta.parties)


def test_build_metadata_handles_encrypted_pdf(tmp_path):
    project_root = tmp_path / "p"
    project_root.mkdir()
    fp = project_root / "encrypted.pdf"
    fp.write_text("x")

    meta = build_metadata(
        doc_id="abc",
        file_path=fp,
        project_root=project_root,
        content="",
        kreuzberg_meta={"is_encrypted": True, "format_type": "pdf"},
        detections=[],
    )
    assert meta.is_encrypted_source is True
    assert meta.doc_format == "pdf"


def test_parse_iso_to_epoch_round_trip():
    iso = "2026-04-15T10:30:00Z"
    epoch = _parse_iso_to_epoch(iso)
    # 2026-04-15T10:30:00 UTC
    assert epoch == 1776249000


def test_parse_iso_to_epoch_returns_none_on_garbage():
    assert _parse_iso_to_epoch("not a date") is None
    assert _parse_iso_to_epoch("") is None
    assert _parse_iso_to_epoch(None) is None  # type: ignore[arg-type]


def test_build_metadata_dedups_same_label_same_text(tmp_path):
    """Same person mentioned twice → one entry in parties."""
    project_root = tmp_path / "p"
    project_root.mkdir()
    fp = project_root / "note.txt"
    fp.write_text("x")
    meta = build_metadata(
        doc_id="abc",
        file_path=fp,
        project_root=project_root,
        content="Marie Dupont. Et encore Marie Dupont.",
        kreuzberg_meta={},
        detections=[
            _det("Marie Dupont", "nom_personne", 0, 12),
            _det("Marie Dupont", "nom_personne", 22, 34),
        ],
    )
    assert len(meta.parties) == 1


def test_party_token_matches_LabelHashPlaceholderFactory():
    """Cross-validation: build_metadata's party token MUST match the
    canonical placeholder factory output. If these diverge silently,
    Phase 1 subject_clustering breaks because the tokens in
    documents_meta.parties won't match those in vault.entities.
    """
    from piighost.service.doc_metadata_extractor import _party_token
    from piighost.placeholder import LabelHashPlaceholderFactory
    from piighost.models import Detection, Entity, Span

    factory = LabelHashPlaceholderFactory()

    test_cases = [
        ("Marie Dupont", "nom_personne"),
        ("acme.fr", "email"),
        ("Acme Corporation", "organisation"),
        ("Jean", "prenom"),
    ]
    for text, label in test_cases:
        local = _party_token(text, label)
        det = Detection(
            text=text, label=label,
            position=Span(start_pos=0, end_pos=len(text)),
            confidence=1.0,
        )
        entity = Entity(detections=(det,))
        canonical = factory.create([entity])[entity]
        assert local == canonical, (
            f"Token divergence for ({text!r}, {label!r}): "
            f"_party_token={local!r} factory={canonical!r}"
        )
