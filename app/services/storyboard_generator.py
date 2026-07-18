"""Deterministic storyboard templates — the AI/LLM generation boundary.

generate_storyboard() is the single swap point for plugging in a real LLM
provider later; template logic must not leak into other modules.
"""

from collections.abc import Callable
from pathlib import Path

from app.models import Scene, Storyboard
from app.services import artifact_store
from app.utils.logging import get_logger

logger = get_logger(__name__)


class StoryboardGenerationError(Exception):
    pass


def _ph_scale_storyboard() -> Storyboard:
    return Storyboard(
        title="How Does the pH Scale Work?",
        concept="ph_scale",
        scenes=[
            Scene(
                heading="What Is pH?",
                visual_type="title",
                visual_text="The pH Scale",
                narration=(
                    "pH measures how acidic or basic a solution is. "
                    "The scale usually runs from 0 to 14."
                ),
            ),
            Scene(
                heading="The Scale Is Logarithmic",
                visual_type="ph_scale",
                visual_text="0 -- Acidic | 7 -- Neutral | 14 -- Basic",
                narration=(
                    "The pH scale is logarithmic: each one-unit drop in pH means "
                    "roughly a tenfold increase in hydrogen ion concentration. "
                    "A solution with pH 4 has about ten times more H+ ions than one with pH 5."
                ),
            ),
            Scene(
                heading="Acidic, Neutral, and Basic",
                visual_type="ph_scale",
                visual_text="pH below 7: acidic | pH 7: neutral | pH above 7: basic",
                narration=(
                    "A pH below 7 is acidic, exactly 7 is neutral, and above 7 is "
                    "basic or alkaline. More hydrogen ions generally means a more "
                    "acidic solution."
                ),
            ),
            Scene(
                heading="Everyday Examples",
                visual_type="summary",
                visual_text="Lemon juice: acidic. Water: neutral. Soap: basic.",
                narration=(
                    "Lemon juice is acidic, pure water is neutral, and soap is basic — "
                    "everyday examples of the pH scale in action."
                ),
            ),
        ],
    )


def _covalent_bonds_storyboard() -> Storyboard:
    return Storyboard(
        title="Why Do Atoms Form Covalent Bonds?",
        concept="covalent_bonds",
        scenes=[
            Scene(
                heading="Sharing, Not Taking",
                visual_type="title",
                visual_text="Covalent Bonds",
                narration=(
                    "Atoms form covalent bonds by sharing pairs of electrons with "
                    "each other, rather than fully giving them away."
                ),
            ),
            Scene(
                heading="A More Stable Configuration",
                visual_type="atom_sharing",
                visual_text="Atom A -- shared electron pair -- Atom B",
                narration=(
                    "Sharing electrons generally helps atoms reach a more stable "
                    "electron configuration in their outer shell, similar to how "
                    "noble gases are already stable on their own."
                ),
            ),
            Scene(
                heading="Hydrogen Example",
                visual_type="atom_sharing",
                visual_text="H : H (one shared electron pair)",
                narration=(
                    "For example, two hydrogen atoms can each share one electron, "
                    "forming a single shared pair between them. This shared pair "
                    "holds the two atoms together, creating a stable H2 molecule."
                ),
            ),
            Scene(
                heading="Where Covalent Bonds Form",
                visual_type="summary",
                visual_text="Typically between nonmetal atoms.",
                narration=(
                    "Covalent bonds typically form between nonmetal atoms, such as "
                    "carbon, oxygen, nitrogen, and hydrogen. Water, carbon dioxide, "
                    "and methane are everyday molecules held together by covalent bonds."
                ),
            ),
        ],
    )


def _ionic_vs_covalent_storyboard() -> Storyboard:
    return Storyboard(
        title="Ionic vs Covalent Bonding",
        concept="ionic_vs_covalent",
        scenes=[
            Scene(
                heading="Two Ways to Bond",
                visual_type="title",
                visual_text="Ionic vs Covalent Bonding",
                narration=(
                    "Ionic bonding and covalent bonding are two different ways atoms "
                    "interact to form compounds."
                ),
            ),
            Scene(
                heading="Electron Transfer (Ionic)",
                visual_type="atom_sharing",
                visual_text="Na -- electron transfer arrow --> Cl, forming Na+ and Cl-",
                narration=(
                    "In ionic bonding, one atom transfers an electron to another. "
                    "Sodium transfers an electron to chlorine, forming a positive "
                    "sodium ion and a negative chloride ion."
                ),
            ),
            Scene(
                heading="Electron Sharing (Covalent)",
                visual_type="atom_sharing",
                visual_text="H : H (shared electron pair, no transfer)",
                narration=(
                    "In covalent bonding, atoms share electrons instead of transferring "
                    "them, as in molecules like water or hydrogen."
                ),
            ),
            Scene(
                heading="Transfer vs Share",
                visual_type="comparison_table",
                visual_text=(
                    "Ionic: electron transfer, charged ions | "
                    "Covalent: electron sharing, shared electron pairs"
                ),
                narration=(
                    "Ionic bonding involves electron transfer and forms charged ions, "
                    "while covalent bonding involves electron sharing and forms shared "
                    "electron pairs."
                ),
            ),
            Scene(
                heading="Examples",
                visual_type="summary",
                visual_text="Ionic: sodium chloride. Covalent: water, hydrogen.",
                narration=(
                    "Sodium chloride is a classic example of ionic bonding, while "
                    "water and hydrogen are examples of covalent bonding."
                ),
            ),
        ],
    )


def _safe_fallback_storyboard(concept: str) -> Storyboard:
    """Minimal, generic 3-scene template. Deliberately different from any
    primary template — a bug in a primary template must not also break this."""
    return Storyboard(
        title="Chemistry Concept Overview",
        concept=concept,
        scenes=[
            Scene(
                heading="Overview",
                visual_type="title",
                visual_text="Chemistry Concept Overview",
                narration="This video explains a core chemistry concept.",
            ),
            Scene(
                heading="Key Idea",
                visual_type="summary",
                visual_text="Detailed content is temporarily unavailable.",
                narration="We are unable to generate detailed content for this concept right now.",
            ),
            Scene(
                heading="Summary",
                visual_type="summary",
                visual_text="Please try again later.",
                narration="Thank you for your patience while we resolve this issue.",
            ),
        ],
    )


_PRIMARY_TEMPLATES: dict[str, Callable[[], Storyboard]] = {
    "ph_scale": _ph_scale_storyboard,
    "covalent_bonds": _covalent_bonds_storyboard,
    "ionic_vs_covalent": _ionic_vs_covalent_storyboard,
}


def generate_storyboard(concept: str) -> Storyboard:
    try:
        return _PRIMARY_TEMPLATES[concept]()
    except Exception as e:
        logger.error(f"Primary storyboard template failed for {concept}: {e}")
        try:
            return _safe_fallback_storyboard(concept)
        except Exception as fallback_error:
            raise StoryboardGenerationError(
                f"Both primary and fallback storyboard generation failed for {concept}"
            ) from fallback_error


def save_storyboard(job_id: str, storyboard: Storyboard) -> Path:
    path = artifact_store.storyboard_path(job_id)
    artifact_store.atomic_write_json(path, storyboard.model_dump(mode="json"))
    return path
