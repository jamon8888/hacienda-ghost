"""Verify compliance package uses lazy submodule imports.

Importing piighost.compliance + reading load_bundled_profile must NOT
pull pydantic or piighost.compliance.render into sys.modules. Phase 5
followup #1.
"""
from __future__ import annotations

import sys


def test_loading_only_profile_loader_does_not_import_render(monkeypatch):
    """from piighost.compliance import load_bundled_profile should not
    transitively import compliance.render."""
    # Drop any cached state so we measure cold-import cost
    for mod in list(sys.modules):
        if mod.startswith("piighost.compliance"):
            del sys.modules[mod]

    # Now do the lean import
    from piighost.compliance import load_bundled_profile  # noqa: F401

    # render must NOT be loaded yet
    assert "piighost.compliance.render" not in sys.modules, (
        "compliance.render was eagerly imported — lazy __getattr__ broken"
    )
    # processing_register must NOT be loaded yet
    assert "piighost.compliance.processing_register" not in sys.modules, (
        "compliance.processing_register was eagerly imported"
    )


def test_accessing_render_loads_it_on_demand():
    """Touching compliance.render_compliance_doc DOES load render submodule."""
    for mod in list(sys.modules):
        if mod.startswith("piighost.compliance"):
            del sys.modules[mod]

    import piighost.compliance as cmp
    assert "piighost.compliance.render" not in sys.modules

    # Force the lazy load
    fn = cmp.render_compliance_doc
    assert callable(fn)
    assert "piighost.compliance.render" in sys.modules


def test_dunder_all_unchanged():
    """__all__ stays the same shape — only the import strategy changes."""
    import piighost.compliance as cmp
    assert set(cmp.__all__) == {
        "build_processing_register",
        "screen_dpia",
        "render_compliance_doc",
        "load_bundled_profile",
    }


def test_unknown_attribute_raises_attribute_error():
    import piighost.compliance as cmp
    try:
        _ = cmp.nonexistent_function
    except AttributeError as exc:
        assert "nonexistent_function" in str(exc)
    else:
        raise AssertionError("AttributeError not raised")
