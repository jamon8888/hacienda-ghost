"""piighost.compliance — RGPD compliance subsystem.

Public API:
    build_processing_register  — Art. 30 register builder
    screen_dpia                — Art. 35 DPIA-lite screening
    render_compliance_doc      — Render compliance dict to MD/DOCX/PDF
    load_bundled_profile       — Read bundled per-profession defaults
"""
from .processing_register import build_processing_register
from .dpia_screening import screen_dpia
from .render import render_compliance_doc
from .profile_loader import load_bundled_profile

__all__ = [
    "build_processing_register",
    "screen_dpia",
    "render_compliance_doc",
    "load_bundled_profile",
]
