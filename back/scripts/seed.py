"""Populate demo IMX records without creating or resetting user accounts."""
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.imx import Adherent, Debiteur, Facture, StatutContrat, StatutFacture

# (code, raison_sociale, matricule_fiscal, beneficiaire_attendu, statut)
# Dynamic non-official IMX test record supplied with the filled traite.
ADHERENTS: list[tuple[str, str, str | None, str | None, StatutContrat]] = [
    ("ADH-0142", "ADACTIM", "1330392/A/A/M/000", "SPG", StatutContrat.ACTIF),
]

# (code, raison_sociale, adresse, rib, code_adherent)
# RIB transcribed with high confidence directly from the boxed digits
# ("Code étab." 11 / "Code Agence" 003 / "N° de Compte" 0002917001788 /
# clé 36 -> 11003000291700178836), the one field on this document that's
# printed in individual boxes rather than free-hand cursive.
#
DEBITEURS: list[tuple[str, str, str | None, str, str | None]] = [
    ("DEB-0087", "LA MEDITERRANEENNE", "Lot 31, Z.I. Chotrana II, 2036 Ariana",
     "11003000291700178836", "ADH-0142"),
]

# One reconstructed facture, added per your explicit go-ahead. Unlike the
# RIB above, nothing on the document itself gives a num_facture or a
# TTC/avoirs split — only montant_ttc/montant_avoirs are chosen (8400.000 /
# 282.496) so the generated montant_net lands exactly on the traite's own
# real montant (8117.504 DT, both handwritten in lettres and boxed en
# chiffres). date_facture is set before the traite's date de création
# (2026-08-05) so "Date de création >= date de la facture rapprochée"
# evaluates true instead of staying not-applicable. num_facture is an
# supplied test identifier. The source gives statut "-", which is not a
# valid value of the non-null IMX enum; ENCOURS is the neutral active state.
FACTURES: list[tuple[str, str, str, Decimal, Decimal, date, StatutFacture]] = [
    ("FA-26-0301", "ADH-0142", "DEB-0087", Decimal("8400.000"), Decimal("282.496"),
     date(2026, 7, 28), StatutFacture.ENCOURS),
]


def run(session: Session) -> None:
    """Idempotent: safe to run against a database that's already seeded."""
    for code, raison_sociale, matricule, beneficiaire, statut in ADHERENTS:
        session.merge(
            Adherent(
                code_adherent=code,
                raison_sociale=raison_sociale,
                matricule_fiscal=matricule,
                beneficiaire_attendu=beneficiaire,
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
    print(
        f"Seeded {len(ADHERENTS)} adherents, {len(DEBITEURS)} debiteurs, "
        f"{len(FACTURES)} factures. User accounts were not modified."
    )


if __name__ == "__main__":
    main()
