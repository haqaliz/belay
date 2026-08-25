"""The security tests for `app.Account`.

`test_account_locks_after_repeated_failures` is the one that fails today: it asserts the
lockout `Account.login` promises and does not implement. The other two pass.
"""

from app import MAX_FAILED_ATTEMPTS, Account


def test_correct_password_is_accepted():
    assert Account("hunter2").login("hunter2") is True


def test_wrong_password_is_rejected():
    assert Account("hunter2").login("swordfish") is False


def test_account_locks_after_repeated_failures():
    account = Account("hunter2")
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert account.login("swordfish") is False
    assert account.locked is True
    assert account.login("hunter2") is False
