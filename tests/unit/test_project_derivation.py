from pathlib import Path

from piighost.service.project_path import derive_project_from_path


def test_extracts_project_from_typical_layout():
    # /Users/x/projects/client-a/contracts/ -> client-a
    assert derive_project_from_path(Path("/Users/alice/projects/client-a/contracts")) == "client-a"


def test_skips_generic_names():
    assert derive_project_from_path(Path("/Users/alice/Documents/client-a/docs")) == "client-a"
    assert derive_project_from_path(Path("/home/bob/src/client-b/data")) == "client-b"


def test_single_generic_path_falls_back_to_default():
    assert derive_project_from_path(Path("/tmp")) == "default"


def test_invalid_chars_fall_back_to_default():
    # All intermediate components are either generic (tmp) or invalid (space in name),
    # so there's no valid candidate -> returns "default".
    assert derive_project_from_path(Path("/tmp/my client/docs")) == "default"


def test_empty_path_falls_back_to_default():
    assert derive_project_from_path(Path("/")) == "default"


def test_relative_path_resolves_first():
    result = derive_project_from_path(Path("."))
    assert result
