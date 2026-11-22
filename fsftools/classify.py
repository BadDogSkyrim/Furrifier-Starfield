"""NPC classification engine — assigns each NPC to a class by first-match rules."""
from fnmatch import fnmatch
from typing import List

from fsftools.config import ClassRule


# Default class when no rule matches.
DEFAULT_CLASS = 'CLASS_CITIZEN'


class Classifier:
    """Evaluate first-match classification rules against NPC attributes."""

    def __init__(self, rules: List[ClassRule]):
        self.rules = rules

    def classify(self, npc_attrs: dict) -> str:
        """Classify an NPC by its attributes.

        npc_attrs should contain:
            'RACE': str          — race EditorID
            'FACTIONS': list[str] — faction EditorIDs
            'KEYWORDS': list[str] — keyword EditorIDs
            'EDITORID': str      — NPC's own EditorID
            'NAME': str          — display name
            'LOCATION': str      — inferred location (from faction/keyword mapping)

        Returns the class name (e.g. 'CLASS_UC_MILITARY').
        """
        for rule in self.rules:
            if self._matches(rule, npc_attrs):
                return rule.class_name
        return DEFAULT_CLASS

    def _matches(self, rule: ClassRule, attrs: dict) -> bool:
        """Test one rule against the NPC's attributes."""
        field = rule.field
        pattern = rule.pattern

        if field == 'RACE':
            return fnmatch(attrs.get('RACE', ''), pattern)

        elif field == 'FACTION':
            return any(fnmatch(f, pattern) for f in attrs.get('FACTIONS', []))

        elif field == 'KEYWORD':
            return any(fnmatch(k, pattern) for k in attrs.get('KEYWORDS', []))

        elif field == 'EDITORID':
            return fnmatch(attrs.get('EDITORID', ''), pattern)

        elif field == 'NAME':
            return fnmatch(attrs.get('NAME', ''), pattern)

        elif field == 'LOCATION':
            return fnmatch(attrs.get('LOCATION', ''), pattern)

        return False


def npc_attributes(npc_rec, plugins) -> dict:
    """Extract classification attributes from an esplib NPC_ record.

    Requires the PluginSet to resolve references. Factions and keywords
    need FACT and KYWD in the loaded signature set.
    """
    attrs = {
        'EDITORID': npc_rec.editor_id or '',
        'RACE': '',
        'FACTIONS': [],
        'KEYWORDS': [],
        'NAME': '',
        'LOCATION': '',
    }

    # Race
    race = plugins.resolve_reference(npc_rec, 'RNAM')
    if race:
        attrs['RACE'] = race.editor_id or ''

    # Display name — FULL subrecord (may be localized / empty in SF)
    full = npc_rec.get_subrecord('FULL')
    if full:
        try:
            attrs['NAME'] = full.get_string()
        except Exception:
            pass

    # Factions — SNAM entries (FormID at offset 0, rank at offset 4)
    for sr in npc_rec.get_subrecords('SNAM'):
        try:
            fact = plugins.resolve_form_id(sr.get_form_id(0), npc_rec.plugin)
            if fact and fact.editor_id:
                attrs['FACTIONS'].append(fact.editor_id)
        except Exception:
            pass

    # Keywords — KWDA subrecord (array of FormIDs)
    kwda = npc_rec.get_subrecord('KWDA')
    if kwda:
        n_kw = len(kwda.data) // 4
        for i in range(n_kw):
            try:
                kw = plugins.resolve_form_id(kwda.get_form_id(i * 4), npc_rec.plugin)
                if kw and kw.editor_id:
                    attrs['KEYWORDS'].append(kw.editor_id)
            except Exception:
                pass

    # Location inference from factions/keywords
    attrs['LOCATION'] = _infer_location(attrs['FACTIONS'], attrs['KEYWORDS'])

    return attrs


# ── Location inference ──────────────────────────────────────────────────────

# Map faction/keyword substrings to location names for the LOCATION field.
_LOCATION_HINTS = {
    'UC_Faction': 'NewAtlantis',
    'Freestar': 'Akila',
    'CrimsonFleet': 'TheKey',
    'Neon': 'Neon',
    'Akila': 'Akila',
    'NewAtlantis': 'NewAtlantis',
    'Cydonia': 'Cydonia',
    'Paradiso': 'Paradiso',
}


def _infer_location(factions: list, keywords: list) -> str:
    """Best-effort location from faction/keyword names. First match wins."""
    for name in factions + keywords:
        for hint, location in _LOCATION_HINTS.items():
            if hint in name:
                return location
    return ''
