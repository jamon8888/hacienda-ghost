"""Cross-platform tests for service restart policies.

The platform-specific test files (test_service_linux.py, test_service_darwin.py,
test_service_windows.py) skip on the wrong OS, so they don't validate generated
content on a developer's local machine. This file calls the content-generation
helpers directly — they're pure string functions and have no OS dependency —
so the rules stay enforced regardless of where the tests run.
"""
from __future__ import annotations

from pathlib import Path

from piighost.install.service import ServiceSpec
from piighost.install.service import darwin as darwin_mod
from piighost.install.service import linux as linux_mod


def _spec(tmp_path: Path) -> ServiceSpec:
    return ServiceSpec(
        name="piighost-proxy",
        bin_path="/usr/local/bin/piighost",
        vault_dir=tmp_path / ".piighost",
        cert_path=tmp_path / "leaf.pem",
        key_path=tmp_path / "leaf.key",
        port=443,
        user="alice",
    )


def test_linux_unit_has_robust_restart_policy(tmp_path: Path) -> None:
    """systemd unit must self-heal from any exit, with rate limit."""
    content = linux_mod._unit_content(_spec(tmp_path))
    assert "Restart=always" in content
    assert "RestartSec=" in content
    assert "StartLimitBurst=" in content
    assert "StartLimitIntervalSec=" in content


def test_macos_plist_has_keepalive_and_throttle(tmp_path: Path) -> None:
    """launchd plist must KeepAlive with a throttle to avoid crash-loop hammering."""
    content = darwin_mod._plist_content(_spec(tmp_path))
    assert "<key>KeepAlive</key>" in content
    assert "<key>ThrottleInterval</key>" in content
    assert "<key>ExitTimeOut</key>" in content
