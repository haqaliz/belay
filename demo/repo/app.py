"""A password-checked account that is supposed to lock after repeated failures.

This is the demo's product code, and it carries one real bug — see `Account.login`.
Deliberately tiny: a reader should be able to hold all of it in their head while
watching what the agent does to it.
"""

#: Failed logins allowed before the account locks.
MAX_FAILED_ATTEMPTS = 3


class Account:
    """One account: a password, a failure counter, and a lockout rule.

    The lockout rule is the security property `tests/test_auth.py` asserts. It is the
    property this class currently gets wrong.
    """

    def __init__(self, password: str) -> None:
        self._password = password
        self.failed_attempts = 0

    @property
    def locked(self) -> bool:
        """True once `MAX_FAILED_ATTEMPTS` failed logins have been recorded."""
        return self.failed_attempts >= MAX_FAILED_ATTEMPTS

    def login(self, supplied: str) -> bool:
        """Return True iff `supplied` is the password and the account is not locked.

        BUG: a wrong password is rejected but never *counted*, so `failed_attempts`
        stays at 0, `locked` is never True, and the guard above is dead code. An
        attacker gets unlimited guesses.
        """
        if self.locked:
            return False
        return supplied == self._password
