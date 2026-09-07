"""Populate the database with example IMX-referential data.

Only ``imx.*`` tables are seeded. The app's own ``traites`` table (and
everything that hangs off it — extracted fields, NLP matches, manual
checks, decisions) is intentionally left empty: those rows are meant to be
created by the real upload -> OCR -> NLP pipeline in a later phase, not
faked ahead of time.

Two sets of rows are inserted:

1. The exact example rows from IMX's own table documentation
   (ADH-0142 / DEB-0087 / FA-26-0117) — kept byte-for-byte faithful to the
   source so anyone cross-checking against the docs finds exactly what they
   expect.
2. A fuller set matching the entities already used throughout the TRAIT-AI
   design mockup (ADACTIM, LA MÉDITERRANÉENNE, STE TEXTIS, ...), so the NLP
   reconciliation work in the next phase has real, realistic data to match
   against from day one.

Usage (inside the backend container):
    python -m scripts.seed
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.imx import Adherent, Debiteur, Facture, StatutContrat, StatutFacture

# (code, raison_sociale, matricule_fiscal, statut)
ADHERENTS: list[tuple[str, str, str | None, StatutContrat]] = [
    ("ADH-0142", "SO.CO.PAR.", None, StatutContrat.ACTIF),  # exemple documentation IMX
    ("ADH-1001", "ADACTIM", "1330392/A/A/M/000", StatutContrat.ACTIF),
    ("ADH-1002", "STE TEXTIS", None, StatutContrat.ACTIF),
    ("ADH-1003", "COMPTOIR DU SUD", None, StatutContrat.ACTIF),
    ("ADH-1004", "SARL EL FATH", None, StatutContrat.ACTIF),
    ("ADH-1005", "MEDIPLAST", None, StatutContrat.ACTIF),
    ("ADH-1006", "ETS BEN AMOR", None, StatutContrat.ACTIF),
]

# (code, raison_sociale, adresse, rib, code_adherent)
# RIBs below are fictional but structurally valid (2 + 3 + 13 + 2 = 20 digits,
# matching the reconstitution rule already used in the design mockup).
DEBITEURS: list[tuple[str, str, str | None, str, str | None]] = [
    ("DEB-0087", "LA MEDITERRANEENNE", "Lot 31, Z.I. Chotrana II, 2036 Ariana",
     "21258159852364789588", "ADH-0142"),  # exemple documentation IMX
    ("DEB-1001", "LA MÉDITERRANÉENNE", "Lot 31, Z.I, Chotrana II, 2036 Ariana",
     "11003000291700178836", "ADH-1001"),
    ("DEB-1002", "SOTUMAG", None, "10004123456789012345", "ADH-1001"),
    ("DEB-1003", "ETS GHARBI FRÈRES", None, "20011998877665544321", "ADH-1002"),
    ("DEB-1004", "SOCIÉTÉ EL AMEN", None, "08017556677889900112", "ADH-1002"),
    ("DEB-1005", "COMPTOIR NABEUL", None, "05033445566778899003", "ADH-1003"),
    ("DEB-1006", "MEDIPLAST", None, "07022334455667788994", "ADH-1004"),
    ("DEB-1007", "ETS BEN AMOR", None, "09044556677889900225", "ADH-1004"),
]

# (num_facture, code_adherent, code_debiteur, montant_ttc, montant_avoirs, date_facture, statut)
FACTURES: list[tuple[str, str, str, Decimal, Decimal, date, StatutFacture]] = [
    ("FA-26-0117", "ADH-0142", "DEB-0087", Decimal("8400.000"), Decimal("282.496"),
     date(2026, 8, 7), StatutFacture.ENCOURS),  # exemple documentation IMX — montant_net attendu: 8117.504
    ("FA-26-0203", "ADH-1001", "DEB-1001", Decimal("750.000"), Decimal("0.000"),
     date(2026, 8, 10), StatutFacture.ENCOURS),
    ("FA-26-0198", "ADH-1002", "DEB-1003", Decimal("520.000"), Decimal("20.000"),
     date(2026, 8, 5), StatutFacture.ENCOURS),
    ("FA-26-0150", "ADH-1003", "DEB-1005", Decimal("90.000"), Decimal("0.000"),
     date(2026, 8, 1), StatutFacture.PAYEE),
]


def run(session: Session) -> None:
    """Idempotent: safe to run against a database that's already seeded."""
    for code, raison_sociale, matricule, statut in ADHERENTS:
        session.merge(
            Adherent(
                code_adherent=code,
                raison_sociale=raison_sociale,
                matricule_fiscal=matricule,
                statut_contrat=statut,
            )
        )

    for code, raison_sociale, adresse, rib, code_adherent in DEBITEURS:
        session.merge(
            Debiteur(
                code_debiteur=code,
                raison_sociale=raison_sociale,
                adresse=adresse,
                rib=rib,
                code_adherent=code_adherent,
            )
        )

    for num, code_adherent, code_debiteur, ttc, avoirs, date_facture, statut in FACTURES:
        session.merge(
            Facture(
                num_facture=num,
                code_adherent=code_adherent,
                code_debiteur=code_debiteur,
                montant_ttc=ttc,
                montant_avoirs=avoirs,
                date_facture=date_facture,
                statut=statut,
            )
        )

    session.commit()


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    with Session(engine) as session:
        run(session)
    print(f"Seeded {len(ADHERENTS)} adherents, {len(DEBITEURS)} debiteurs, {len(FACTURES)} factures.")


if __name__ == "__main__":
    main()
