"""Import every model module so ``Base.metadata`` is fully populated.

Alembic's ``env.py`` and the test suite both rely on this: importing
``app.db.models`` once is enough to register every table on
``app.db.base.Base.metadata``, which is what makes autogenerate and the
schema-inspection tests possible.
"""
from app.db.models import imx, traite  # noqa: F401
