import logging
import time
from typing import Iterable, List, Optional

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from .review_utils import (
    Review,
    clean_text,
    deduplicate_reviews,
    filter_by_stars,
)

logger = logging.getLogger(__name__)

class AmazonReviewScraper:
    """
    Scrapes Amazon product reviews from the public product reviews pages.

    This implementation is intentionally conservative: it follows links,
    parses the HTML structure used on Amazon product review pages, and
    attempts to extract structured fields while handling minor layout changes.
    """

    def __init__(
        self,
        base_url: str,
        user_agent: Optional[str],
        timeout: int,
        delay: float,
        max_reviews_per_asin: int,
        allowed_stars: Iterable[int],
        review_type: str,
        variants_mode: str,
    ) -> None:
        self.base_url = base_url or "https://www.amazon.com/product-reviews/{asin}?pageNumber={page}"
        self.timeout = int(timeout)
        self.delay = float(delay)
        self.max_reviews_per_asin = int(max_reviews_per_asin)
        self.allowed_stars = sorted(set(int(s) for s in allowed_stars))
        self.review_type = review_type
        self.variants_mode = variants_mode

        headers = {
            "User-Agent": user_agent
            or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        self.session = requests.Session()
        self.session.headers.update(headers)

    def _build_url(self, asin: str, page: int) -> str:
        """
        Build the review page URL using the configured base_url template.

        The template can contain {asin} and {page} placeholders.
        """
        url = self.base_url.format(asin=asin, page=page)
        return url

    def _fetch_page(self, asin: str, page: int) -> Optional[str]:
        url = self._build_url(asin, page)
        logger.debug("Requesting URL: %s", url)
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning(
                    "Received non-200 status code for ASIN=%s page=%d: %s",
                    asin,
                    page,
                    resp.status_code,
                )
                return None
            return resp.text
        except requests.RequestException as exc:
            logger.warning(
                "Request error for ASIN=%s page=%d: %s",
                asin,
                page,
                exc,
            )
            return None

    def _parse_rating(self, rating_text: str) -> Optional[int]:
        """
        Parse strings like '5.0 out of 5 stars' to an integer rating.
        """
        if not rating_text:
            return None
        rating_text = rating_text.strip()
        try:
            num_str = rating_text.split(" ")[0]
            value = float(num_str)
            return int(round(value))
        except Exception:
            logger.debug("Could not parse rating from text: %r", rating_text)
            return None

    def _parse_helpful_votes(self, helpful_text: str) -> int:
        """
        Parse strings like '12 people found this helpful' or 'One person found this helpful'.
        """
        if not helpful_text:
            return 0
        helpful_text = helpful_text.strip().lower()
        if "one person" in helpful_text:
            return 1
        digits = "".join(ch for ch in helpful_text if ch.isdigit())
        if digits:
            try:
                return int(digits)
            except ValueError:
                return 0
        return 0

    def _parse_date(self, date_text: str) -> Optional[str]:
        """
        Parse flexible date strings to ISO format (YYYY-MM-DD).
        """
        if not date_text:
            return None
        try:
            dt = date_parser.parse(date_text, fuzzy=True)
            return dt.date().isoformat()
        except (ValueError, TypeError) as exc:
            logger.debug("Could not parse date %r: %s", date_text, exc)
            return None

    def _parse_reviews_from_html(self, asin: str, html: str) -> List[Review]:
        soup = BeautifulSoup(html, "html.parser")
        review_elements = soup.select('div[data-hook="review"]')
        reviews: List[Review] = []

        for el in review_elements:
            review_id = el.get("id") or ""
            reviewer_el = el.select_one("span.a-profile-name")
            reviewer_name = clean_text(reviewer_el.get_text()) if reviewer_el else None

            rating_el = el.select_one('i[data-hook="review-star-rating"] span')
            if rating_el is None:
                rating_el = el.select_one('i[data-hook="cmps-review-star-rating"] span')
            rating_text = clean_text(rating_el.get_text()) if rating_el else ""
            rating = self._parse_rating(rating_text) or 0

            title_el = el.select_one('a[data-hook="review-title"] span')
            if not title_el:
                title_el = el.select_one('span[data-hook="review-title"] span')
            title = clean_text(title_el.get_text()) if title_el else None

            body_el = el.select_one('span[data-hook="review-body"] span')
            if not body_el:
                body_el = el.select_one('span[data-hook="review-body"]')
            review_text = clean_text(body_el.get_text()) if body_el else None

            verified_el = el.select_one('span[data-hook="avp-badge"]')
            verified_purchase = bool(verified_el)

            date_el = el.select_one('span[data-hook="review-date"]')
            date_text = clean_text(date_el.get_text()) if date_el else ""
            date_iso = self._parse_date(date_text)

            variant_el = el.select_one('span.a-color-secondary[data-hook="format-strip"]')
            if not variant_el:
                # Sometimes the variant is inside a small bullet section
                variant_el = el.select_one('a.a-size-mini')
            variant = clean_text(variant_el.get_text()) if variant_el else None

            helpful_el = el.select_one('span[data-hook="helpful-vote-statement"]')
            helpful_text = clean_text(helpful_el.get_text()) if helpful_el else ""
            helpful_votes = self._parse_helpful_votes(helpful_text)

            review = Review(
                asin=asin,
                review_id=review_id,
                reviewer_name=reviewer_name,
                rating=rating,
                title=title,
                review_text=review_text,
                verified_purchase=verified_purchase,
                date=date_iso,
                variant=variant,
                helpful_votes=helpful_votes,
            )
            reviews.append(review)

        return reviews

    def _has_next_page(self, html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        # Amazon uses 'li.a-last a' for pagination; if there's no clickable link, we're at the last page
        next_link = soup.select_one("li.a-last a")
        return next_link is not None

    def scrape_reviews_for_asin(self, asin: str) -> List[Review]:
        """
        Scrape reviews for a single ASIN across multiple pages until we hit
        the configured limits or there are no more pages.
        """
        all_reviews: List[Review] = []
        page = 1

        while len(all_reviews) < self.max_reviews_per_asin:
            html = self._fetch_page(asin, page)
            if not html:
                logger.info("Stopping pagination for ASIN=%s due to fetch error at page %d.", asin, page)
                break

            page_reviews = self._parse_reviews_from_html(asin, html)
            logger.debug(
                "Parsed %d reviews from ASIN=%s page=%d",
                len(page_reviews),
                asin,
                page,
            )

            if not page_reviews:
                logger.info(
                    "No reviews found on ASIN=%s page=%d. Assuming end of pages.",
                    asin,
                    page,
                )
                break

            all_reviews.extend(page_reviews)
            all_reviews = deduplicate_reviews(all_reviews)

            if len(all_reviews) >= self.max_reviews_per_asin:
                logger.info(
                    "Reached max_reviews_per_asin=%d for ASIN=%s",
                    self.max_reviews_per_asin,
                    asin,
                )
                break

            if not self._has_next_page(html):
                logger.info("No next page link for ASIN=%s after page %d", asin, page)
                break

            page += 1
            if self.delay > 0:
                time.sleep(self.delay)

        if self.allowed_stars and set(self.allowed_stars) != set(range(1, 6)):
            all_reviews = filter_by_stars(all_reviews, self.allowed_stars)

        return all_reviews