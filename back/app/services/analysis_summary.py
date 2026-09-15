"""Read-only summary values; never promote OCR candidates into business data."""

from app.db.models.traite import Traite
from app.schemas.traite import TraiteRead
from app.services.traite_processing import _MAX_MONTANT, _parse_date, _parse_montant


def build_analysis_summary(traite: Traite) -> dict:
    data = TraiteRead.model_validate(traite).model_dump()
    for source, target, parse in (
        ("montant_chiffres", "montant", _parse_montant),
        ("echeance", "date_echeance", _parse_date),
    ):
        readings = [f.valeur for f in traite.champs_extraits if f.nom_champ == source and f.valeur]
        parsed = [parse(value) for value in readings]
        # Do not choose arbitrarily between conflicting or invalid readings.
        if parsed and None not in parsed and len(set(parsed)) == 1:
            value = parsed[0]
            if target != "montant" or (value.is_finite() and 0 < value < _MAX_MONTANT):
                data[target] = value

    for role, target in (("tireur", "tireur_nom"), ("tire", "tire_nom")):
        if not data[target]:
            scanned = next((n.valeur_scan for n in traite.rapprochements_nlp
                            if n.role.value == role and n.valeur_scan), None)
            # The source may contain an address; never label it as an IMX identity.
            if scanned:
                data[target] = f"Texte OCR : {scanned}"
    return data
