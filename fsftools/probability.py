"""Deterministic race assignment — hash-based weighted probability."""
import hashlib
from typing import Dict, Optional, Tuple

from fsftools.config import SchemeConfig, RaceConfig


class RaceAssigner:
    """Assign a furry race (and breed) to each NPC deterministically.

    The same EditorID always gets the same race and breed across runs.
    Families share a race. Pinned NPCs override the probability system.
    """

    def __init__(self, scheme: SchemeConfig, races: Dict[str, RaceConfig]):
        self.scheme = scheme
        self.races = races

        # Build family reverse-lookup: npc_editorid -> family lead editorid
        # Families share race + breed but keep their own appearance signature.
        self._family_lead: Dict[str, str] = {}
        for family_name, members in scheme.families.items():
            if members:
                lead = members[0]
                for m in members:
                    self._family_lead[m] = lead

        # Build alias reverse-lookup: npc_editorid -> alias lead editorid
        # Aliases share EVERYTHING (same NPC in different contexts).
        self._alias_lead: Dict[str, str] = {}
        for alias_name, members in scheme.aliases.items():
            if members:
                lead = members[0]
                for m in members:
                    self._alias_lead[m] = lead

    def signature_for(self, npc_editorid: str) -> str:
        """The identity used for all hash-based choices.

        Aliases: use lead (everything shared).
        Families: use lead for race/breed only (appearance uses own ID).
        Others: use own ID.
        """
        if npc_editorid in self._alias_lead:
            return self._alias_lead[npc_editorid]
        return self._family_lead.get(npc_editorid, npc_editorid)

    def appearance_signature_for(self, npc_editorid: str) -> str:
        """The identity used for appearance choices (tone, headparts, tints).

        Aliases share appearance. Families do NOT (each member looks different).
        """
        if npc_editorid in self._alias_lead:
            return self._alias_lead[npc_editorid]
        return npc_editorid

    def assign(self, npc_editorid: str, class_name: str) -> Optional[Tuple[str, Optional[str]]]:
        """Assign a race (and optional breed) for an NPC.

        Returns (race_editorid, breed_name) or None if the NPC should stay human.
        """
        # Excluded?
        if npc_editorid in self.scheme.exclude_npcs:
            return None

        # Pinned?
        if npc_editorid in self.scheme.npc_assignments:
            race_edid = self.scheme.npc_assignments[npc_editorid]
            breed = self._pick_breed(npc_editorid, race_edid)
            return (race_edid, breed)

        # Race/breed signature: aliases and families both use leader
        effective_id = self.signature_for(npc_editorid)

        # The class's own weights, else the default
        weights = self.scheme.class_probabilities.get(class_name) or self.scheme.proportions
        if not weights:
            return None

        # Pick race
        race_edid = _weighted_pick(effective_id, weights)
        if race_edid is None or race_edid == '_HUMAN':
            return None

        # Pick breed within race
        breed = self._pick_breed(effective_id, race_edid)
        return (race_edid, breed)

    def _pick_breed(self, editorid: str, race_edid: str) -> Optional[str]:
        """Pick a breed within a race using the NPC's hash."""
        race_cfg = self.races.get(race_edid)
        if not race_cfg or not race_cfg.breeds:
            return None

        breed_weights = {b.name: b.weight for b in race_cfg.breeds}
        return _weighted_pick(editorid + ':breed', breed_weights)

    def assign_skin_tone(self, npc_editorid: str, race_edid: str,
                         breed_name: Optional[str], sex: str) -> int:
        """Pick a skin tone index for the custom race, from those the sex and breed allow.

        Uses appearance signature (aliases share, families don't).
        """
        editorid = self.appearance_signature_for(npc_editorid)
        race_cfg = self.races.get(race_edid)
        if not race_cfg:
            return 0

        breed = next((b for b in race_cfg.breeds if b.name == breed_name), None)
        allowed = race_cfg.tones_for(sex, breed)
        if not allowed:
            return 0

        # Uniform pick from allowed tones
        idx = _stable_hash(editorid + ':tone') % len(allowed)
        return allowed[idx]

    def assign_phenotype(self, npc_editorid: str, race_edid: str,
                         breed_name: Optional[str], sex: str) -> Optional[str]:
        """Pick a phenotype for the NPC within its breed's allowed set.

        Uses appearance signature. sex is 'MALE' or 'FEMALE'.
        Returns a phenotype prefix like 'male_fox_md1'.
        """
        editorid = self.appearance_signature_for(npc_editorid)
        race_cfg = self.races.get(race_edid)
        if not race_cfg:
            return None

        # Get per-sex phenotype list from breed: [["male_fox_md1", 50], ...]
        phenotype_list = None
        if breed_name and race_cfg.breeds:
            for b in race_cfg.breeds:
                if b.name == breed_name:
                    if sex == 'FEMALE':
                        phenotype_list = b.phenotypes_female
                    else:
                        phenotype_list = b.phenotypes_male
                    break

        if not phenotype_list:
            return None

        # Weighted pick from the list
        weights = {name: int(w) for name, w in phenotype_list}
        return _weighted_pick(editorid + ':phenotype', weights)


# ── Hashing and weighted selection ──────────────────────────────────────────

def _stable_hash(key: str) -> int:
    """Deterministic hash of a string, stable across Python versions and runs."""
    return int.from_bytes(hashlib.sha256(key.encode('utf-8')).digest()[:8], 'little')


def _weighted_pick(key: str, weights: Dict[str, int]) -> Optional[str]:
    """Pick from a {name: weight} dict using a deterministic hash of key.

    Returns None if weights is empty or all weights are zero.
    """
    # Filter out zero weights and sort for determinism
    items = sorted((name, w) for name, w in weights.items() if w > 0)
    if not items:
        return None

    total = sum(w for _, w in items)
    if total <= 0:
        return None

    h = _stable_hash(key) % total
    cumulative = 0
    for name, w in items:
        cumulative += w
        if h < cumulative:
            return name

    return items[-1][0]  # shouldn't reach here, but safety
