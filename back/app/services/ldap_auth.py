"""LDAP authentication — "Authentification par annuaire interne", the
design's own login copy, implemented for real against a real (in dev, a
throwaway seeded OpenLDAP container) directory.

The correct way to verify a directory password is to attempt a bind as
that user and see if it succeeds — never read, cache, or compare a
password yourself. A failed bind (wrong password, unknown user, or the
directory being unreachable) is reported the same way to the caller: as
"authentication failed". That's deliberate — distinguishing "wrong
password" from "unknown user" in the response would let an attacker
enumerate valid usernames.
"""
import ldap3

from app.core.config import get_settings


def authenticate(username: str, password: str) -> bool:
    if not username or not password:
        return False

    settings = get_settings()
    user_dn = settings.ldap_user_dn_template.format(username=username)
    server = ldap3.Server(settings.ldap_url)

    try:
        connection = ldap3.Connection(server, user=user_dn, password=password, auto_bind=True)
    except ldap3.core.exceptions.LDAPException:
        return False

    connection.unbind()
    return True
