"""French number-to-words conversion for "montant en lettres".

This is genuine, deterministic business logic — not a stand-in for OCR.
Given a traite's own known ``montant`` (Decimal, 3 decimal places = dinars
and millimes, the Tunisian dinar convention already used throughout this
project), the correct words are fully computable; there is nothing to
simulate here.
"""
from decimal import Decimal

_UNITS = [
    "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
    "dix-sept", "dix-huit", "dix-neuf",
]
_TENS = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _under_hundred(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    if n < 70:
        tens_digit, unit_digit = divmod(n, 10)
        base = _TENS[tens_digit]
        if unit_digit == 0:
            return base
        if unit_digit == 1:
            return f"{base} et un"
        return f"{base}-{_UNITS[unit_digit]}"
    if n < 80:
        remainder = n - 60  # 10..19
        if remainder == 11:
            return "soixante et onze"
        return f"soixante-{_UNITS[remainder]}"
    if n == 80:
        return "quatre-vingts"
    if n < 90:
        return f"quatre-vingt-{_UNITS[n - 80]}"
    return f"quatre-vingt-{_UNITS[n - 80]}"  # 90..99 -> _UNITS[10..19]


def _under_thousand(n: int) -> str:
    if n < 100:
        return _under_hundred(n)
    hundreds, remainder = divmod(n, 100)
    prefix = "cent" if hundreds == 1 else f"{_UNITS[hundreds]} cent"
    if remainder == 0:
        # "cent" never takes an 's' (100 = "cent"); "deux cents" does, but
        # only when nothing follows it (203 = "deux cent trois", no 's").
        return f"{prefix}s" if hundreds > 1 else prefix
    return f"{prefix} {_under_hundred(remainder)}"


def _group(n: int, singular: str, plural: str | None = None) -> str:
    if n == 0:
        return ""
    if singular == "mille":
        # "mille" is invariable and never preceded by "un" (1000 = "mille",
        # not "un mille"), unlike "cent" and "million".
        return "mille" if n == 1 else f"{_under_thousand(n)} mille"
    suffix = singular if n == 1 else (plural or f"{singular}s")
    return f"{_under_thousand(n)} {suffix}"


def number_to_words(n: int) -> str:
    if n == 0:
        return "zéro"
    millions, remainder = divmod(n, 1_000_000)
    thousands, units = divmod(remainder, 1000)
    parts = [
        _group(millions, "million", "millions"),
        _group(thousands, "mille"),
    ]
    if units or not any(parts):
        parts.append(_under_thousand(units))
    return " ".join(p for p in parts if p)


def amount_to_words(montant: Decimal) -> str:
    """E.g. Decimal("8117.504") -> "Huit mille cent dix-sept dinars, 504 millimes"."""
    dinars = int(montant)
    millimes = round((montant - dinars) * 1000)

    word = number_to_words(dinars)
    result = f"{word[0].upper()}{word[1:]} {'dinar' if dinars == 1 else 'dinars'}"
    if millimes:
        result += f", {millimes} millimes"
    return result
