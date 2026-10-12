"""Small, auditable clients for scholarly discovery providers."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sci_search.discovery import PublicationCandidate, SearchQuery

JsonFetcher = Callable[[str, dict[str, str]], dict[str, Any]]


class DiscoveryProvider(Protocol):
    name: str

    def search(self, query: SearchQuery, *, limit: int) -> tuple[PublicationCandidate, ...]: ...


class OpenAlexProvider:
    name = "openalex"
    base_url = "https://api.openalex.org/works"

    def __init__(self, api_key: str, *, fetch_json: JsonFetcher | None = None) -> None:
        if not api_key.strip():
            raise ValueError("OpenAlex API key is required")
        self.api_key = api_key
        self.fetch_json = fetch_json or _fetch_json

    def search(self, query: SearchQuery, *, limit: int = 25) -> tuple[PublicationCandidate, ...]:
        params = {
            "api_key": self.api_key,
            "search": query.text,
            "per_page": str(min(max(limit, 1), 100)),
            "select": "id,doi,display_name,publication_year,authorships,ids,primary_location,best_oa_location,locations,open_access,has_content,type,is_retracted,cited_by_count,abstract_inverted_index",
        }
        payload = self.fetch_json(self.base_url, params)
        results = payload.get("results") if isinstance(payload, dict) else []
        return tuple(
            _openalex_candidate(item, query.id)
            for item in results or []
            if isinstance(item, dict) and str(item.get("display_name") or "").strip()
        )

    def expand_citations(
        self, seed: PublicationCandidate, *, limit: int = 10
    ) -> tuple[PublicationCandidate, ...]:
        """Return one bounded hop of references and citing works around an OpenAlex seed."""
        work_id = _openalex_work_id(seed.openalex_id)
        if not work_id:
            return ()
        per_direction = max(1, min(limit, 100) // 2)
        reference_budget = min(100, max(25, per_direction * 5))
        select = "id,doi,display_name,publication_year,authorships,ids,primary_location,best_oa_location,locations,open_access,has_content,type,is_retracted,cited_by_count,abstract_inverted_index"
        seed_payload = self.fetch_json(
            f"{self.base_url}/{work_id}", {"api_key": self.api_key, "select": "referenced_works"}
        )
        references = seed_payload.get("referenced_works") if isinstance(seed_payload, dict) else []
        reference_ids = [item for item in references or [] if _openalex_work_id(str(item))][
            :reference_budget
        ]
        results: list[PublicationCandidate] = []
        if reference_ids:
            ids_filter = "|".join(str(_openalex_work_id(item)) for item in reference_ids)
            payload = self.fetch_json(
                self.base_url,
                {
                    "api_key": self.api_key,
                    "filter": f"openalex_id:{ids_filter}",
                    "per_page": str(len(reference_ids)),
                    "select": select,
                },
            )
            reference_candidates: list[PublicationCandidate] = []
            for item in payload.get("results", []) if isinstance(payload, dict) else []:
                if isinstance(item, dict) and item.get("display_name"):
                    candidate = _openalex_candidate(item, f"citation:references:{seed.id}")
                    reference_candidates.append(
                        replace(candidate, citation_relations=(f"referenced_by:{seed.id}",))
                    )
            reference_candidates.sort(
                key=lambda item: _candidate_similarity(seed, item), reverse=True
            )
            results.extend(reference_candidates[:per_direction])
        payload = self.fetch_json(
            self.base_url,
            {
                "api_key": self.api_key,
                "filter": f"cites:{work_id}",
                "per_page": str(per_direction),
                "select": select,
            },
        )
        for item in payload.get("results", []) if isinstance(payload, dict) else []:
            if isinstance(item, dict) and item.get("display_name"):
                candidate = _openalex_candidate(item, f"citation:cites:{seed.id}")
                results.append(replace(candidate, citation_relations=(f"cites:{seed.id}",)))
        return tuple(results[:limit])


class EuropePmcProvider:
    name = "europe_pmc"
    base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, *, fetch_json: JsonFetcher | None = None) -> None:
        self.fetch_json = fetch_json or _fetch_json

    def search(self, query: SearchQuery, *, limit: int = 25) -> tuple[PublicationCandidate, ...]:
        params = {
            "query": f"({query.text}) AND OPEN_ACCESS:Y",
            "format": "json",
            "resultType": "core",
            "pageSize": str(min(max(limit, 1), 100)),
        }
        payload = self.fetch_json(self.base_url, params)
        result_list = payload.get("resultList") if isinstance(payload, dict) else {}
        results = result_list.get("result") if isinstance(result_list, dict) else []
        return tuple(
            _europe_pmc_candidate(item, query.id)
            for item in results or []
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        )


class CrossrefProvider:
    name = "crossref"
    base_url = "https://api.crossref.org/works"

    def __init__(self, *, email: str | None = None, fetch_json: JsonFetcher | None = None) -> None:
        self.email = email
        self.fetch_json = fetch_json or _fetch_json

    def search(self, query: SearchQuery, *, limit: int = 25) -> tuple[PublicationCandidate, ...]:
        params = {"query.bibliographic": query.text, "rows": str(min(max(limit, 1), 100))}
        if self.email:
            params["mailto"] = self.email
        payload = self.fetch_json(self.base_url, params)
        message = payload.get("message") if isinstance(payload, dict) else {}
        results = message.get("items") if isinstance(message, dict) else []
        return tuple(
            _crossref_candidate(item, query.id)
            for item in results or []
            if isinstance(item, dict) and item.get("title")
        )


def discover_with_providers(
    queries: tuple[SearchQuery, ...],
    providers: tuple[DiscoveryProvider, ...],
    *,
    per_query: int,
) -> tuple[tuple[PublicationCandidate, ...], tuple[dict[str, object], ...]]:
    candidates: list[PublicationCandidate] = []
    logs: list[dict[str, object]] = []
    for provider in providers:
        provider_unavailable: str | None = None
        for query in queries:
            if provider_unavailable:
                logs.append(
                    {
                        "provider": provider.name,
                        "query_id": query.id,
                        "query": query.text,
                        "purpose": query.purpose,
                        "result_count": 0,
                        "elapsed_seconds": 0.0,
                        "status": "skipped",
                        "error": provider_unavailable,
                    }
                )
                continue
            started = time.monotonic()
            try:
                found = provider.search(query, limit=per_query)
                candidates.extend(found)
                logs.append(
                    {
                        "provider": provider.name,
                        "query_id": query.id,
                        "query": query.text,
                        "purpose": query.purpose,
                        "result_count": len(found),
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "status": "ok",
                        "error": None,
                    }
                )
            except (
                HTTPError,
                URLError,
                TimeoutError,
                OSError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                if isinstance(exc, HTTPError) and exc.code in {401, 403, 429}:
                    provider_unavailable = (
                        f"provider disabled for this search after HTTP {exc.code}"
                    )
                logs.append(
                    {
                        "provider": provider.name,
                        "query_id": query.id,
                        "query": query.text,
                        "purpose": query.purpose,
                        "result_count": 0,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "status": "error",
                        "error": f"{type(exc).__name__}: {_sanitized_error(exc)}",
                    }
                )
                if isinstance(exc, HTTPError):
                    exc.close()
    return tuple(candidates), tuple(logs)


def expand_citation_network(
    seeds: tuple[PublicationCandidate, ...],
    providers: tuple[DiscoveryProvider, ...],
    *,
    per_seed: int,
) -> tuple[tuple[PublicationCandidate, ...], tuple[dict[str, object], ...]]:
    """Expand one citation hop through providers that explicitly support it."""
    candidates: list[PublicationCandidate] = []
    logs: list[dict[str, object]] = []
    for provider in providers:
        expand = getattr(provider, "expand_citations", None)
        if not callable(expand):
            continue
        for seed in seeds:
            started = time.monotonic()
            try:
                found = tuple(expand(seed, limit=per_seed))
                candidates.extend(found)
                logs.append(
                    {
                        "provider": provider.name,
                        "seed_publication_id": seed.id,
                        "result_count": len(found),
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "status": "ok",
                        "error": None,
                        "kind": "citation_expansion",
                    }
                )
            except (
                HTTPError,
                URLError,
                TimeoutError,
                OSError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                logs.append(
                    {
                        "provider": provider.name,
                        "seed_publication_id": seed.id,
                        "result_count": 0,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "status": "error",
                        "error": f"{type(exc).__name__}: {_sanitized_error(exc)}",
                        "kind": "citation_expansion",
                    }
                )
                if isinstance(exc, HTTPError):
                    exc.close()
    return tuple(candidates), tuple(logs)


def _openalex_candidate(item: dict[str, Any], query_id: str) -> PublicationCandidate:
    openalex_id = str(item.get("id") or "").strip()
    ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
    best = item.get("best_oa_location") if isinstance(item.get("best_oa_location"), dict) else {}
    primary = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
    oa = item.get("open_access") if isinstance(item.get("open_access"), dict) else {}
    content = item.get("has_content") if isinstance(item.get("has_content"), dict) else {}
    doi = _normalize_doi(item.get("doi") or ids.get("doi"))
    pmcid = _normalize_pmcid(ids.get("pmcid"))
    authors = tuple(
        str(authorship.get("author", {}).get("display_name") or "").strip()
        for authorship in item.get("authorships") or []
        if isinstance(authorship, dict)
        and str(authorship.get("author", {}).get("display_name") or "").strip()
    )
    author_ids = tuple(
        str(authorship.get("author", {}).get("id") or "").strip()
        for authorship in item.get("authorships") or []
        if isinstance(authorship, dict)
        and str(authorship.get("author", {}).get("display_name") or "").strip()
    )
    institution_pairs = tuple(
        dict.fromkeys(
            (
                str(institution.get("display_name") or "").strip(),
                str(institution.get("ror") or institution.get("id") or "").strip(),
            )
            for authorship in item.get("authorships") or []
            if isinstance(authorship, dict)
            for institution in authorship.get("institutions") or []
            if isinstance(institution, dict) and str(institution.get("display_name") or "").strip()
        )
    )
    institutions = tuple(name for name, _ in institution_pairs)
    institution_ids = tuple(identifier for _, identifier in institution_pairs)
    candidate_id = _candidate_id(doi, openalex_id, str(item.get("display_name") or ""))
    return PublicationCandidate(
        id=candidate_id,
        title=_strip_markup(str(item.get("display_name") or "")),
        abstract=_abstract_from_inverted_index(item.get("abstract_inverted_index")),
        year=item.get("publication_year")
        if isinstance(item.get("publication_year"), int)
        else None,
        doi=doi,
        authors=authors,
        publication_type=str(item.get("type") or "article"),
        source_url=openalex_id or str(primary.get("landing_page_url") or "").strip() or None,
        full_text_url=str(best.get("pdf_url") or "").strip() or None,
        oa_landing_urls=tuple(
            dict.fromkeys(
                str(location["landing_page_url"]).strip()
                for location in [best, primary, *(item.get("locations") or [])]
                if isinstance(location, dict)
                and location.get("is_oa") is True
                and isinstance(location.get("source"), dict)
                and location["source"].get("type") == "repository"
                and location.get("landing_page_url")
            )
        ),
        author_ids=author_ids,
        institutions=institutions,
        institution_ids=institution_ids,
        openalex_id=openalex_id or None,
        pmcid=pmcid,
        cited_by_count=item.get("cited_by_count")
        if isinstance(item.get("cited_by_count"), int)
        else 0,
        is_open_access=bool(oa.get("is_oa")),
        license=str(best.get("license") or "").strip() or None,
        has_pdf=bool(best.get("pdf_url") or content.get("pdf")),
        has_structured_fulltext=bool(pmcid or content.get("grobid_xml")),
        is_retracted=bool(item.get("is_retracted")),
        providers=("openalex",),
        matched_query_ids=(query_id,),
    )


def _europe_pmc_candidate(item: dict[str, Any], query_id: str) -> PublicationCandidate:
    doi = _normalize_doi(item.get("doi"))
    pmcid = _normalize_pmcid(
        item.get("pmcid")
        or (item.get("id") if str(item.get("id") or "").upper().startswith("PMC") else None)
    )
    authors = tuple(
        str(author.get("fullName") or "").strip()
        for author in (item.get("authorList") or {}).get("author", [])
        if isinstance(author, dict) and str(author.get("fullName") or "").strip()
    )
    institution_values: list[str] = []
    for author in (item.get("authorList") or {}).get("author", []):
        if isinstance(author, dict) and str(author.get("affiliation") or "").strip():
            institution_values.append(str(author["affiliation"]).strip())
    for affiliation in (item.get("affiliationList") or {}).get("affiliation", []):
        if isinstance(affiliation, dict):
            value = affiliation.get("affiliation") or affiliation.get("name")
        else:
            value = affiliation
        if str(value or "").strip():
            institution_values.append(str(value).strip())
    title = _strip_markup(str(item.get("title") or ""))
    source_id = pmcid or str(item.get("id") or "")
    return PublicationCandidate(
        id=_candidate_id(doi, source_id, title),
        title=title,
        abstract=_strip_markup(str(item.get("abstractText") or "")),
        year=_year(item.get("pubYear") or item.get("firstPublicationDate")),
        doi=doi,
        authors=authors,
        publication_type=str(item.get("pubType") or "article"),
        source_url=f"https://europepmc.org/article/MED/{item.get('pmid')}"
        if item.get("pmid")
        else f"https://europepmc.org/article/PMC/{pmcid}"
        if pmcid
        else None,
        affiliations=tuple(dict.fromkeys(institution_values)),
        pmcid=pmcid,
        cited_by_count=_integer(item.get("citedByCount")),
        is_open_access=bool(item.get("isOpenAccess") == "Y" or pmcid),
        license=str(item.get("license") or "").strip() or None,
        has_pdf=bool(item.get("hasPDF") == "Y"),
        has_structured_fulltext=bool(pmcid and item.get("inEPMC") == "Y"),
        is_retracted="RETRACT" in str(item.get("pubType") or "").upper(),
        providers=("europe_pmc",),
        matched_query_ids=(query_id,),
    )


def _crossref_candidate(item: dict[str, Any], query_id: str) -> PublicationCandidate:
    titles = item.get("title") if isinstance(item.get("title"), list) else []
    title = _strip_markup(str(titles[0] if titles else ""))
    doi = _normalize_doi(item.get("DOI"))
    authors = tuple(
        " ".join(
            part
            for part in (
                str(author.get("given") or "").strip(),
                str(author.get("family") or "").strip(),
            )
            if part
        )
        for author in item.get("author") or []
        if isinstance(author, dict)
    )
    institutions = tuple(
        dict.fromkeys(
            str(affiliation.get("name") or "").strip()
            for author in item.get("author") or []
            if isinstance(author, dict)
            for affiliation in author.get("affiliation") or []
            if isinstance(affiliation, dict) and str(affiliation.get("name") or "").strip()
        )
    )
    full_text_url = _crossref_pdf_url(item, doi)
    return PublicationCandidate(
        id=_candidate_id(doi, None, title),
        title=title,
        abstract=_strip_markup(str(item.get("abstract") or "")),
        year=_crossref_year(item),
        doi=doi,
        authors=tuple(author for author in authors if author),
        publication_type=str(item.get("type") or "article"),
        source_url=str(item.get("URL") or "").strip() or None,
        full_text_url=full_text_url,
        affiliations=institutions,
        cited_by_count=_integer(item.get("is-referenced-by-count")),
        is_open_access=bool(item.get("license")),
        license=str((item.get("license") or [{}])[0].get("URL") or "").strip() or None
        if isinstance((item.get("license") or [{}])[0], dict)
        else None,
        has_pdf=bool(full_text_url),
        providers=("crossref",),
        matched_query_ids=(query_id,),
    )


def _crossref_pdf_url(item: dict[str, Any], doi: str | None) -> str | None:
    """Retain an explicitly deposited OA PDF URL, including Copernicus links
    whose Crossref content type is recorded as ``unspecified``.

    Copernicus discussion records expose a stable article discussion URL rather
    than a link entry; its PDF is the same URL without ``-discussion.html``.
    This publisher-specific rule is deliberately narrow and only applied to
    records carrying an open licence elsewhere in the candidate mapping.
    """
    links = item.get("link") if isinstance(item.get("link"), list) else []
    for link in links:
        if not isinstance(link, dict):
            continue
        url = str(link.get("URL") or "").strip()
        content_type = str(link.get("content-type") or "").casefold()
        if url.startswith("https://") and (
            url.casefold().endswith(".pdf") or content_type == "application/pdf"
        ):
            return url
    resource = item.get("resource") if isinstance(item.get("resource"), dict) else {}
    primary = resource.get("primary") if isinstance(resource.get("primary"), dict) else {}
    landing = str(primary.get("URL") or "").strip()
    if (
        doi
        and doi.startswith("10.5194/")
        and landing.startswith("https://")
        and landing.endswith("-discussion.html")
    ):
        return landing.removesuffix("-discussion.html") + ".pdf"
    return None


def _fetch_json(base_url: str, params: dict[str, str]) -> dict[str, Any]:
    url = f"{base_url}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Sci-Search/0.2 (provenance-aware literature discovery)",
        },
    )
    for attempt in range(4):
        try:
            with urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("provider response was not a JSON object")
            return payload
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("provider request exhausted retries")


def _abstract_from_inverted_index(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    positioned: list[tuple[int, str]] = []
    for token, positions in value.items():
        if not isinstance(positions, list):
            continue
        positioned.extend(
            (position, str(token)) for position in positions if isinstance(position, int)
        )
    return " ".join(token for _, token in sorted(positioned))


def _candidate_id(doi: str | None, provider_id: str | None, title: str) -> str:
    basis = doi or provider_id or title.lower()
    return "publication:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def _openalex_work_id(value: str | None) -> str | None:
    match = re.search(r"W\d+", str(value or ""), re.IGNORECASE)
    return match.group(0).upper() if match else None


def _candidate_similarity(left: PublicationCandidate, right: PublicationCandidate) -> float:
    left_tokens = set(re.findall(r"[a-z]{3,}", f"{left.title} {left.abstract}".lower()))
    right_tokens = set(re.findall(r"[a-z]{3,}", f"{right.title} {right.abstract}".lower()))
    stop = {
        "about",
        "after",
        "among",
        "from",
        "have",
        "into",
        "study",
        "that",
        "their",
        "these",
        "this",
        "using",
        "were",
        "with",
    }
    left_tokens -= stop
    right_tokens -= stop
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def _normalize_doi(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text).removeprefix("doi:")
    return text or None


def _normalize_pmcid(value: Any) -> str | None:
    match = re.search(r"PMC\d+", str(value or ""), re.IGNORECASE)
    return match.group(0).upper() if match else None


def _strip_markup(value: str) -> str:
    return " ".join(
        re.sub(r"<[^>]+>", " ", value)
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .split()
    )


def _year(value: Any) -> int | None:
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _crossref_year(item: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "issued", "created"):
        value = item.get(key)
        if not isinstance(value, dict):
            continue
        parts = value.get("date-parts")
        if (
            isinstance(parts, list)
            and parts
            and isinstance(parts[0], list)
            and parts[0]
            and isinstance(parts[0][0], int)
        ):
            return parts[0][0]
    return None


def _sanitized_error(exc: BaseException) -> str:
    text = str(exc)
    return re.sub(r"api_key=[^&\s]+", "api_key=<redacted>", text)[:500]
