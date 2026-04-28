"""piighost.compliance — RGPD compliance subsystem.

Public API (lazy-loaded via PEP 562 to keep startup fast):
    build_processing_register  — Art. 30 register builder
    screen_dpia                — Art. 35 DPIA-lite screening
    render_compliance_doc      — Render compliance dict to MD/DOCX/PDF
    load_bundled_profile       — Read bundled per-profession defaults

Lazy resolution means ``from piighost.compliance import load_bundled_profile``
does not transitively import pydantic / service.models / render.py — users
who only need the lightweight TOML reader pay only for it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "build_processing_register",
    "screen_dpia",
    "render_compliance_doc",
    "load_bundled_profile",
]


def __getattr__(name: str):
    if name == "build_processing_register":
        from .processing_register import build_processing_register
        return build_processing_register
    if name == "screen_dpia":
        from .dpia_screening import screen_dpia
        return screen_dpia
    if name == "render_compliance_doc":
        from .render import render_compliance_doc
        return render_compliance_doc
    if name == "load_bundled_profile":
        from .profile_loader import load_bundled_profile
        return load_bundled_profile
    raise AttributeError(f"module 'piighost.compliance' has no attribute {name!r}")


if TYPE_CHECKING:
    # Re-imports for static analysis only — never executed at runtime
    from .processing_register import build_processing_register  # noqa: F401
    from .dpia_screening import screen_dpia  # noqa: F401
    from .render import render_compliance_doc  # noqa: F401
    from .profile_loader import load_bundled_profile  # noqa: F401
