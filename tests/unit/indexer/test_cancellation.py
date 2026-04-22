from piighost.indexer.cancellation import (
    CancellationToken,
    CancellationRegistry,
)


def test_token_is_not_cancelled_by_default():
    tok = CancellationToken()
    assert tok.is_cancelled is False


def test_cancel_sets_flag():
    tok = CancellationToken()
    tok.cancel()
    assert tok.is_cancelled is True


def test_registry_returns_same_token_for_same_project():
    reg = CancellationRegistry()
    t1 = reg.get_or_create("proj-a")
    t2 = reg.get_or_create("proj-a")
    assert t1 is t2


def test_registry_reset_replaces_token():
    reg = CancellationRegistry()
    t1 = reg.get_or_create("proj-a")
    t1.cancel()
    t2 = reg.reset("proj-a")
    assert t2 is not t1
    assert t2.is_cancelled is False
