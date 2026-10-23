"""ZISPIS-specific transformation.

Everything expressible as configuration lives in `apps.py`. What remains here is the
handful of things ZISPIS does that config cannot describe: roles that need a second
field to disambiguate, and identity values the source deliberately poisons.
"""
import logging
from datetime import datetime

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

    def _dob_path(self):
        return (self.cfg.adapter.field_map or {}).get("dob")

    def _dob_as_sent(self, row):
        """The dateOfBirth exactly as ZISPIS sent it (whitespace-collapsed), or None."""
        path = self._dob_path()
        raw = self.clean_text(self.resolve_path(row, path)) if path else None
        return None if raw in (None, "") else str(raw)

    def resolve_dob(self, row):
        """The reported date of birth, or None. Never an estimate.

        The registry stores only what the source asserted. ZISPIS confirmed that records
        with no usable date of birth must still be registered (historical data predating
        CORE MIS often lacks one), and `individual.dob` is nullable for exactly that
        reason: "unknown" is stored as unknown, not as a guess that reads as fact.

        `parse_date` keeps its plausibility window, so an impossible date such as
        `6012-06-04` resolves to None here. The unusable value itself is not lost - see
        `transform_row`, which keeps it as `dob_as_sent`.

        Deliberately NOT derived from `yearOfBirth` or `age`. `yearOfBirth` is not
        independent of `dateOfBirth` (it equals year(dateOfBirth) on 99.6% of records,
        and carries the same corruption where the date is corrupt), and an age-based
        estimate is only good to about +-6 months. Either would put a generated value in
        a field every downstream consumer treats as a fact.
        """
        return self.parse_date(self._dob_as_sent(row))

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

        # Store what the source asserted, nothing generated. An unusable date becomes
        # NULL, and the raw value is kept beside it so the data owner can see what was
        # sent. `age` and `createdAt` are carried as-is by the field map
        # (`age`, `registered_at`); nothing is computed from them.
        record["dob"] = self.resolve_dob(row)
        sent = self._dob_as_sent(row)
        if record["dob"] is None and sent is not None:
            record["dob_as_sent"] = sent
        # year_of_birth feeds the identity key, so it is kept only if plausible. That
        # holds even when the date was reported: about 0.4% of records carry a corrupt
        # yearOfBirth (19895989) next to a valid dateOfBirth. Rejecting a corrupt value
        # is not generating one; no replacement is derived.
        if not self._plausible_year(record.get("year_of_birth")):
            record["year_of_birth"] = None

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

    def _plausible_year(self, value):
        try:
            year = int(str(value).strip())
        except (TypeError, ValueError):
            return False
        adapter = self.cfg.adapter
        return (adapter.min_year or 0) <= year <= (adapter.max_year or datetime.now().year)

    _current_gender = None
