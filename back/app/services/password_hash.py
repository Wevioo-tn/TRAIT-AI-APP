"""Password hashing for local users (app/db/models/user.py) — Argon2id via
``argon2-cffi``, OWASP's current default recommendation for new
applications (memory-hard, resistant to GPU/ASIC cracking, no known
practical break). Replaces the earlier LDAP bind, where this app never
touched a password at all beyond forwarding it to the directory — now that
this app *is* the identity store, hashing it correctly is this module's
one job.

Never store, log, or compare a plain-text password anywhere outside this
module.
"""
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

# A hash of a value nobody will ever type, used to burn the same amount of
# time verifying an unknown username as a real one — see local_auth.py's
# authenticate() for why: without this, a real Argon2 verify only running
# when the username exists is a timing side-channel that leaks exactly the
# same "does this user exist" fact the identical 401 message is meant to
# hide.
_DUMMY_HASH = _hasher.hash("not-a-real-password-only-used-for-constant-time-verification")


def hash_password(password: str) -> str:
    """Returns an encoded Argon2id hash — algorithm, salt, and parameters
    are all embedded in the string, so no separate salt column is needed."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def verify_dummy_password(password: str) -> None:
    """Called instead of verify_password() when the username doesn't
    exist, so a login attempt against an unknown user takes about as long
    as one against a real user with the wrong password."""
    try:
        _hasher.verify(_DUMMY_HASH, password)
    except VerifyMismatchError:
        pass
