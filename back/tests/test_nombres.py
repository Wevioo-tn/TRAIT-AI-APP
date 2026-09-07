"""Pure unit tests for French number-to-words — covers the classic
irregularities (70s/80s/90s, cent/mille/million (in)variability)."""
from decimal import Decimal

import pytest

from app.services.nombres import amount_to_words, number_to_words


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, "zéro"),
        (1, "un"),
        (17, "dix-sept"),
        (20, "vingt"),
        (21, "vingt et un"),
        (22, "vingt-deux"),
        (69, "soixante-neuf"),
        (70, "soixante-dix"),
        (71, "soixante et onze"),
        (79, "soixante-dix-neuf"),
        (80, "quatre-vingts"),
        (81, "quatre-vingt-un"),
        (90, "quatre-vingt-dix"),
        (91, "quatre-vingt-onze"),
        (99, "quatre-vingt-dix-neuf"),
        (100, "cent"),
        (101, "cent un"),
        (200, "deux cents"),
        (203, "deux cent trois"),
        (1000, "mille"),
        (1001, "mille un"),
        (2000, "deux mille"),
        (8117, "huit mille cent dix-sept"),
        (1_000_000, "un million"),
        (2_000_000, "deux millions"),
    ],
)
def test_number_to_words(n, expected):
    assert number_to_words(n) == expected


def test_montant_en_lettres_matches_the_design_mockup_example():
    assert amount_to_words(Decimal("8117.504")) == "Huit mille cent dix-sept dinars, 504 millimes"


def test_montant_en_lettres_singular_dinar():
    assert amount_to_words(Decimal("1.000")) == "Un dinar"


def test_montant_en_lettres_no_millimes_suffix_when_zero():
    assert amount_to_words(Decimal("500.000")) == "Cinq cents dinars"
