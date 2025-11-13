import json
import logging
from pathlib import Path
from typing import Iterable, List

from extractors.review_utils import Review

logger = logging.getLogger(__name__)

def _ensure_parent_dir(path: Path) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

def export_reviews_to_json(reviews: Iterable[Review], output_path: str, indent: int = 2) -> None:
    path = Path(output_path)
    _ensure_parent_dir(path)

    data: List[dict] = [r.to_dict() for r in reviews]
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    logger.info("JSON export complete: %s", path)

def export_reviews_to_ndjson(reviews: Iterable[Review], output_path: str) -> None:
    path = Path(output_path)
    _ensure_parent_dir(path)

    with path.open("w", encoding="utf-8") as f:
        for r in reviews:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
    logger.info("NDJSON export complete: %s", path)