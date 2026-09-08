"""Real OCR/extraction backed by Azure OpenAI's vision-capable chat model,
selected at deploy time by the ``OCR_PROVIDER`` env var (see
app/core/config.py).

This is a real implementation of the ``Extractor`` interface defined in
extraction.py; that module (and its ``StubExtractor``) has no dependency
on the ``openai`` package, so importing it never requires network
credentials — only importing *this* module, or calling ``get_extractor()``
with ``OCR_PROVIDER=azure_openai`` configured, does.
"""
import base64
import json
import logging
import re
from typing import Any

from openai import AzureOpenAI

from app.core.config import Settings, get_settings
from app.db.models.traite import Face, Traite
from app.services.extraction import (
    CHAMP_CLE_RIB,
    CHAMP_CODE_AGENCE,
    CHAMP_CODE_ETABLISSEMENT,
    CHAMP_DATE_CREATION,
    CHAMP_ECHEANCE,
    CHAMP_LIEU_CREATION,
    CHAMP_MONTANT_CHIFFRES,
    CHAMP_MONTANT_LETTRES,
    CHAMP_NUMERO_COMPTE,
    CHAMP_NUMERO_LCN,
    CHAMP_RIB_TIRE,
    ROLE_DOMICILIATION,
    ROLE_ORDRE,
    ROLE_TIRE,
    ROLE_TIREUR,
    Extractor,
    ExtractionResult,
    FieldCandidate,
    PartyCandidate,
    StubExtractor,
)
from app.services.extraction_log import Stopwatch, record_extraction

logger = logging.getLogger(__name__)

_FIELDS_TO_EXTRACT = [
    CHAMP_NUMERO_LCN,
    CHAMP_MONTANT_CHIFFRES,
    CHAMP_MONTANT_LETTRES,
    CHAMP_ECHEANCE,
    CHAMP_DATE_CREATION,
    CHAMP_RIB_TIRE,
    CHAMP_CODE_ETABLISSEMENT,
    CHAMP_CODE_AGENCE,
    CHAMP_NUMERO_COMPTE,
    CHAMP_CLE_RIB,
    CHAMP_LIEU_CREATION,
]

_PROMPT = """Tu es un agent de contrôle back-office spécialisé dans la lecture de lettres de change (traites) tunisiennes. On te fournit le recto puis le verso scannés d'une même traite.

Pour chacun des champs suivants, la traite peut porter DEUX occurrences visuellement distinctes du même champ (contrôle de cohérence habituel sur ce type d'instrument) — relève les deux indépendamment si tu peux les localiser, une seule si l'autre n'existe pas sur ce document, ou aucune si le champ est illisible ou absent :
- numero_lcn (numéro de la lettre de change / traite)
- montant_chiffres (montant en chiffres)
- montant_lettres (montant écrit en toutes lettres)
- echeance (date d'échéance, au format AAAA-MM-JJ si possible)
- date_creation (date de création, au format AAAA-MM-JJ si possible)
- rib_tire (RIB ou domiciliation bancaire du tiré, lu directement dans sa case dédiée "RIB ou RIP du Tiré")
- lieu_creation (lieu de création)
- code_etablissement (2 premiers chiffres du RIB du tiré, case dédiée "Code étab.")
- code_agence (3 chiffres suivants du RIB du tiré, case dédiée "Code Agence")
- numero_compte (13 chiffres suivants du RIB du tiré, case dédiée "N° de Compte")
- cle_rib (2 derniers chiffres du RIB du tiré, case dédiée "Clé")

Les 4 derniers champs ci-dessus (code_etablissement/code_agence/numero_compte/cle_rib)
sont des cases séparées et distinctes de la case rib_tire elle-même — une
seconde reconstitution indépendante du même RIB à 20 chiffres, pas une
lecture redondante de la même case.

Relève aussi, une seule fois chacun :
- tireur_texte (nom de l'entreprise qui tire la traite, généralement en haut du recto)
- tire_texte (nom de l'entreprise tirée / débitrice, dans la case "payez contre cette lettre de change à l'ordre de...")
- ordre_texte (bénéficiaire de l'endossement au verso, généralement "à l'ordre de ...")
- domiciliation_texte (nom et adresse de l'agence bancaire du tiré)

ATTENTION — piège fréquent sur tireur_texte / tire_texte / ordre_texte : le
formulaire imprimé porte souvent, à l'intérieur ou à côté de la case
elle-même, une légende statique du type "Nom ou raison sociale du tireur
(vendeur)" ou "Nom et adresse du Tiré (acheteur)". Cette légende fait partie
du gabarit imprimé, ce N'EST PAS une donnée renseignée. Si la case ne
contient aucune écriture manuscrite ou dactylographiée distincte de cette
légende, le champ est ABSENT : réponds `null`, ne recopie jamais le texte de
la légende comme si c'était le nom réel.

ATTENTION — piège distinct sur domiciliation_texte : le nom de l'agence
bancaire (Domiciliation) peut déborder hors de sa case imprimée. Lis le
texte même s'il chevauche la case voisine ; ne le tronque jamais à la
largeur de sa case.

Réponds UNIQUEMENT avec un objet JSON strictement de cette forme, sans texte autour, sans balises markdown :
{
  "numero_lcn": {"occurrence_1": "...", "occurrence_2": "..."},
  "montant_chiffres": {"occurrence_1": "...", "occurrence_2": "..."},
  "montant_lettres": {"occurrence_1": "...", "occurrence_2": "..."},
  "echeance": {"occurrence_1": "...", "occurrence_2": "..."},
  "date_creation": {"occurrence_1": "...", "occurrence_2": "..."},
  "rib_tire": {"occurrence_1": "...", "occurrence_2": "..."},
  "lieu_creation": {"occurrence_1": "...", "occurrence_2": "..."},
  "code_etablissement": {"occurrence_1": "...", "occurrence_2": "..."},
  "code_agence": {"occurrence_1": "...", "occurrence_2": "..."},
  "numero_compte": {"occurrence_1": "...", "occurrence_2": "..."},
  "cle_rib": {"occurrence_1": "...", "occurrence_2": "..."},
  "tireur_texte": "...",
  "tire_texte": "...",
  "ordre_texte": "...",
  "domiciliation_texte": "..."
}
Utilise `null` (jamais une chaîne vide) pour tout champ illisible ou absent."""


def _image_part(content_type: str, image_bytes: bytes) -> dict[str, Any]:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}}


def _parse_json_response(text: str) -> dict[str, Any]:
    """The prompt asks for raw JSON, but models occasionally wrap it in a
    markdown code fence (or add a stray sentence) anyway — strip that
    defensively rather than trust the instruction was followed."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```\s*$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"La réponse du modèle ne contient pas d'objet JSON exploitable : {text[:200]!r}")
    return json.loads(text[start : end + 1])


def _content_type_for(traite: Traite, face: Face) -> str | None:
    document = next((d for d in traite.documents if d.face == face), None)
    return document.content_type if document else None


class VlmExtractor:
    """Real extraction via Azure OpenAI's Chat Completions API."""

    def __init__(self, client: AzureOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def extract(self, traite: Traite, recto: bytes, verso: bytes) -> ExtractionResult:
        recto_content_type = _content_type_for(traite, Face.RECTO)
        verso_content_type = _content_type_for(traite, Face.VERSO)
        # Vision chat APIs take image/* content — not application/pdf. A
        # PDF upload is legitimate (Sprint 2 accepts it) but real VLM
        # extraction from one isn't implemented yet; report absence rather
        # than send bytes the model can't read as an image.
        if not (
            recto_content_type
            and recto_content_type.startswith("image/")
            and verso_content_type
            and verso_content_type.startswith("image/")
        ):
            logger.warning(
                "VLM extraction skipped for traite %s: non-image content-type (recto=%s, verso=%s) — "
                "PDF extraction isn't implemented yet.",
                traite.id,
                recto_content_type,
                verso_content_type,
            )
            return ExtractionResult()

        stopwatch = Stopwatch()
        content: str | None = None
        try:
            message_content = [
                {"type": "text", "text": _PROMPT},
                {"type": "text", "text": "Recto :"},
                _image_part(recto_content_type, recto),
                {"type": "text", "text": "Verso :"},
                _image_part(verso_content_type, verso),
            ]
            # No explicit temperature: newer reasoning-style deployments
            # (found live with "gpt-6-astra") reject any value other than
            # their own default with a 400 — "'temperature' does not
            # support 0.0 with this model. Only the default (1) value is
            # supported." Omitting it lets each deployment use whatever
            # default it actually supports instead of hardcoding an
            # assumption that doesn't hold across models.
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": message_content,
                    }
                ],
            )
            content = response.choices[0].message.content or ""
            data = _parse_json_response(content)
        except Exception as exc:
            # Logged here — the raw response the model actually gave, not
            # just the exception message — because *why* extraction failed
            # (bad JSON vs. a network/auth error) is invisible from
            # execute_analysis's own audit_log entry alone, which only ever
            # sees str(exc). Re-raised so execute_analysis's existing
            # failure handling (statut -> ECARTS_A_TRAITER) still applies.
            record_extraction(
                traite_id=traite.id,
                provider="azure_openai",
                model=self._model,
                success=False,
                raw_response=content,
                error=str(exc),
                duration_ms=stopwatch.elapsed_ms(),
            )
            raise

        record_extraction(
            traite_id=traite.id,
            provider="azure_openai",
            model=self._model,
            success=True,
            raw_response=content,
            error=None,
            duration_ms=stopwatch.elapsed_ms(),
        )

        fields: list[FieldCandidate] = []
        for field_name in _FIELDS_TO_EXTRACT:
            occurrences = data.get(field_name) or {}
            fields.append(FieldCandidate(field_name, 1, occurrences.get("occurrence_1")))
            fields.append(FieldCandidate(field_name, 2, occurrences.get("occurrence_2")))

        parties = [
            PartyCandidate(ROLE_TIREUR, data.get("tireur_texte")),
            PartyCandidate(ROLE_TIRE, data.get("tire_texte")),
            PartyCandidate(ROLE_ORDRE, data.get("ordre_texte")),
            PartyCandidate(ROLE_DOMICILIATION, data.get("domiciliation_texte")),
        ]
        return ExtractionResult(fields=fields, parties=parties)


def _client_azure_openai(settings: Settings) -> tuple[AzureOpenAI, str]:
    if not (settings.azure_openai_endpoint and settings.azure_openai_api_key and settings.azure_openai_deployment):
        raise RuntimeError(
            "OCR_PROVIDER=azure_openai nécessite AZURE_OPENAI_ENDPOINT, "
            "AZURE_OPENAI_API_KEY et AZURE_OPENAI_DEPLOYMENT."
        )
    client = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )
    return client, settings.azure_openai_deployment


def get_extractor() -> Extractor:
    """Selects the extraction backend from ``OCR_PROVIDER`` — the same
    ``Extractor`` seam ``execute_analysis``/the background task always
    expected. Defaults to ``StubExtractor``: an unset or misconfigured
    provider must never silently fall back to a real, possibly-billed
    external call."""
    settings = get_settings()
    if settings.ocr_provider == "stub":
        return StubExtractor()
    if settings.ocr_provider == "azure_openai":
        client, model = _client_azure_openai(settings)
        return VlmExtractor(client, model)
    raise RuntimeError(f"OCR_PROVIDER inconnu : {settings.ocr_provider!r} (attendu : stub, azure_openai).")
