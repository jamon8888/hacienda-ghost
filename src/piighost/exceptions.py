"""PIIGhost exception hierarchy."""


class PIIGhostException(Exception):
    """Base exception for all PIIGhost errors."""


class CacheMissError(PIIGhostException):
    """Raised when a cache lookup finds no entry for the given key."""


class DeanonymizationError(PIIGhostException):
    """Raised when a token cannot be found during deanonymization."""

    def __init__(self, message: str, partial_text: str) -> None:
        super().__init__(message)
        self.partial_text = partial_text


class RehydrationError(DeanonymizationError):
    """Raised when a document's anonymization mapping is missing or malformed.

    Subclass of DeanonymizationError because rehydration is semantically
    a deanonymization step, just driven from Document.meta rather than
    from the pipeline cache.
    """


class VaultNotFound(Exception):
    """No `.piighost/` found in cwd or any ancestor directory."""


class VaultSchemaMismatch(Exception):
    """Vault database schema version does not match the current code."""


class PIISafetyViolation(Exception):
    """An operation would violate a PII-safety invariant (e.g. unknown rehydrate token in strict mode)."""


class DaemonUnreachable(Exception):
    """Daemon is configured but not reachable; CLI may auto-spawn."""


class ProjectNotFound(LookupError):
    """Raised when a project name is passed to a read operation but does not exist."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"project '{name}' does not exist; call list_projects to see available projects"
        )
        self.name = name


class ProjectNotEmpty(RuntimeError):
    """Raised when delete_project is called on a non-empty project without force=True."""

    def __init__(self, name: str, doc_count: int, vault_count: int) -> None:
        super().__init__(
            f"project '{name}' contains {doc_count} docs and {vault_count} vault entries; "
            f"pass force=True to delete anyway"
        )
        self.name = name
        self.doc_count = doc_count
        self.vault_count = vault_count
