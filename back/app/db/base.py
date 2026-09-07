"""Declarative base shared by every ORM model in the project.

Two logical schemas live in the same Postgres database:

- ``imx``    — a local stand-in for the real IMX referential (ADHERENTS /
               DEBITEURS / FACTURES). In production this data is owned by the
               external IMX system; here it exists so the app can be built
               and tested against a realistic, faithful copy of its shape
               before the real integration (direct DB link, per the
               validated architecture decision) is wired up.
- (default)  — tables owned by this application: traites, extracted fields,
               manual verifications, decisions, audit log.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
