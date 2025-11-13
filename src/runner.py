import argparse
import json
import logging
import os
import sys
from typing import List

# Ensure the src directory is on sys.path when executed from repo root
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(CURRENT_DIR)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

try:
    from extractors.amazon_parser import AmazonReviewScraper
    from extractors.review_utils import Review, deduplicate_reviews
    from outputs.exporters import export_reviews_to_json, export_reviews_to_ndjson
except ImportError as exc:
    raise SystemExit(f"Failed to import internal modules: {exc}")

DEFAULT_SETTINGS_PATH = os.path.join(CURRENT_DIR, "config", "settings.example.json")
DEFAULT_INPUTS_PATH = os.path.join(REPO_ROOT, "data", "inputs.sample.txt")
DEFAULT_OUTPUT_PATH = os.path.join(REPO_ROOT, "data", "sample_output.json")

def load_settings(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Settings file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        settings = json.load(f)
    return settings

def configure_logging(settings: dict) -> None:
    logging_settings = settings.get("logging", {})
    level_name = logging_settings.get("level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

def read_asins(path: str) -> List[str]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Input file not found: {path}")
    asins: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            asins.append(line)
    return asins

def run(
    settings_path: str,
    inputs_path: str,
    output_path: str | None = None,
) -> None:
    settings = load_settings(settings_path)
    configure_logging(settings)

    logger = logging.getLogger("runner")

    base_url = settings.get("base_url", "https://www.amazon.com/product-reviews/{asin}?pageNumber={page}")
    user_agent = settings.get("user_agent")
    max_reviews_per_asin = int(settings.get("max_reviews_per_asin", 1000))
    timeout = int(settings.get("request_timeout", 10))
    delay = float(settings.get("delay_between_requests", 1.0))
    stars = settings.get("stars") or [1, 2, 3, 4, 5]
    review_type = settings.get("review_type", "all")
    variants_mode = settings.get("variants_mode", "selected_only")
    daily_asin_limit = int(settings.get("daily_asin_limit", 1000))

    output_cfg = settings.get("output", {})
    output_format = output_cfg.get("format", "json").lower()
    output_indent = int(output_cfg.get("indent", 2))
    if output_path is None:
        output_path = os.path.join(REPO_ROOT, output_cfg.get("path", "data/sample_output.json"))

    logger.info("Loading ASINs from %s", inputs_path)
    asins = read_asins(inputs_path)

    if not asins:
        logger.warning("No ASINs found in input file. Nothing to do.")
        return

    if len(asins) > daily_asin_limit:
        logger.warning(
            "Number of ASINs (%d) exceeds configured daily limit (%d). "
            "Only the first %d ASINs will be processed.",
            len(asins),
            daily_asin_limit,
            daily_asin_limit,
        )
        asins = asins[:daily_asin_limit]

    scraper = AmazonReviewScraper(
        base_url=base_url,
        user_agent=user_agent,
        timeout=timeout,
        delay=delay,
        max_reviews_per_asin=max_reviews_per_asin,
        allowed_stars=stars,
        review_type=review_type,
        variants_mode=variants_mode,
    )

    all_reviews: List[Review] = []
    for idx, asin in enumerate(asins, start=1):
        logger.info("(%d/%d) Scraping reviews for ASIN %s", idx, len(asins), asin)
        try:
            reviews = scraper.scrape_reviews_for_asin(asin)
            logger.info("Fetched %d reviews for ASIN %s", len(reviews), asin)
            all_reviews.extend(reviews)
        except Exception as exc:
            logger.exception("Error while scraping ASIN %s: %s", asin, exc)

    if not all_reviews:
        logger.warning("No reviews collected. Exiting without writing output.")
        return

    logger.info("Deduplicating %d reviews", len(all_reviews))
    all_reviews = deduplicate_reviews(all_reviews)
    logger.info("Total unique reviews after deduplication: %d", len(all_reviews))

    logger.info("Writing %s reviews to %s (format=%s)", len(all_reviews), output_path, output_format)
    if output_format == "ndjson":
        export_reviews_to_ndjson(all_reviews, output_path)
    else:
        export_reviews_to_json(all_reviews, output_path, indent=output_indent)

    logger.info("Done.")

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Amazon.com Reviews Easy Scraper - runner",
    )
    parser.add_argument(
        "--settings",
        default=DEFAULT_SETTINGS_PATH,
        help=f"Path to settings JSON file (default: {DEFAULT_SETTINGS_PATH})",
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUTS_PATH,
        help=f"Path to input ASIN list (default: {DEFAULT_INPUTS_PATH})",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to output file. Overrides the path in settings.json if provided.",
    )
    return parser.parse_args(argv)

if __name__ == "__main__":
    args = parse_args()
    run(
        settings_path=args.settings,
        inputs_path=args.input,
        output_path=args.output,
    )