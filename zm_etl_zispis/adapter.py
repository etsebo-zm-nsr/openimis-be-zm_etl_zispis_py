"""ZISPIS-specific transformation.

Everything expressible as configuration lives in `apps.py`. What remains here is the
handful of things ZISPIS does that config cannot describe: roles that need a second
field to disambiguate, and identity values the source deliberately poisons.
"""
import hashlib
import logging

from api_etl.adapters import BaseMappingAdapter

logger = logging.getLogger(__name__)

# ZISPIS collapses gendered relationships into one code; openIMIS keeps them apart.
# `gender` resolves them, and this covers 90% of the roster: SON_OR_DAUGHTER and
# GRANDCHILD alone are ~52% of all records.
GENDERED_ROLES = {
    "SON_OR_DAUGHTER":   {"MALE": "SON", "FEMALE": "DAUGHTER"},
    "GRANDCHILD":        {"MALE": "GRANDSON", "FEMALE": "GRANDDAUGHTER"},
    "BROTHER_OR_SISTER": {"MALE": "BROTHER", "FEMALE": "SISTER"},
    "FATHER_OR_MOTHER":  {"MALE": "FATHER", "FEMALE": "MOTHER"},
    "GRANDPARENT":       {"MALE": "GRANDFATHER", "FEMALE": "GRANDMOTHER"},
}

# ZISPIS marks its own known-duplicate identities inside the national ID field rather
# than in a flag: a "/DUPLICATE" suffix, and a 999999/99/* placeholder. Used as-is both
# become a match key shared by many unrelated people, which is precisely how a registry
# merges two different human beings.
DUPLICATE_SUFFIX = "/DUPLICATE"
PLACEHOLDER_ID_PREFIX = "999999"

# tblLocations.LocationCode is CharField(max_length=50).
LOCATION_CODE_MAX = 50


class ZispisAdapter(BaseMappingAdapter):

    def map_role(self, raw_role):
        """Resolve ZISPIS's gender-ambiguous roles, else fall back to the config map."""
        key = str(raw_role).strip().upper() if raw_role not in (None, "") else ""
        if key in GENDERED_ROLES:
            gender = str(self._current_gender or "").strip().upper()
            mapped = GENDERED_ROLES[key].get(gender)
            if mapped:
                return mapped
            # Gender absent or unexpected: a neutral relative is honest, an invented
            # SON-or-DAUGHTER guess is not.
            return self.cfg.adapter.default_role or "OTHER_RELATIVE"
        return super().map_role(raw_role)

    def map_recipient(self, value):
        """ZISPIS designates the recipient by role rather than a dedicated flag."""
        if str(value or "").strip().upper() == "HEAD":
            return "1"
        return None

    def clean_national_id(self, value):
        """Strip ZISPIS's duplicate markers; treat placeholders as no identity at all."""
        if value in (None, ""):
            return None, None
        text = str(value).strip()
        flagged = None
        if text.upper().endswith(DUPLICATE_SUFFIX):
            text = text[: -len(DUPLICATE_SUFFIX)].strip()
            flagged = "zispis marked this national id as a duplicate"
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits.startswith(PLACEHOLDER_ID_PREFIX):
            return None, "zispis placeholder national id (999999...) treated as absent"
        return (text or None), flagged

    def location_code(self, row):
        """A village code unique across the whole country.

        ZISPIS publishes no location code, only names, and CWAC names repeat: MGWAZO
        occurs under both MSADILE and MSANDILE wards. openIMIS resolves a village with
        `LocationName = x AND LocationCode = y AND LocationType = 'V'`, so if the code
        were just the name, that join would match two village rows and the LEFT JOIN
        would insert the individual TWICE. Qualifying the code by its parents makes it
        unique; the district is included because ward names repeat across districts too.
        """
        parts = [self.clean_text(self.resolve_path(row, f"location/{level}"))
                 for level in ("district", "ward", "cwac")]
        parts = [str(p) for p in parts if p]
        if not parts:
            return None
        code = "/".join(parts)
        if len(code) <= LOCATION_CODE_MAX:
            return code
        # Truncating alone would reintroduce the collisions this exists to prevent,
        # so the discriminator is a digest of the full value.
        digest = hashlib.blake2s(code.encode("utf-8"), digest_size=6).hexdigest()
        return f"{code[:LOCATION_CODE_MAX - len(digest) - 1]}-{digest}"

    def transform_row(self, row):
        # map_role needs gender, which the base class does not pass down. Held per row
        # rather than threaded through the signature so the core SPI stays unchanged.
        self._current_gender = self.resolve_path(row, "gender")
        try:
            record = super().transform_row(row)
        finally:
            self._current_gender = None
        if record is None:
            return None

        record["location_code"] = self.location_code(row)

        national_id, note = self.clean_national_id(self.resolve_path(row, "nationalId"))
        record["national_id"] = self.normalise_national_id(national_id)
        if note:
            # Surfaced rather than silently dropped: a person whose only identifier is
            # unusable still belongs in the registry, flagged for a caseworker.
            #
            # Deliberately NOT `linkage_note`: the sink writes that key for its own
            # identity decisions, and it would overwrite this one - losing exactly the
            # explanation the checker needs. A placeholder national id is *why* an id
            # matches two hundred people, so the two notes have to survive together.
            record["data_quality_note"] = note

        return record

    _current_gender = None
