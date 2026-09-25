from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import html
from pathlib import Path
import re
import time

import requests

from core.config import Settings
from core.utils import normalize_whitespace, read_json, write_json

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    title: str
    summary: str
    authors: list[str]
    categories: list[str]
    primary_category: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str
    comment: str


def _strip_markup(value: str) -> str:
    # Crossref abstracts are JATS XML: drop the "Abstract" heading, then every remaining tag.
    text = re.sub(r"<jats:title>.*?</jats:title>", " ", value or "", flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_whitespace(html.unescape(text))


def _first_text(value) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return _strip_markup(str(value or ""))


def _date_from_parts(value: dict | None) -> str | None:
    if not value:
        return None
    parts = (value.get("date-parts") or [[]])[0]
    if parts and parts[0]:
        year, month, day = (list(parts) + [1, 1])[:3]
        return f"{int(year):04d}-{int(month or 1):02d}-{int(day or 1):02d}"
    date_time = value.get("date-time")
    return date_time[:10] if date_time else None


def _published_date(item: dict) -> str | None:
    for key in ("published", "published-online", "published-print", "issued", "created"):
        date = _date_from_parts(item.get(key))
        if date:
            return date
    return None


def _author_names(item: dict) -> list[str]:
    names = []
    for author in item.get("author") or []:
        name = normalize_whitespace(f"{author.get('given', '')} {author.get('family', '')}") or author.get("name", "")
        if name:
            names.append(normalize_whitespace(name))
    return names


def _pdf_url(item: dict, fallback: str) -> str:
    for link in item.get("link") or []:
        if link.get("content-type") == "application/pdf" and link.get("URL"):
            return link["URL"]
    return fallback


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse a Crossref `/works` payload into `PaperRecord`s, skipping records without DOI/title/abstract/date."""
    records: list[PaperRecord] = []
    seen: set[str] = set()
    for item in (payload.get("message") or {}).get("items") or []:
        paper_id = normalize_whitespace(item.get("DOI") or "")
        title = _first_text(item.get("title"))
        summary = _strip_markup(item.get("abstract") or "")
        published = _published_date(item)
        if not paper_id or not title or not summary or not published or paper_id.lower() in seen:
            continue
        seen.add(paper_id.lower())

        categories = [normalize_whitespace(subject) for subject in item.get("subject") or [] if subject]
        updated = (
            _date_from_parts(item.get("updated"))
            or _date_from_parts(item.get("deposited"))
            or _date_from_parts(item.get("created"))
            or published
        )
        abs_url = item.get("URL") or f"https://doi.org/{paper_id}"
        records.append(
            PaperRecord(
                paper_id=paper_id,
                title=title,
                summary=summary,
                authors=_author_names(item),
                categories=categories,
                primary_category=categories[0] if categories else "Uncategorized",
                published=published,
                updated=updated,
                abs_url=abs_url,
                pdf_url=_pdf_url(item, abs_url),
                comment=f"Crossref record {paper_id}",
            )
        )
    return records


def _fetch_live_payload(settings: Settings) -> dict:
    params = {
        "query": settings.source_query,
        "filter": settings.source_filter,
        "rows": settings.max_results,
        "sort": "published",
        "order": "desc",
    }
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(CROSSREF_WORKS_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code in RETRYABLE_STATUS_CODES:
                raise requests.HTTPError(f"Crossref returned {response.status_code}", response=response)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"Crossref API unavailable after {MAX_RETRIES} attempts: {last_error}")


def _save_records(records: list[PaperRecord], path: Path) -> None:
    # Only rewrite the lineage file when its content actually changes, so reruns stay idempotent.
    if path.exists():
        try:
            if load_raw_records(path) == records:
                return
        except (ValueError, TypeError, KeyError):
            pass
    write_json(path, [asdict(record) for record in records])


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Load source records: offline snapshot by default, Crossref live API when REFRESH_SOURCE=1.

    The live call falls back to the local snapshot on network errors or repeated 429/503 responses.
    """
    snapshot_path = settings.paths.raw_api_response
    payload: dict | None = None

    if settings.refresh_source or not snapshot_path.exists():
        try:
            live_payload = _fetch_live_payload(settings)
            if parse_crossref_payload(live_payload):
                payload = live_payload
                write_json(snapshot_path, payload)
                print(f"[ingestion] Fetched live data from {settings.source_api}.")
            else:
                print("[ingestion] Live API returned no usable records; using local snapshot.")
        except RuntimeError as exc:
            print(f"[ingestion] {exc}. Falling back to local snapshot.")

    if payload is None:
        if not snapshot_path.exists():
            raise FileNotFoundError(f"No Crossref snapshot found at {snapshot_path} and the live API failed.")
        payload = read_json(snapshot_path)

    records = parse_crossref_payload(payload)
    _save_records(records, settings.paths.raw_records_json)
    return records


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Read the parsed-records snapshot and map each entry back to a `PaperRecord`."""
    known = {field.name for field in fields(PaperRecord)}
    records = []
    for item in read_json(path):
        values = {key: item.get(key) for key in known}
        values["authors"] = list(values["authors"] or [])
        values["categories"] = list(values["categories"] or [])
        records.append(PaperRecord(**{key: value if value is not None else "" for key, value in values.items()}))
    return records
