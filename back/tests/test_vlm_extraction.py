"""Sprint 8 — real OCR/extraction via Azure OpenAI's vision-capable chat
model.

Pure unit tests, no network: the Azure OpenAI client is a dependency-
injected fake, never the real SDK talking to a real service.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.db.models.traite import Face, Traite, TraiteDocument
from app.services.extraction import (
    CHAMP_LIEU_CREATION,
    CHAMP_NUMERO_LCN,
    CHAMP_RIB_TIRE,
    ROLE_ORDRE,
    ROLE_TIRE,
    ROLE_TIREUR,
    StubExtractor,
)
from app.services.vlm_extraction import (
    VlmExtractor,
    _client_azure_openai,
    _parse_json_response,
    get_extractor,
)


def _traite_with_documents(recto_ct: str = "image/jpeg", verso_ct: str = "image/jpeg") -> Traite:
    traite = Traite(
        numero_lcn="011570763437",
        montant=Decimal("1500.000"),
        date_echeance=date(2026, 12, 1),
        date_creation_traite=date(2026, 9, 1),
    )
    traite.documents = [
        TraiteDocument(
            face=Face.RECTO, fichier_nom="recto.jpg", fichier_chemin="/x/recto.jpg",
            content_type=recto_ct, taille_octets=10,
        ),
        TraiteDocument(
            face=Face.VERSO, fichier_nom="verso.jpg", fichier_chemin="/x/verso.jpg",
            content_type=verso_ct, taille_octets=10,
        ),
    ]
    return traite


@dataclass
class _FakeChatCompletions:
    content: str
    last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.chat = SimpleNamespace(completions=_FakeChatCompletions(content))


# ---- JSON parsing --------------------------------------------------------


def test_parse_json_response_accepts_raw_json():
    assert _parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_response_strips_markdown_fence():
    text = "```json\n{\"a\": 1}\n```"
    assert _parse_json_response(text) == {"a": 1}


def test_parse_json_response_extracts_object_from_surrounding_prose():
    text = "Voici le résultat :\n{\"a\": 1}\nFin."
    assert _parse_json_response(text) == {"a": 1}


def test_parse_json_response_raises_clearly_when_no_object_found():
    with pytest.raises(ValueError, match="ne contient pas d'objet JSON"):
        _parse_json_response("je ne sais pas lire cette image.")


# ---- VlmExtractor.extract -------------------------------------------------


def test_extract_maps_both_occurrences_and_parties(monkeypatch):
    # record_extraction (raw psycopg, see extraction_log.py) is a real
    # I/O boundary — mocked here the same way the Azure client already is,
    # so this stays a pure unit test. It's exercised for real against the
    # test database in test_extraction_log.py instead.
    log = []
    monkeypatch.setattr(
        "app.services.vlm_extraction.record_extraction",
        lambda **kwargs: log.append(kwargs),
    )

    response_text = """{
      "numero_lcn": {"occurrence_1": "011570763437", "occurrence_2": "011570763437"},
      "montant_chiffres": {"occurrence_1": "1500.000", "occurrence_2": "1500.000"},
      "montant_lettres": {"occurrence_1": null, "occurrence_2": null},
      "echeance": {"occurrence_1": "2026-12-01", "occurrence_2": "2026-12-01"},
      "date_creation": {"occurrence_1": "2026-09-01", "occurrence_2": "2026-09-01"},
      "rib_tire": {"occurrence_1": "TN591000...", "occurrence_2": null},
      "lieu_creation": {"occurrence_1": "Tunis", "occurrence_2": "Tunis"},
      "tireur_texte": "ADACTIM",
      "tire_texte": "LA MEDITERRANEENNE",
      "ordre_texte": "SPG"
    }"""
    client = _FakeClient(response_text)
    extractor = VlmExtractor(client, "test-model")

    result = extractor.extract(_traite_with_documents(), b"recto-bytes", b"verso-bytes")

    by_field = {(f.field_name, f.occurrence): f.value for f in result.fields}
    assert by_field[(CHAMP_NUMERO_LCN, 1)] == "011570763437"
    assert by_field[(CHAMP_RIB_TIRE, 1)] == "TN591000..."
    assert by_field[(CHAMP_RIB_TIRE, 2)] is None
    assert by_field[(CHAMP_LIEU_CREATION, 1)] == "Tunis"

    by_role = {p.role: p.scanned_value for p in result.parties}
    assert by_role == {ROLE_TIREUR: "ADACTIM", ROLE_TIRE: "LA MEDITERRANEENNE", ROLE_ORDRE: "SPG"}

    # Confirms the model actually received both images, not just the prompt.
    sent_content = client.chat.completions.last_kwargs["messages"][0]["content"]
    image_parts = [p for p in sent_content if p.get("type") == "image_url"]
    assert len(image_parts) == 2
    assert image_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    # The raw-SQL audit log (extraction_log.py) got exactly one successful
    # entry with the real raw response — not just the parsed result.
    assert len(log) == 1
    assert log[0]["success"] is True
    assert log[0]["provider"] == "azure_openai"
    assert log[0]["raw_response"] == response_text


def test_extract_logs_the_failed_attempt_with_the_real_raw_response(monkeypatch):
    """Caught live (Sprint 8): a real model can ignore the "respond only
    with JSON" instruction and describe the image conversationally
    instead. The audit log must capture that actual text, not just
    "invalid JSON" — that's the whole point of logging raw responses."""
    log = []
    monkeypatch.setattr(
        "app.services.vlm_extraction.record_extraction",
        lambda **kwargs: log.append(kwargs),
    )
    off_topic_response = "The image features a gray and brown striped pattern."
    client = _FakeClient(off_topic_response)
    extractor = VlmExtractor(client, "gpt-4o-vision")

    with pytest.raises(ValueError, match="ne contient pas d'objet JSON"):
        extractor.extract(_traite_with_documents(), b"recto-bytes", b"verso-bytes")

    assert len(log) == 1
    assert log[0]["success"] is False
    assert log[0]["raw_response"] == off_topic_response
    assert "JSON" in log[0]["error"]


def test_extract_skips_the_model_call_for_non_image_content_type():
    """A PDF upload is legitimate (Sprint 2) but real VLM extraction from
    one isn't implemented — must report absence, not send un-decodable
    bytes to the model or crash the analysis pipeline."""
    client = _FakeClient('{"numero_lcn": {}}')
    extractor = VlmExtractor(client, "test-model")

    result = extractor.extract(_traite_with_documents(recto_ct="application/pdf"), b"%PDF-1.4", b"verso-bytes")

    assert result.fields == []
    assert result.parties == []
    assert client.chat.completions.last_kwargs is None


# ---- provider selection ---------------------------------------------------


def test_client_azure_openai_requires_full_configuration():
    # Explicit empty overrides, not just omission: since Sprint 11 the
    # backend container (where tests also run) carries the real
    # AZURE_OPENAI_* vars for the live pipeline, so relying on ambient env
    # being unset would make this test's outcome depend on whatever's in
    # .env rather than on the code under test.
    settings = Settings(
        ocr_provider="azure_openai",
        azure_openai_endpoint="",
        azure_openai_api_key="",
        azure_openai_deployment="",
    )
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        _client_azure_openai(settings)


def test_client_azure_openai_builds_client_when_configured():
    settings = Settings(
        ocr_provider="azure_openai",
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_api_key="secret",
        azure_openai_deployment="gpt-4o-vision",
    )
    client, model = _client_azure_openai(settings)
    assert model == "gpt-4o-vision"
    assert client is not None


def test_get_extractor_defaults_to_stub(monkeypatch):
    monkeypatch.setattr("app.services.vlm_extraction.get_settings", lambda: Settings(ocr_provider="stub"))
    assert isinstance(get_extractor(), StubExtractor)


def test_get_extractor_dispatches_to_azure_openai(monkeypatch):
    settings = Settings(
        ocr_provider="azure_openai",
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_api_key="secret",
        azure_openai_deployment="gpt-4o-vision",
    )
    monkeypatch.setattr("app.services.vlm_extraction.get_settings", lambda: settings)
    extractor = get_extractor()
    assert isinstance(extractor, VlmExtractor)
    assert extractor._model == "gpt-4o-vision"


def test_get_extractor_rejects_unknown_provider(monkeypatch):
    settings = Settings(ocr_provider="carrier-pigeon")
    monkeypatch.setattr("app.services.vlm_extraction.get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="OCR_PROVIDER inconnu"):
        get_extractor()
