"""Local stand-in for the external IMX referential.

Shape and column names are taken directly from IMX's own documentation
(ADHERENTS / DEBITEURS / FACTURES tables). In production the app connects
read-only to the real IMX database instead of this schema — see
``README.md`` for the integration note — but the structure here is kept
identical so that switching over later is a connection-string change, not a
data-model change.
"""
import enum
from datetime import date

from sqlalchemy import Computed, Date, ForeignKey, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

IMX_SCHEMA = "imx"


class StatutContrat(str, enum.Enum):
    ACTIF = "Actif"
    RESILIE = "Résilié"
    SUSPENDU = "Suspendu"


class StatutFacture(str, enum.Enum):
    ENCOURS = "Encours"
    PAYEE = "Payée"
    ANNULEE = "Annulée"


class Adherent(Base):
    """ADHERENTS — correspond au Tireur."""

    __tablename__ = "adherents"
    __table_args__ = {"schema": IMX_SCHEMA}

    code_adherent: Mapped[str] = mapped_column(String(20), primary_key=True)
    raison_sociale: Mapped[str] = mapped_column(String(255), nullable=False)
    matricule_fiscal: Mapped[str | None] = mapped_column(String(50))
    # Contractual beneficiary expected in "Payer à l'ordre de". Nullable
    # because the provisional IMX extracts may omit contract details.
    beneficiaire_attendu: Mapped[str | None] = mapped_column(String(255))
    statut_contrat: Mapped[StatutContrat] = mapped_column(
        SAEnum(StatutContrat, name="statut_contrat", schema=IMX_SCHEMA),
        nullable=False,
        default=StatutContrat.ACTIF,
    )

    debiteurs: Mapped[list["Debiteur"]] = relationship(back_populates="adherent")
    factures: Mapped[list["Facture"]] = relationship(back_populates="adherent")


class Debiteur(Base):
    """DEBITEURS — correspond au Tiré."""

    __tablename__ = "debiteurs"
    __table_args__ = {"schema": IMX_SCHEMA}

    code_debiteur: Mapped[str] = mapped_column(String(20), primary_key=True)
    raison_sociale: Mapped[str] = mapped_column(String(255), nullable=False)
    adresse: Mapped[str | None] = mapped_column(Text)
    rib: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    # Nullable: only needed when a débiteur can carry invoices from several
    # adhérents; otherwise the adhérent/débiteur link is made via FACTURES.
    code_adherent: Mapped[str | None] = mapped_column(
        ForeignKey(f"{IMX_SCHEMA}.adherents.code_adherent")
    )

    adherent: Mapped[Adherent | None] = relationship(back_populates="debiteurs")
    factures: Mapped[list["Facture"]] = relationship(back_populates="debiteur")


class Facture(Base):
    """FACTURES — sert au calcul de couverture et au contrôle avance/facture."""

    __tablename__ = "factures"
    __table_args__ = {"schema": IMX_SCHEMA}

    num_facture: Mapped[str] = mapped_column(String(30), primary_key=True)
    code_adherent: Mapped[str] = mapped_column(
        ForeignKey(f"{IMX_SCHEMA}.adherents.code_adherent"), nullable=False
    )
    code_debiteur: Mapped[str] = mapped_column(
        ForeignKey(f"{IMX_SCHEMA}.debiteurs.code_debiteur"), nullable=False
    )
    montant_ttc: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    montant_avoirs: Mapped[float] = mapped_column(
        Numeric(14, 3), nullable=False, server_default="0"
    )
    # Generated column: single source of truth for "TTC - avoirs", exactly
    # the value compared against the traite's montant during reconciliation.
    montant_net: Mapped[float] = mapped_column(
        Numeric(14, 3),
        Computed("montant_ttc - montant_avoirs", persisted=True),
        nullable=False,
    )
    date_facture: Mapped[date] = mapped_column(Date, nullable=False)
    statut: Mapped[StatutFacture] = mapped_column(
        SAEnum(StatutFacture, name="statut_facture", schema=IMX_SCHEMA),
        nullable=False,
        default=StatutFacture.ENCOURS,
    )

    adherent: Mapped[Adherent] = relationship(back_populates="factures")
    debiteur: Mapped[Debiteur] = relationship(back_populates="factures")
