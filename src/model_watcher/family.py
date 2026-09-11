"""Deterministic release family folding and representative selection for monitor deduplication.

Rules:
1. Only folds explicit inference effort / reasoning configuration suffixes/descriptors:
   - max / max-effort
   - xhigh / xhigh-effort
   - high / high-effort
   - medium / medium-effort
   - low / low-effort
   - non-reasoning
   - thinking / thinking-auto
2. Strictly preserves distinct model variants:
   - Flash vs Pro
   - Text vs Vision
   - Mini vs full model
   - Explicit version numbers
   - Date versions (e.g. -0731)
   - Preview vs Stable
   - Generation jumps (e.g. V4 vs V4.1)
3. Safe version format normalization:
   - '.' vs '-' in version numbers (e.g. 'v4-1' -> 'v4.1', 'grok-4-6' -> 'grok-4.6')
4. Deterministic representative selection based on effort priority:
   max (5) > xhigh (4) > high (3) > default (2) > medium (1) > low (0) > non-reasoning (-1)
"""
import re
from typing import Dict, List, Tuple
from model_watcher.types import ModelMetadata

# Effort suffix in canonical IDs
EFFORT_SUFFIX_RE = re.compile(
    r"-(?:xhigh-effort|high-effort|medium-effort|low-effort|max-effort|xhigh|high|medium|low|max|non-reasoning|thinking(?:-auto|-64k)?)$",
    re.IGNORECASE,
)

# Parenthetical or trailing effort descriptors in display names
EFFORT_PAREN_RE = re.compile(
    r"\s*\((?:(?:adaptive\s+)?reasoning,?\s*)?(?:xhigh|high|medium|low|max-effort|max)(?:\s+effort)?(?:,?\s*default\s+fallback)?\)",
    re.IGNORECASE,
)

NON_REASONING_PAREN_RE = re.compile(
    r"\s*\((?:non-reasoning|reasoning)\)",
    re.IGNORECASE,
)

TRAILING_EFFORT_WORD_RE = re.compile(
    r"\s+(?:xhigh-effort|high-effort|medium-effort|low-effort|max-effort|xhigh|high|medium|low|max|non-reasoning)$",
    re.IGNORECASE,
)


def get_effort_priority(canonical_id: str, display_name: str = "") -> int:
    """Computes deterministic effort priority for representative selection:
    max (5) > xhigh (4) > high (3) > default (2) > medium (1) > low (0) > non-reasoning (-1)
    """
    text = f"{canonical_id} {display_name}".lower()

    # 1. max / max-effort
    if re.search(r"\b(max|max-effort)\b|\(max\b", text):
        return 5

    # 2. xhigh / xhigh-effort
    if re.search(r"\b(xhigh|xhigh-effort)\b|\(xhigh\b", text):
        return 4

    # 3. high / high-effort
    # Avoid matching 'xhigh' as 'high'
    if re.search(r"(?<!x)\b(high|high-effort)\b|(?<!x)\(high\b", text):
        return 3

    # 4. medium / medium-effort
    if re.search(r"-(?:medium|medium-effort)$|\(medium\b|\s+medium$", text):
        return 1

    # 5. low / low-effort
    if re.search(r"\b(low|low-effort)\b|\(low\b", text):
        return 0

    # 6. non-reasoning
    if "non-reasoning" in text:
        return -1

    # Default / standard configuration
    return 2


def get_release_family_id(canonical_id: str, display_name: str = "") -> str:
    """Computes a lightweight, deterministic monitor release family identity."""
    cid = canonical_id.lower().strip()

    # 1. Strip effort suffix from canonical_id
    base_id = EFFORT_SUFFIX_RE.sub("", cid)

    # 2. Format normalization for '.' vs '-' in explicit versions
    # e.g. 'deepseek-v4-1-flash' -> 'deepseek-v4.1-flash'
    base_id = re.sub(r"v(\d+)-(\d+)", r"v\1.\2", base_id)
    # e.g. 'grok-4-6' -> 'grok-4.6' (only single/double digit version numbers, not dates like -0731)
    base_id = re.sub(r"\b([a-zA-Z]+)-(\d{1,2})-(\d{1,2})\b", r"\1-\2.\3", base_id)

    return base_id


def select_family_representative(candidates: List[ModelMetadata]) -> ModelMetadata:
    """Deterministically selects the single representative model for a release family.
    
    Sorting key:
    1. Effort priority DESC (max > xhigh > high > default > medium > low > non-reasoning)
    2. Release date DESC (if available)
    3. Display name ASC
    4. Canonical ID ASC
    """
    if not candidates:
        raise ValueError("Cannot select representative from empty candidate list")

    sorted_candidates = sorted(
        candidates,
        key=lambda m: (
            -get_effort_priority(m.canonical_id, m.display_name),
            -(int(m.release_date.replace("-", "").replace("_", "")[:8]) if m.release_date and re.match(r"^\d{4}[-_]\d{2}[-_]\d{2}", m.release_date) else 0),
            m.display_name,
            m.canonical_id,
        )
    )
    return sorted_candidates[0]


def group_candidates_by_family(candidates: List[ModelMetadata]) -> Dict[str, List[ModelMetadata]]:
    """Groups candidate models by their release family ID."""
    families: Dict[str, List[ModelMetadata]] = {}
    for m in candidates:
        fam_id = get_release_family_id(m.canonical_id, m.display_name)
        if fam_id not in families:
            families[fam_id] = []
        families[fam_id].append(m)
    return families
