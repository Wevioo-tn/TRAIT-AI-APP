import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models.traite import (
    Decision,
    Face,
    Traite,
    TraiteDocument,
    TraiteStatut,
    TypeDecision,
    VerificationCode,
    VerificationManuelle,
)
from app.db.session import get_session
from app.schemas.traite import (
    ChampExtraitRead,
    DebtorControlRollupRead,
    DebtorCoverageRead,
    DecisionCreate,
    DecisionRead,
    FactureRapprocheeRead,
    MentionRead,
    MontantAvoirsUpdate,
    RapprochementNlpRead,
    RecommandationRead,
    RegleDateRead,
    TraiteCountsRead,
    TraiteCreate,
    TraiteDetail,
    TraiteDocumentRead,
    TraitePage,
    TraiteRead,
    TraiteStatusRead,
    VerificationManuelleRead,
    VerificationUpdate,
)
from app.services.audit import log_action
from app.services.analysis_summary import build_analysis_summary
from app.services.control_rollup import calculate_debtor_control_rollup
from app.services.coverage import calculate_debtor_coverage
from app.services.mentions_rules import evaluate_date_rules, evaluate_mandatory_mentions, find_matching_invoice
from app.services.storage import LocalFileStorage, get_storage
from app.services.traite_processing import PLACEHOLDER_BILL_AMOUNT
from app.services.verification_rules import evaluate_verifications
from app.tasks.traite_processing import run_traite_analysis

router = APIRouter(prefix="/traites", tags=["traites"], dependencies=[Depends(get_current_user)])
settings = get_settings()

ALLOWED_UPLOAD_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}

# A traite with one of these statuts has a final decision — nothing about
# it (verifications, further decisions) is modifiable anymore. The design
# mockup never models this (it only ever demos one traite mid-review), but
# a real backend has to: without it, a "renvoyée" traite could still be
# flipped to "validée" by a second, contradictory decision.
_FINAL_STATUTS = {TraiteStatut.VALIDEE, TraiteStatut.RENVOYEE, TraiteStatut.FRAUDE_SIGNALEE}

_DETAIL_OPTIONS = (
    selectinload(Traite.documents),
    selectinload(Traite.champs_extraits),
    selectinload(Traite.rapprochements_nlp),
    selectinload(Traite.verifications_manuelles),
    selectinload(Traite.decisions),
    selectinload(Traite.adherent),
    selectinload(Traite.debiteur),
)


async def _build_detail(session: AsyncSession, traite: Traite) -> TraiteDetail:
    """Assemble the full detail response, including everything computed
    server-side rather than stored as columns on the ORM model."""
    blocking_state = evaluate_verifications(traite.verifications_manuelles, traite.statut)
    invoice = await find_matching_invoice(session, traite)
    mentions = evaluate_mandatory_mentions(
        traite, traite.champs_extraits, traite.rapprochements_nlp, traite.verifications_manuelles
    )
    date_rules = evaluate_date_rules(traite, invoice, traite.champs_extraits)
    # Computed live, not from anything stored on this traite: a debtor's
    # coverage depends on every other bill/saisie known for them, which
    # can change independently of this one bill's own last analysis (see
    # app/services/coverage.py's own docstring).
    debtor_coverage = (
        await calculate_debtor_coverage(session, traite.code_debiteur) if traite.code_debiteur is not None else None
    )
    control_rollup = (
        await calculate_debtor_control_rollup(session, traite.code_debiteur)
        if traite.code_debiteur is not None
        else None
    )

    nlp_rows = [RapprochementNlpRead.model_validate(n) for n in traite.rapprochements_nlp]
    scanned_rib = next((f.valeur for f in sorted(traite.champs_extraits, key=lambda f: f.occurrence)
                        if f.nom_champ == "rib_tire" and f.valeur), "")
    for row in nlp_rows:
        if row.role == "rib":
            row.valeur_scan = scanned_rib

    return TraiteDetail(
        **build_analysis_summary(traite),
        documents=[TraiteDocumentRead.model_validate(d) for d in traite.documents],
        champs_extraits=[ChampExtraitRead.model_validate(c) for c in traite.champs_extraits],
        rapprochements_nlp=nlp_rows,
        verifications_manuelles=[VerificationManuelleRead.model_validate(v) for v in traite.verifications_manuelles],
        decisions=[DecisionRead.model_validate(d) for d in traite.decisions],
        bloque=blocking_state.blocked,
        motif_blocage=blocking_state.reason,
        recommandation=RecommandationRead(
            titre=blocking_state.recommendation.title, detail=blocking_state.recommendation.detail
        ),
        visual_marks=traite.visual_marks,
        mentions=[MentionRead(code=m.code, label=m.label, valeur=m.value, statut=m.status) for m in mentions],
        regles_dates=[
            RegleDateRead(label=r.label, valeur_a=r.value_a, valeur_b=r.value_b, ok=r.ok) for r in date_rules
        ],
        num_facture_rapprochee=invoice.num_facture if invoice else None,
        facture_rapprochee=(
            FactureRapprocheeRead(
                num_facture=invoice.num_facture,
                montant_ttc=invoice.montant_ttc,
                montant_avoirs=invoice.montant_avoirs,
                montant_net=invoice.montant_net,
            )
            if invoice
            else None
        ),
        montant_avoirs_saisi=traite.montant_avoirs_saisi,
        debtor_coverage=(
            DebtorCoverageRead(
                total_bills_amount=debtor_coverage.total_bills_amount,
                total_invoices_net_amount=debtor_coverage.total_invoices_net_amount,
                total_credit_notes_amount=debtor_coverage.total_credit_notes_amount,
                gap=debtor_coverage.gap,
                sufficient=debtor_coverage.sufficient,
            )
            if debtor_coverage is not None
            else None
        ),
        control_rollup=(
            DebtorControlRollupRead(
                mandatory_mentions_ok=control_rollup.mandatory_mentions_ok,
                duplicated_fields_ok=control_rollup.duplicated_fields_ok,
                date_rules_ok=control_rollup.date_rules_ok,
                identification_ok=control_rollup.identification_ok,
                coverage_ok=control_rollup.coverage_ok,
            )
            if control_rollup is not None
            else None
        ),
        domiciliation=traite.domiciliation,
        cross_field_discrepancies=traite.cross_field_discrepancies or [],
    )


@router.get("", response_model=TraitePage)
async def list_traites(
    statut: TraiteStatut | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> TraitePage:
    """Queue list — mirrors the design's "Traites à contrôler" table.

    Sorted by ``date_reception`` ascending: the traite waiting longest has
    the *least* SLA time remaining, so it surfaces first — this is what
    "tri par délai restant croissant" means in the design (a 24h processing
    SLA measured from reception, unrelated to the bill's payment due date).
    """
    base = select(Traite)
    if statut is not None:
        base = base.where(Traite.statut == statut)

    total = await session.scalar(select(func.count()).select_from(base.subquery()))

    stmt = (
        base.options(selectinload(Traite.adherent), selectinload(Traite.debiteur))
        .order_by(Traite.date_reception.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = (await session.execute(stmt)).scalars().all()

    return TraitePage(items=items, total=total or 0, page=page, per_page=per_page)


@router.get("/counts", response_model=TraiteCountsRead)
async def get_traite_counts(session: AsyncSession = Depends(get_session)) -> TraiteCountsRead:
    """Backs the queue list's status counter cards. Registered before
    GET /{traite_id} so "counts" is never swallowed as a traite_id."""
    rows = (
        await session.execute(select(Traite.statut, func.count()).group_by(Traite.statut))
    ).all()
    counts = {statut: count for statut, count in rows}
    return TraiteCountsRead(par_statut={statut: counts.get(statut, 0) for statut in TraiteStatut})


def _generate_numero_lcn() -> str:
    """A traite created straight from a scan, with no bordereau intake to
    read a real L-CN number from, still needs a unique key — see
    TraiteCreate's docstring for why this exists at all."""
    return f"AUTO-{uuid.uuid4().hex[:10].upper()}"


@router.post("", response_model=TraiteDetail, status_code=201)
async def create_traite(
    payload: TraiteCreate,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
) -> Traite:
    today = date.today()
    numero_lcn = payload.numero_lcn or _generate_numero_lcn()
    montant = payload.montant if payload.montant is not None else PLACEHOLDER_BILL_AMOUNT
    date_echeance = payload.date_echeance or today
    date_creation_traite = payload.date_creation_traite or today

    existing = await session.scalar(select(Traite).where(Traite.numero_lcn == numero_lcn))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Une traite avec ce numéro L-CN existe déjà.")

    traite = Traite(
        numero_lcn=numero_lcn,
        montant=montant,
        date_echeance=date_echeance,
        date_creation_traite=date_creation_traite,
    )
    session.add(traite)
    await session.flush()  # assigns traite.id

    # Every traite is born with its 4 mandatory manual-verification slots —
    # the checklist is fixed (signature tiré, acceptation, signature
    # tireur, endossement), so there's never a reason to create them lazily.
    for code in VerificationCode:
        session.add(VerificationManuelle(traite_id=traite.id, code_verification=code))

    await log_action(session, user=current_user, action="traite_creee", traite_id=traite.id)

    await session.commit()

    detail_stmt = select(Traite).where(Traite.id == traite.id).options(*_DETAIL_OPTIONS)
    return await _build_detail(session, await session.scalar(detail_stmt))


@router.get("/{traite_id}", response_model=TraiteDetail)
async def get_traite(traite_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> TraiteDetail:
    stmt = select(Traite).where(Traite.id == traite_id).options(*_DETAIL_OPTIONS)
    traite = await session.scalar(stmt)
    if traite is None:
        raise HTTPException(status_code=404, detail="Traite introuvable.")
    return await _build_detail(session, traite)


@router.post("/{traite_id}/documents", response_model=TraiteDocumentRead, status_code=201)
async def upload_document(
    traite_id: uuid.UUID,
    face: Face,
    file: UploadFile = File(...),
    replace: bool = Query(default=False, description="Remplace le fichier existant pour cette face, s'il y en a un."),
    session: AsyncSession = Depends(get_session),
    storage: LocalFileStorage = Depends(get_storage),
    current_user: str = Depends(get_current_user),
) -> TraiteDocument:
    """Recto/verso upload — both faces are required by the design before an
    analysis can be launched, but that's enforced by the caller (there's
    nothing wrong with a traite that only has one face uploaded so far)."""
    traite = await session.get(Traite, traite_id)
    if traite is None:
        raise HTTPException(status_code=404, detail="Traite introuvable.")

    if file.content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Type de fichier non supporté : {file.content_type}. Formats acceptés : JPEG, PNG, PDF.",
        )

    content = await file.read()
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (15 Mo maximum).")

    existing = await session.scalar(
        select(TraiteDocument).where(TraiteDocument.traite_id == traite_id, TraiteDocument.face == face)
    )
    if existing is not None:
        if not replace:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Un fichier {face.value} existe déjà pour cette traite. "
                    "Ajoutez ?replace=true pour le remplacer."
                ),
            )
        await storage.delete(existing.fichier_chemin)
        await session.delete(existing)
        await session.flush()

    filename = file.filename or "document"
    path = await storage.save(traite_id, face.value, filename, content)

    document = TraiteDocument(
        traite_id=traite_id,
        face=face,
        fichier_nom=filename,
        fichier_chemin=path,
        content_type=file.content_type,
        taille_octets=len(content),
    )
    session.add(document)

    await log_action(
        session,
        user=current_user,
        action="document_televerse",
        traite_id=traite_id,
        details={"face": face.value, "fichier_nom": filename},
    )

    await session.commit()
    await session.refresh(document)
    return document


@router.get("/{traite_id}/documents/{face}")
async def download_document(
    traite_id: uuid.UUID,
    face: Face,
    session: AsyncSession = Depends(get_session),
    storage: LocalFileStorage = Depends(get_storage),
) -> Response:
    document = await session.scalar(
        select(TraiteDocument).where(TraiteDocument.traite_id == traite_id, TraiteDocument.face == face)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Aucun document pour cette face.")

    content = await storage.read(document.fichier_chemin)
    return Response(
        content=content,
        media_type=document.content_type,
        headers={"Content-Disposition": f'inline; filename="{document.fichier_nom}"'},
    )


@router.patch("/{traite_id}/verifications/{code}", response_model=VerificationManuelleRead)
async def update_verification(
    traite_id: uuid.UUID,
    code: VerificationCode,
    payload: VerificationUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
) -> VerificationManuelle:
    traite = await session.get(Traite, traite_id)
    if traite is None:
        raise HTTPException(status_code=404, detail="Traite introuvable.")
    if traite.statut in _FINAL_STATUTS:
        raise HTTPException(
            status_code=409,
            detail="Cette traite a une décision finale ; les vérifications ne sont plus modifiables.",
        )

    verification = await session.scalar(
        select(VerificationManuelle).where(
            VerificationManuelle.traite_id == traite_id,
            VerificationManuelle.code_verification == code,
        )
    )
    if verification is None:
        raise HTTPException(status_code=404, detail="Zone de vérification introuvable.")

    verification.statut = payload.statut
    verification.verifie_par = current_user if payload.statut is not None else None
    verification.verifie_le = datetime.now(timezone.utc) if payload.statut is not None else None

    await log_action(
        session,
        user=current_user,
        action="verification_modifiee",
        traite_id=traite_id,
        details={"code": code.value, "statut": payload.statut.value if payload.statut else None},
    )

    await session.commit()
    await session.refresh(verification)
    return verification


@router.patch("/{traite_id}/montant-avoirs", response_model=TraiteDetail)
async def update_montant_avoirs(
    traite_id: uuid.UUID,
    payload: MontantAvoirsUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
) -> TraiteDetail:
    """Caissier's manual observation of the avoirs applicable to this
    traite's coverage check (BPMN Phase 3, étape 2 — "Saisir manuellement
    les montants des avoirs par débiteur si applicable"), feeding a future
    TR-112 coverage calculation (still out of scope). Deliberately never
    written into imx.factures.montant_avoirs — see Traite.montant_avoirs_saisi's
    own docstring for why. Returns the full detail (not just the touched
    field) since the caissier judging "si applicable" needs the read-only
    IMX facture context (facture_rapprochee) alongside it in one response."""
    traite = await session.get(Traite, traite_id)
    if traite is None:
        raise HTTPException(status_code=404, detail="Traite introuvable.")
    if traite.statut in _FINAL_STATUTS:
        raise HTTPException(
            status_code=409,
            detail="Cette traite a une décision finale ; le montant des avoirs n'est plus modifiable.",
        )

    ancienne_valeur = traite.montant_avoirs_saisi
    traite.montant_avoirs_saisi = payload.montant_avoirs

    await log_action(
        session,
        user=current_user,
        action="montant_avoirs_saisi",
        traite_id=traite_id,
        details={
            "ancienne_valeur": str(ancienne_valeur) if ancienne_valeur is not None else None,
            "nouvelle_valeur": str(payload.montant_avoirs) if payload.montant_avoirs is not None else None,
        },
    )

    await session.commit()

    detail_stmt = select(Traite).where(Traite.id == traite_id).options(*_DETAIL_OPTIONS)
    return await _build_detail(session, await session.scalar(detail_stmt))


@router.post("/{traite_id}/decisions", response_model=DecisionRead, status_code=201)
async def create_decision(
    traite_id: uuid.UUID,
    payload: DecisionCreate,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
) -> Decision:
    """Cashier's final decision. Only "validée" is blocked by the manual
    verification rules — "renvoyer" and "signaler fraude" are always
    available, exactly as in the design (the mockup never disables those
    two buttons)."""
    stmt = select(Traite).where(Traite.id == traite_id).options(selectinload(Traite.verifications_manuelles))
    traite = await session.scalar(stmt)
    if traite is None:
        raise HTTPException(status_code=404, detail="Traite introuvable.")

    if traite.statut in _FINAL_STATUTS:
        raise HTTPException(status_code=409, detail="Cette traite a déjà une décision finale.")

    if payload.type == TypeDecision.VALIDEE:
        blocking_state = evaluate_verifications(traite.verifications_manuelles, traite.statut)
        if blocking_state.blocked:
            raise HTTPException(status_code=409, detail=blocking_state.reason)

    # Mandatory comment for renvoi/fraude, matching the design's own
    # "Commentaire (obligatoire si écart)" hint for those escalation paths.
    # Extending this to "validée" needs the OCR/NLP écarts computation
    # (Sprint 4) to know whether there's actually anything to justify.
    if payload.type in (TypeDecision.RENVOI, TypeDecision.FRAUDE) and not (
        payload.commentaire and payload.commentaire.strip()
    ):
        raise HTTPException(status_code=422, detail="Un commentaire est obligatoire pour ce type de décision.")

    decision = Decision(
        traite_id=traite_id,
        type=payload.type,
        commentaire=payload.commentaire,
        decide_par=current_user,
    )
    session.add(decision)

    traite.statut = {
        TypeDecision.VALIDEE: TraiteStatut.VALIDEE,
        TypeDecision.RENVOI: TraiteStatut.RENVOYEE,
        TypeDecision.FRAUDE: TraiteStatut.FRAUDE_SIGNALEE,
    }[payload.type]

    await log_action(
        session,
        user=current_user,
        action="decision_prise",
        traite_id=traite_id,
        details={"type": payload.type.value},
    )

    await session.commit()
    await session.refresh(decision)
    return decision


@router.post("/{traite_id}/analyse", response_model=TraiteRead, status_code=202)
async def lancer_analyse(
    traite_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
) -> Traite:
    """Kicks off the async OCR/NLP pipeline — the design's "Lancer
    l'analyse OCR / NLP" button. Returns immediately (202); the frontend
    polls GET .../status (the "waiting system") for the outcome."""
    stmt = (
        select(Traite)
        .where(Traite.id == traite_id)
        .options(selectinload(Traite.documents), selectinload(Traite.adherent), selectinload(Traite.debiteur))
    )
    traite = await session.scalar(stmt)
    if traite is None:
        raise HTTPException(status_code=404, detail="Traite introuvable.")

    faces = {d.face for d in traite.documents}
    missing = [f.value for f in (Face.RECTO, Face.VERSO) if f not in faces]
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"Recto et verso sont obligatoires avant de lancer l'analyse (manquant : {', '.join(missing)}).",
        )

    if traite.statut != TraiteStatut.A_TRAITER:
        raise HTTPException(
            status_code=409,
            detail=f"Cette traite est déjà au statut « {traite.statut.value} » ; l'analyse ne peut pas être relancée.",
        )

    traite.statut = TraiteStatut.EN_COURS_OCR
    await log_action(session, user=current_user, action="analyse_lancee", traite_id=traite_id)
    await session.commit()
    await session.refresh(traite)

    background_tasks.add_task(run_traite_analysis, str(traite_id))

    return traite


@router.get("/{traite_id}/status", response_model=TraiteStatusRead)
async def get_traite_status(traite_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> TraiteStatusRead:
    traite = await session.get(Traite, traite_id)
    if traite is None:
        raise HTTPException(status_code=404, detail="Traite introuvable.")
    return TraiteStatusRead(statut=traite.statut, en_cours=traite.statut == TraiteStatut.EN_COURS_OCR)
