"""Argon2 password hashing (app/services/password_hash.py) — pure unit
tests, no DB, no network."""
from app.services.password_hash import hash_password, verify_dummy_password, verify_password


def test_hash_password_produces_a_verifiable_hash():
    hashed = hash_password("correct horse battery staple")
    assert verify_password(hashed, "correct horse battery staple") is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password(hashed, "wrong password") is False


def test_hash_password_never_stores_the_plain_text():
    hashed = hash_password("correct horse battery staple")
    assert "correct horse battery staple" not in hashed


def test_hash_password_salts_differently_each_call():
    """Same password, two calls -> two different hashes — proves a real
    per-call salt is used, not a fixed/deterministic transform."""
    first = hash_password("same password")
    second = hash_password("same password")
    assert first != second
    assert verify_password(first, "same password") is True
    assert verify_password(second, "same password") is True


def test_verify_dummy_password_never_raises():
    """Exercised by local_auth.authenticate() on an unknown username, to
    keep response timing similar to a real user's wrong-password path —
    must never itself raise, for any input."""
    verify_dummy_password("")
    verify_dummy_password("anything at all")
