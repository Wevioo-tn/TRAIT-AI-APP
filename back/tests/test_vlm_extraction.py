"""Offline regression tests for image preparation and strict vision extraction."""
import base64
import json
from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from openai import AzureOpenAI
from sqlalchemy import select
from PIL import Image

from app.core.config import Settings
from app.db.models.traite import Face, Traite, TraiteDocument
from app.services.extraction import StubExtractor
from app.services.vision_document import VisionDocument
from app.services.vision_images import normalize_image
from app.services.vlm_extraction import (
    VlmExtractor, _client_azure_openai, _parse_json_response, get_extractor,
)

PAIRED_FIELDS = (
    "numero_lcn", "montant_chiffres", "montant_lettres", "echeance",
    "date_creation", "rib_tire", "lieu_creation", "code_etablissement",
    "code_agence", "numero_compte", "cle_rib",
)
MARK_FIELDS = ("has_signature_tire", "has_cachet_tire", "has_signature_tireur",
               "has_cachet_tireur", "has_acceptation_signature", "has_acceptation_cachet")
PARTY_FIELDS = ("tireur_texte", "tire_texte", "ordre_texte", "domiciliation_texte")


def _document():
    data = {name: {"occurrence_1": None, "occurrence_2": None} for name in PAIRED_FIELDS}
    data.update(dict.fromkeys(PARTY_FIELDS))
    data.update(dict.fromkeys(MARK_FIELDS, False))
    return data


def _image(format="PNG", mode="RGB", color="white", size=(24, 12), **kwargs):
    with BytesIO() as output:
        Image.new(mode, size, color).save(output, format=format, **kwargs)
        return output.getvalue()


def _traite_with_documents(recto_ct="image/png", verso_ct="image/png"):
    traite = Traite(
        numero_lcn="011570763437", montant=Decimal("1500.000"),
        date_echeance=date(2026, 12, 1), date_creation_traite=date(2026, 9, 1),
    )
    traite.documents = [
        TraiteDocument(face=face, fichier_nom="scan.png", content=b"0123456789",
                       content_type=ct, taille_octets=10)
        for face, ct in ((Face.RECTO, recto_ct), (Face.VERSO, verso_ct))
    ]
    return traite


class _FakeClient:
    def __init__(self, content, finish_reason="stop", refusal=None):
        self.content = content
        self.finish_reason = finish_reason
        self.refusal = refusal
        self.last_kwargs = None
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=self.content, refusal=self.refusal),
            finish_reason=self.finish_reason,
        )])


@pytest.fixture(autouse=True)
def extraction_log(monkeypatch):
    records = []
    monkeypatch.setattr("app.services.vlm_extraction.record_extraction", lambda **kw: records.append(kw))
    return records


def test_extract_preserves_backend_contract_and_source_text(extraction_log):
    data = _document()
    data["numero_lcn"] = {"occurrence_1": "00123", "occurrence_2": "00456"}
    data["echeance"] = {"occurrence_1": "15/09/26", "occurrence_2": None}
    data["montant_lettres"]["occurrence_1"] = "Deux mille\ndinars"
    for name, value in zip(PARTY_FIELDS, ("?metteur", "Payeur", "Ordre", "Agence\nTunis")):
        data[name] = value
    client = _FakeClient(json.dumps(data))
    result = VlmExtractor(client, "test-model").extract(_traite_with_documents(), _image(), _image())
    assert len(result.fields) == 22
    assert len(result.parties) == 4
    for field in result.fields:
        assert field.value == data[field.field_name][f"occurrence_{field.occurrence}"]
    assert {p.role: p.scanned_value for p in result.parties} == {
        "tireur": "?metteur", "tire": "Payeur", "ordre": "Ordre", "domiciliation": "Agence\nTunis",
    }
    request = client.last_kwargs
    assert request["model"] == "test-model"
    assert request["max_completion_tokens"] == 8192
    assert "temperature" not in request
    assert [m["role"] for m in request["messages"]] == ["system", "user"]
    images = request["messages"][1]["content"][1:]
    assert len(images) == 2
    assert all(p["image_url"]["detail"] == "high" for p in images)
    schema = request["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert set(schema["schema"]["properties"]) == set(PAIRED_FIELDS + PARTY_FIELDS + MARK_FIELDS)
    assert schema["schema"]["additionalProperties"] is False
    assert len(extraction_log) == 1
    assert extraction_log[0]["success"] is True
    assert extraction_log[0]["raw_response"] == client.content


def test_schema_requires_all_keys_and_azure_compatible_references():
    schema = VisionDocument.model_json_schema()
    pending = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if "$ref" in node:
                assert "description" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)


@pytest.mark.parametrize("bad", [None, "", "12A", "12-3", "??", "??"])
def test_rib_never_guesses_invalid_or_missing_components(bad):
    data = _document()
    for name, value in zip(PAIRED_FIELDS[7:], ("11", "003", "0002917001788", "36")):
        data[name]["occurrence_1"] = value
    data["code_agence"]["occurrence_1"] = bad
    data["rib_tire"] = {"occurrence_1": "11003000291700178836", "occurrence_2": "model guess"}
    parsed = _parse_json_response(json.dumps(data))
    assert parsed["rib_tire"]["occurrence_2"] is None
    assert parsed["rib_tire"]["occurrence_1"] == "11 003 0002917001788 36"


def test_rib_reconstruction_preserves_zeroes_and_independent_component_occurrences():
    data = _document()
    for name, value in zip(PAIRED_FIELDS[7:], (" 11", "003 ", "000 2917001788", "36")):
        data[name]["occurrence_1"] = value
    data["code_agence"]["occurrence_2"] = "999"
    parsed = _parse_json_response(json.dumps(data))
    assert parsed["rib_tire"]["occurrence_2"] == "11 003 0002917001788 36"
    assert parsed["code_agence"] == {"occurrence_1": "003", "occurrence_2": "999"}
    assert parsed["numero_compte"]["occurrence_2"] == "0002917001788"


@pytest.mark.parametrize("change", [
    lambda d: d.pop("domiciliation_texte"),
    lambda d: d.update(extra="unexpected"),
    lambda d: d.update(tire_texte=123),
    lambda d: d.update(numero_lcn="123"),
    lambda d: d["numero_lcn"].update(occurrence_1=123),
    lambda d: d["numero_lcn"].pop("occurrence_2"),
])
def test_invalid_schema_is_logged_as_failure(change, extraction_log):
    data = _document()
    change(data)
    client = _FakeClient(json.dumps(data))
    with pytest.raises(ValueError):
        VlmExtractor(client, "test").extract(_traite_with_documents(), _image(), _image())
    assert len(extraction_log) == 1
    assert extraction_log[0]["success"] is False
    assert extraction_log[0]["raw_response"] == client.content


@pytest.mark.parametrize("text", ["{}", "[]", "not JSON", '```json\n{}\n```'])
def test_parser_rejects_incomplete_or_non_schema_json(text):
    with pytest.raises(ValueError):
        _parse_json_response(text)


@pytest.mark.parametrize("finish,refusal", [("length", None), ("content_filter", None), ("stop", "refused")])
def test_rejects_incomplete_or_refused_responses(finish, refusal, extraction_log):
    client = _FakeClient(json.dumps(_document()), finish, refusal)
    with pytest.raises(ValueError, match="refused or incomplete"):
        VlmExtractor(client, "test").extract(_traite_with_documents(), _image(), _image())
    assert extraction_log[0]["success"] is False


def test_extract_skips_non_image_content_type():
    client = _FakeClient("{}")
    result = VlmExtractor(client, "test").extract(
        _traite_with_documents(recto_ct="application/pdf"), b"%PDF", _image(),
    )
    assert result.fields == [] and result.parties == []
    assert client.last_kwargs is None


def test_invalid_image_is_logged_without_calling_provider(extraction_log):
    client = _FakeClient("{}")
    with pytest.raises(ValueError, match="valid, complete image"):
        VlmExtractor(client, "test").extract(_traite_with_documents(), b"invalid", _image())
    assert client.last_kwargs is None
    assert extraction_log[0]["success"] is False
    assert extraction_log[0]["raw_response"] is None


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
def test_normalize_image_preserves_dimensions(format):
    url = normalize_image(_image(format=format))
    assert url.startswith("data:image/jpeg;base64,")
    with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        assert image.size == (24, 12)
        assert image.mode == "RGB"


def test_normalize_image_applies_exif_orientation():
    exif = Image.Exif()
    exif[274] = 6
    url = normalize_image(_image(format="JPEG", exif=exif))
    with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        assert image.size == (12, 24)
        assert image.getexif().get(274) is None


def test_normalize_image_flattens_transparency_onto_white():
    url = normalize_image(_image(mode="RGBA", color=(0, 0, 0, 0)))
    with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("data", [b"", b"invalid", _image()[:30], _image(format="GIF")])
def test_normalize_image_rejects_invalid_or_unsupported_input(data):
    with pytest.raises(ValueError):
        normalize_image(data)


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


def test_real_sdk_serializes_strict_request_and_parses_response():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "offline-completion", "object": "chat.completion", "created": 0,
            "model": "test-model", "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(_document())},
            }],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        with AzureOpenAI(
            azure_endpoint="https://example.openai.azure.com", api_key="offline-key",
            api_version="2024-08-01-preview", http_client=transport,
        ) as client:
            result = VlmExtractor(client, "test-model").extract(
                _traite_with_documents(), _image(color="red"), _image(color="blue"),
            )
    assert len(result.fields) == 22
    assert all(field.value is None for field in result.fields)
    assert requests[0]["response_format"]["json_schema"]["strict"] is True
    images = requests[0]["messages"][1]["content"][1:]
    for part, channel in zip(images, (0, 2)):
        with Image.open(BytesIO(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]))) as image:
            assert image.getpixel((0, 0))[channel] > 240


@pytest.mark.parametrize("invalid_response", [False, True])
def test_vision_extraction_integrates_with_persistence_and_failure_state(db_session, tmp_path, invalid_response):
    from app.db.models.traite import AuditLogEntry, ChampExtrait, TraiteStatut
    from app.services.traite_processing import execute_analysis

    traite = _traite_with_documents()
    traite.numero_lcn = "VISION-INTEGRATION"
    for document in traite.documents:
        document.content = _image()
        document.taille_octets = len(document.content)
    db_session.add(traite)
    db_session.flush()
    data = _document()
    data["montant_chiffres"] = {"occurrence_1": "2520,000", "occurrence_2": "2520,000"}
    data["domiciliation_texte"] = "Agence Tunis"
    data["has_signature_tireur"] = True
    data["rib_tire"]["occurrence_1"] = "11003000291700178836"
    for name, value in zip(PAIRED_FIELDS[7:], ("11", "003", "0002917001788", "36")):
        data[name]["occurrence_1"] = value
    client = _FakeClient("{}" if invalid_response else json.dumps(data))
    execute_analysis(traite.id, db_session, VlmExtractor(client, "test"))
    db_session.flush()
    fields = db_session.scalars(select(ChampExtrait).where(ChampExtrait.traite_id == traite.id)).all()
    events = db_session.scalars(select(AuditLogEntry).where(AuditLogEntry.traite_id == traite.id)).all()
    if invalid_response:
        assert fields == []
        assert traite.montant == Decimal("1500.000")
        assert any(event.action == "analyse_echouee" for event in events)
    else:
        assert len(fields) == 22
        assert traite.montant == Decimal("2520.000")
        assert traite.domiciliation == "Agence Tunis"
        assert traite.visual_marks["has_signature_tireur"] is True
        assert traite.visual_marks["has_cachet_tireur"] is False
        rib = [field for field in fields if field.nom_champ == "rib_tire"]
        assert [field.valeur for field in rib] == ["11 003 0002917001788 36"] * 2
        # Derived components agree without claiming a second OCR source.
        assert "code_agence" not in traite.cross_field_discrepancies
        assert any(event.action == "analyse_terminee" for event in events)
    assert traite.statut == TraiteStatut.ECARTS_A_TRAITER


@pytest.mark.parametrize("value", ["true", "false", 1, 0, None])
def test_visual_marks_require_native_booleans(value):
    data = _document()
    data["has_signature_tireur"] = value
    with pytest.raises(ValueError):
        _parse_json_response(json.dumps(data))


def test_two_equivalent_transcribed_dates_can_be_promoted():
    from app.services.traite_processing import _coherent_date
    assert _coherent_date(["07/09/26", "2026-09-07"]) == date(2026, 9, 7)
    assert _coherent_date(["07/09/26", None]) is None
    assert _coherent_date(["07/09/26", "08/09/26"]) is None


@pytest.mark.parametrize("account", ["000291700178", "00029170017889", "000291700178A"])
def test_invalid_length_or_characters_do_not_fill_second_components(account):
    data = _document()
    for name, value in zip(PAIRED_FIELDS[7:], ("11", "003", account, "36")):
        data[name]["occurrence_1"] = value
    result = _parse_json_response(json.dumps(data))
    assert all(result[name]["occurrence_2"] is None for name in PAIRED_FIELDS[7:])


def test_screenshot_rib_is_formatted_and_components_are_completed():
    data = _document()
    data["rib_tire"]["occurrence_1"] = "11 003 0002917 001788 36"
    for name, value in zip(PAIRED_FIELDS[7:], ("11", "003", "0002917 001788", "36")):
        data[name]["occurrence_1"] = value
    result = _parse_json_response(json.dumps(data))
    assert result["rib_tire"] == dict.fromkeys(("occurrence_1", "occurrence_2"), "11 003 0002917001788 36")
    for name, value in zip(PAIRED_FIELDS[7:], ("11", "003", "0002917001788", "36")):
        assert result[name] == dict.fromkeys(("occurrence_1", "occurrence_2"), value)
