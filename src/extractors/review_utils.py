from dataclasses import dataclass, asdict
from typing import Iterable, List, Optional, Set, Tuple

@dataclass
class Review:
    asin: str
    review_id: str
    reviewer_name: Optional[str]
    rating: int
    title: Optional[str]
    review_text: Optional[str]
    verified_purchase: bool
    date: Optional[str]  # ISO date string: YYYY-MM-DD
    variant: Optional[str]
    helpful_votes: int

    def to_dict(self) -> dict:
        return asdict(self)

def clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    # Collapse whitespace and strip leading/trailing spaces
    cleaned = " ".join(value.split())
    return cleaned or None

def deduplicate_reviews(reviews: Iterable[Review]) -> List[Review]:
    """
    Remove duplicate reviews based on (asin, review_id). Preserves first occurrence.
    """
    seen: Set[Tuple[str, str]] = set()
    unique: List[Review] = []
    for r in reviews:
        key = (r.asin, r.review_id or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique

def filter_by_stars(reviews: Iterable[Review], allowed_stars: Iterable[int]) -> List[Review]:
    allowed = set(int(s) for s in allowed_stars)
    return [r for r in reviews if r.rating in allowed]