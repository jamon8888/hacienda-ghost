"""Verify the piighost.compliance public API re-exports."""
from __future__ import annotations


def test_compliance_top_level_reexports():
    """Programmatic callers should import from piighost.compliance directly."""
    from piighost.compliance import (
        build_processing_register,
        screen_dpia,
        render_compliance_doc,
        load_bundled_profile,
    )

    assert callable(build_processing_register)
    assert callable(screen_dpia)
    assert callable(render_compliance_doc)
    assert callable(load_bundled_profile)


def test_compliance_dunder_all_is_complete():
    import piighost.compliance as cmp

    expected = {
        "build_processing_register",
        "screen_dpia",
        "render_compliance_doc",
        "load_bundled_profile",
    }
    assert set(cmp.__all__) == expected
