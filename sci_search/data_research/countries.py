"""Global country identities, independent of any dataset's geographic coverage.

The bundled ISO 3166-1 names/codes snapshot comes from Debian iso-codes
(https://salsa.debian.org/iso-codes-team/iso-codes), available locally under
/usr/share/iso-codes/json/iso_3166-1.json. Its LGPL-2.1 license is retained
in resources/iso-codes-COPYING.txt. Names are identifiers, not a claim
about sovereignty or a dataset's geographic definitions.
"""

import json
import re
from functools import lru_cache
from importlib.resources import files

_RECORDS = json.loads(
    files(__package__).joinpath("resources/iso_3166-1.json").read_text(encoding="utf-8")
)["3166-1"]
COUNTRY_NAMES = {record["alpha_3"]: record["name"] for record in _RECORDS}

# Common English and retained Dutch labels supplement ISO's formal names.
_ALIASES = {
    "VIR": ("US Virgin Islands", "U.S. Virgin Islands", "United States Virgin Islands"),
    "VGB": ("British Virgin Islands",),
    "UMI": ("US Minor Outlying Islands", "U.S. Minor Outlying Islands"),
    "NLD": ("Nederland",),
    "DEU": ("Duitsland",),
    "GBR": ("UK", "Great Britain"),
    "USA": ("United States of America", "U.S.", "U.S.A."),
    "RUS": ("Russia",),
    "MDA": ("Moldova",),
    "VAT": ("Vatican City",),
    "TUR": ("Turkey", "Türkiye"),
    "CZE": ("Czech Republic",),
    "KOR": ("South Korea", "Republic of Korea"),
    "PRK": ("North Korea", "Democratic People's Republic of Korea"),
    "COD": ("Democratic Republic of the Congo", "Democratic Republic of Congo", "DR Congo"),
    "COG": ("Republic of the Congo", "Republic of Congo", "Congo-Brazzaville"),
    "IRN": ("Iran",),
    "SYR": ("Syria",),
    "LAO": ("Laos",),
    "VNM": ("Vietnam",),
    "BOL": ("Bolivia",),
    "VEN": ("Venezuela",),
    "TZA": ("Tanzania",),
    "PSE": ("Palestine",),
    "CIV": ("Ivory Coast", "Côte d’Ivoire"),
    "CPV": ("Cape Verde",),
    "SWZ": ("Swaziland",),
}
# These unqualified names do not distinguish the countries people may mean.
_AMBIGUOUS = {"congo", "korea"}
_CODES = {}
_NAMES = {}
for _record in _RECORDS:
    _code = _record["alpha_3"]
    for _alias in (_code, _record["alpha_2"]):
        _CODES[_alias] = _code
    for _alias in (
        *(_record[key] for key in ("name", "official_name", "common_name") if key in _record),
        *_ALIASES.get(_code, ()),
    ):
        if _alias.casefold() not in _AMBIGUOUS:
            if _alias.isupper():
                _CODES[_alias] = _code
            else:
                _NAMES[_alias.casefold()] = _code

# Longest alternatives consume qualified names before their shorter neighbours:
# South Sudan is not Sudan, and Papua New Guinea is not Guinea.
_NAME_PATTERN = "|".join(re.escape(name) for name in sorted(_NAMES, key=len, reverse=True))
_CODE_PATTERN = "|".join(re.escape(code) for code in sorted(_CODES, key=len, reverse=True))
_PATTERN = re.compile(r"(?<!\w)(?:(?i:" + _NAME_PATTERN + r")|" + _CODE_PATTERN + r")(?!\w)")


def canonical_country(value: str) -> str | None:
    """Resolve a whole country label or code; never resolve ambiguous shorthand."""
    value = value.strip()
    return _CODES.get(value.upper()) or _NAMES.get(value.casefold())


@lru_cache(maxsize=4096)
def country_mentions(text: str) -> frozenset[str]:
    """Identify complete names and uppercase ISO tokens in a source label.

    Lowercase words such as 'in', 'and', 'no', and 'us' inside prose are not codes.
    """
    return frozenset(
        code
        for match in _PATTERN.finditer(text)
        if (code := canonical_country(match.group())) is not None
    )
