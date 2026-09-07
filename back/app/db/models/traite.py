"""Tables owned by this application.

Each table maps directly onto one section of the TRAIT-AI design: the queue
list's status column, the "Contrôle de cohérence des champs dupliqués"
table, the "Rapprochement NLP" panel, the manual-verification checklist, and
the cashier's final decision. "Mentions obligatoires" and the date-rule
checks are intentionally *not* separate tables: both are derived at read
time from ``ChampExtrait`` / ``VerificationManuelle`` plus the linked
``imx.Facture``, so the same fact is never stored twice.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.models.imx import Adherent, Debiteur


class TraiteStatut(str, enum.Enum):
    A_TRAITER = "À traiter"
    EN_COURS_OCR = "En cours OCR"
    ECARTS_A_TRAITER = "Écarts à traiter"
    CONTROLE_MANUEL_REQUIS = "Contrôle manuel requis"
    RENVOYEE = "Renvoyée"
    FRAUDE_SIGNALEE = "Fraude signalée"
    VALIDEE = "Validée"


class Face(str, enum.Enum):
    RECTO = "recto"
    VERSO = "verso"


class SourceChamp(str, enum.Enum):
    OCR = "ocr"
    NLP = "nlp"
    MANUEL = "manuel"


class RoleNlp(str, enum.Enum):
    TIREUR = "tireur"
    TIRE = "tire"
    ORDRE = "ordre"


class VerificationCode(str, enum.Enum):
    SIG_TIRE = "sigTire"
    ACCEPT = "accept"
    SIG_TIREUR = "sigTireur"
    ENDOS = "endos"


class StatutVerification(str, enum.Enum):
    CONFORME = "conforme"
    ANOMALIE = "anomalie"


class TypeDecision(str, enum.Enum):
    VALIDEE = "validee"
    RENVOI = "renvoi"
    FRAUDE = "fraude"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


class Traite(Base):
    __tablename__ = "traites"

    id: Mapped[uuid.UUID] = _uuid_pk()
    numero_lcn: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    montant: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    date_echeance: Mapped[date] = mapped_column(Date, nullable=False)
    date_creation_traite: Mapped[date] = mapped_column(Date, nullable=False)
    date_reception: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    statut: Mapped[TraiteStatut] = mapped_column(
        SAEnum(TraiteStatut, name="traite_statut"),
        nullable=False,
        default=TraiteStatut.A_TRAITER,
    )
    # Resolved once the NLP reconciliation confirms the match — null until then.
    code_adherent: Mapped[str | None] = mapped_column(ForeignKey(Adherent.code_adherent))
    code_debiteur: Mapped[str | None] = mapped_column(ForeignKey(Debiteur.code_debiteur))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Read-only: resolved counterparty, once NLP matching has run. No
    # back_populates — Adherent/Debiteur don't need a reverse list of every
    # traite drawn on them for anything built so far.
    adherent: Mapped[Adherent | None] = relationship(viewonly=True)
    debiteur: Mapped[Debiteur | None] = relationship(viewonly=True)

    documents: Mapped[list["TraiteDocument"]] = relationship(back_populates="traite", cascade="all, delete-orphan")
    champs_extraits: Mapped[list["ChampExtrait"]] = relationship(back_populates="traite", cascade="all, delete-orphan")
    rapprochements_nlp: Mapped[list["RapprochementNlp"]] = relationship(
        back_populates="traite", cascade="all, delete-orphan"
    )
    verifications_manuelles: Mapped[list["VerificationManuelle"]] = relationship(
        back_populates="traite", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(back_populates="traite", cascade="all, delete-orphan")
    audit_entries: Mapped[list["AuditLogEntry"]] = relationship(back_populates="traite")

    @property
    def tireur_nom(self) -> str | None:
        """Display name for the queue list. Requires ``adherent`` to be
        eager-loaded (selectinload) — this is a plain Python property, so
        touching it on a lazy, un-loaded relationship inside an async
        request would raise, not silently N+1 query."""
        return self.adherent.raison_sociale if self.adherent else None

    @property
    def tire_nom(self) -> str | None:
        return self.debiteur.raison_sociale if self.debiteur else None


class TraiteDocument(Base):
    """The recto / verso scan uploaded for a traite."""

    __tablename__ = "traite_documents"
    __table_args__ = (UniqueConstraint("traite_id", "face", name="uq_traite_documents_traite_face"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    traite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("traites.id"), nullable=False)
    face: Mapped[Face] = mapped_column(SAEnum(Face, name="face"), nullable=False)
    fichier_nom: Mapped[str] = mapped_column(String(255), nullable=False)
    fichier_chemin: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    taille_octets: Mapped[int] = mapped_column(nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    traite: Mapped[Traite] = relationship(back_populates="documents")


class ChampExtrait(Base):
    """One row of the duplicated-fields coherence check."""

    __tablename__ = "champs_extraits"

    id: Mapped[uuid.UUID] = _uuid_pk()
    traite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("traites.id"), nullable=False)
    nom_champ: Mapped[str] = mapped_column(String(100), nullable=False)
    occurrence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Null = the box was empty on the scan.
    valeur: Mapped[str | None] = mapped_column(Text)
    source: Mapped[SourceChamp] = mapped_column(
        SAEnum(SourceChamp, name="source_champ"), nullable=False, default=SourceChamp.OCR
    )
    confiance: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    traite: Mapped[Traite] = relationship(back_populates="champs_extraits")


class RapprochementNlp(Base):
    """One row of the NLP reconciliation against the IMX referential."""

    __tablename__ = "rapprochements_nlp"

    id: Mapped[uuid.UUID] = _uuid_pk()
    traite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("traites.id"), nullable=False)
    role: Mapped[RoleNlp] = mapped_column(SAEnum(RoleNlp, name="role_nlp"), nullable=False)
    valeur_scan: Mapped[str] = mapped_column(Text, nullable=False)
    valeur_referentiel: Mapped[str | None] = mapped_column(Text)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    code_adherent_matche: Mapped[str | None] = mapped_column(ForeignKey(Adherent.code_adherent))
    code_debiteur_matche: Mapped[str | None] = mapped_column(ForeignKey(Debiteur.code_debiteur))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    traite: Mapped[Traite] = relationship(back_populates="rapprochements_nlp")


class VerificationManuelle(Base):
    """One of the 4 mandatory human-control zones (signatures, stamps, endorsement)."""

    __tablename__ = "verifications_manuelles"
    __table_args__ = (
        UniqueConstraint("traite_id", "code_verification", name="uq_verif_manuelle_traite_code"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    traite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("traites.id"), nullable=False)
    code_verification: Mapped[VerificationCode] = mapped_column(
        SAEnum(VerificationCode, name="verification_code"), nullable=False
    )
    # Null = not yet decided.
    statut: Mapped[StatutVerification | None] = mapped_column(SAEnum(StatutVerification, name="statut_verification"))
    verifie_par: Mapped[str | None] = mapped_column(String(120))
    verifie_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    traite: Mapped[Traite] = relationship(back_populates="verifications_manuelles")


class Decision(Base):
    """The cashier's final decision for a traite."""

    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    traite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("traites.id"), nullable=False)
    type: Mapped[TypeDecision] = mapped_column(SAEnum(TypeDecision, name="type_decision"), nullable=False)
    commentaire: Mapped[str | None] = mapped_column(Text)
    decide_par: Mapped[str] = mapped_column(String(120), nullable=False)
    decide_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    traite: Mapped[Traite] = relationship(back_populates="decisions")


class AuditLogEntry(Base):
    """Audit trail — every action is timestamped and traced."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Nullable: some entries (login, logout) aren't attached to any traite.
    traite_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("traites.id"))
    utilisateur: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)
    horodatage: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    traite: Mapped[Traite | None] = relationship(back_populates="audit_entries")
