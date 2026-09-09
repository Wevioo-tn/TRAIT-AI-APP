"""Pydantic schemas for the Traites API.

Read schemas mirror the ORM models field-for-field (``from_attributes``) so
a SQLAlchemy instance can be returned directly from a route. Nested-relation
schemas for champs_extraits/rapprochements_nlp are included from the start,
even though nothing populates them until the OCR/NLP pipeline (Sprint 4)
exists, so the API contract doesn't change shape out from under the
frontend later.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.traite import (
    Face,
    MethodeIdentification,
    RoleNlp,
    SourceChamp,
    StatutVerification,
    TraiteStatut,
    TypeDecision,
    VerificationCode,
)


class TraiteCreate(BaseModel):
    """All four fields are optional: the queue screen no longer collects a
    bordereau-declared intake (per your call) and creates a traite from
    just the recto/verso scans. Any field left out is generated server-side
    (see create_traite in routes/traites.py) rather than rejected — but a
    field that *is* provided must still be well-formed (a real client that
    does have bordereau data, e.g. a future API integration, still gets
    the original validation)."""

    numero_lcn: str | None = Field(default=None, min_length=1, max_length=20)
    montant: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    date_echeance: date | None = None
    date_creation_traite: date | None = None

    @field_validator("numero_lcn", "montant", "date_echeance", "date_creation_traite", mode="before")
    @classmethod
    def _blank_string_means_not_provided(cls, value: object) -> object:
        """A client sending explicit empty strings (e.g. an untouched HTML
        form serialized as-is, rather than omitting the keys) means the
        same thing here as omitting them entirely — both fall through to
        create_traite's server-side generation, not a 422."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class VerificationUpdate(BaseModel):
    # Explicit null (or omitted) resets the zone back to "not yet statué" —
    # mirrors the mockup's toggle behaviour (clicking the active button again
    # clears it).
    statut: StatutVerification | None = None


class DecisionCreate(BaseModel):
    type: TypeDecision
    commentaire: str | None = Field(default=None, max_length=4000)


class MontantAvoirsUpdate(BaseModel):
    # null (or omitted) clears a previous saisie — same "toggle" semantics
    # as VerificationUpdate.statut. ge=0: an avoir can't be negative; 0
    # itself is a legitimate saisie ("no avoir applicable"), distinct from
    # null ("not yet saisi").
    montant_avoirs: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)


class TraiteDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    face: Face
    fichier_nom: str
    content_type: str
    taille_octets: int
    uploaded_at: datetime


class ChampExtraitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom_champ: str
    occurrence: int
    valeur: str | None
    source: SourceChamp
    confiance: Decimal | None


class RapprochementNlpRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: RoleNlp
    valeur_scan: str
    valeur_referentiel: str | None
    score: Decimal
    code_adherent_matche: str | None
    code_debiteur_matche: str | None
    methode_identification: MethodeIdentification
    alerte_ecart_nom: bool


class VerificationManuelleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code_verification: VerificationCode
    statut: StatutVerification | None
    verifie_par: str | None
    verifie_le: datetime | None


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: TypeDecision
    commentaire: str | None
    decide_par: str
    decide_le: datetime


class TraiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero_lcn: str
    montant: Decimal
    date_echeance: date
    date_creation_traite: date
    date_reception: datetime
    statut: TraiteStatut
    code_adherent: str | None
    code_debiteur: str | None
    # Resolved display names — null until NLP matching has run (see the
    # Traite.tireur_nom / tire_nom properties this reads from).
    tireur_nom: str | None
    tire_nom: str | None
    created_at: datetime
    updated_at: datetime


class RecommandationRead(BaseModel):
    titre: str
    detail: str


class MentionRead(BaseModel):
    code: str
    label: str
    valeur: str | None
    statut: str  # "ok" | "warn" | "absent"


class RegleDateRead(BaseModel):
    label: str
    valeur_a: str | None
    valeur_b: str | None
    ok: bool | None  # null = indéterminée (aucune facture rapprochée)


class FactureRapprocheeRead(BaseModel):
    """Read-only context from the external IMX referential
    (imx.factures) — never modifiable through this API (production
    connects to the real IMX database read-only, see db/models/imx.py).
    Distinct from TraiteDetail.montant_avoirs_saisi, which is this app's
    own cashier observation for this control, never a correction of this
    data."""

    num_facture: str
    montant_ttc: Decimal
    montant_avoirs: Decimal
    montant_net: Decimal


class DebtorCoverageRead(BaseModel):
    """BPMN Phase 3, étape 3 — invoice coverage check for this bill's
    resolved debtor, computed live (see app/services/coverage.py) over
    every bill this app currently knows about for them, not scoped to any
    one "remise" (still deferred — see that module's own docstring).
    Settings.coverage_gap_threshold is a working hypothesis, not a value
    the spec actually states — never present ``sufficient`` as a
    definitive answer in the UI."""

    total_bills_amount: Decimal
    total_invoices_net_amount: Decimal
    total_credit_notes_amount: Decimal
    gap: Decimal
    sufficient: bool


class DebtorControlRollupRead(BaseModel):
    """BPMN Phase 2, étape 10 — one OK/KO per rubrique, computed live
    (see app/services/control_rollup.py) over every bill this app
    currently knows about for this bill's resolved debtor, not scoped to
    any one "remise" (still deferred — see that module's own docstring).
    Each rubrique reuses a verdict already computed elsewhere on this
    same API response for a single bill; this only rolls it up across
    every bill known for the debtor."""

    mandatory_mentions_ok: bool
    duplicated_fields_ok: bool
    date_rules_ok: bool
    identification_ok: bool
    coverage_ok: bool


class TraiteDetail(TraiteRead):
    documents: list[TraiteDocumentRead] = []
    champs_extraits: list[ChampExtraitRead] = []
    rapprochements_nlp: list[RapprochementNlpRead] = []
    verifications_manuelles: list[VerificationManuelleRead] = []
    decisions: list[DecisionRead] = []
    # Computed server-side (see app/services/verification_rules.py and
    # app/services/mentions_rules.py) — not columns on the ORM model, so
    # this response is always built explicitly rather than serialized
    # directly off the SQLAlchemy instance.
    bloque: bool
    motif_blocage: str | None
    recommandation: RecommandationRead
    mentions: list[MentionRead] = []
    regles_dates: list[RegleDateRead] = []
    num_facture_rapprochee: str | None = None
    facture_rapprochee: FactureRapprocheeRead | None = None
    # This app's own cashier observation (BPMN Phase 3, étape 2) — see
    # FactureRapprocheeRead's docstring for why it's a separate field, not
    # folded into that IMX read-only data.
    montant_avoirs_saisi: Decimal | None = None
    debtor_coverage: DebtorCoverageRead | None = None
    control_rollup: DebtorControlRollupRead | None = None


class TraitePage(BaseModel):
    items: list[TraiteRead]
    total: int
    page: int
    per_page: int


class TraiteStatusRead(BaseModel):
    """The "waiting system" polling contract — deliberately minimal (no
    joins, no nested relations) so polling every second or two is cheap."""

    statut: TraiteStatut
    en_cours: bool


class TraiteCountsRead(BaseModel):
    """Backs the queue list's 5 status counter cards. Every TraiteStatut
    value is always present (0 if there are none), so the frontend never
    has to guess at a missing key."""

    par_statut: dict[TraiteStatut, int]
