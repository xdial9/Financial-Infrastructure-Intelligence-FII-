"""Bounded, manual-only HTTPS retrieval for approved public sources."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fii.sources.contracts import CollectionContext, SourceCollectionError


@dataclass(frozen=True)
class HTTPPayload:
    """A bounded public HTTP response body and its non-sensitive metadata."""

    requested_url: str
    final_url: str
    body: bytes
    content_type: str


class _RejectRedirects(HTTPRedirectHandler):
    """Reject redirects so a source cannot silently move collection elsewhere."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def fetch_public_resource(
    url: str,
    context: CollectionContext,
    *,
    accept: str,
) -> HTTPPayload:
    """Fetch one explicitly approved HTTPS resource without auth or redirects."""
    if not context.live_collection_approved:
        raise SourceCollectionError(
            "live_collection_not_approved",
            "Live collection requires explicit per-run operator approval.",
        )
    if not url.startswith("https://"):
        raise SourceCollectionError(
            "https_required",
            "Live public-source collection requires HTTPS.",
        )

    request = Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": context.user_agent,
        },
        method="GET",
    )
    opener = build_opener(_RejectRedirects())

    try:
        with opener.open(request, timeout=context.request_timeout_seconds) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError:
                    declared_length = 0
                if declared_length > context.max_response_bytes:
                    raise SourceCollectionError(
                        "response_too_large",
                        "Public-source response exceeds the configured size limit.",
                    )

            body = response.read(context.max_response_bytes + 1)
            if len(body) > context.max_response_bytes:
                raise SourceCollectionError(
                    "response_too_large",
                    "Public-source response exceeds the configured size limit.",
                )

            return HTTPPayload(
                requested_url=url,
                final_url=response.geturl(),
                body=body,
                content_type=response.headers.get_content_type(),
            )
    except SourceCollectionError:
        raise
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise SourceCollectionError(
                "redirect_refused",
                "The public source redirected; automatic redirects are disabled.",
            ) from exc
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
            detail = (
                f" Retry-After: {retry_after}."
                if retry_after and retry_after.isascii()
                else ""
            )
            raise SourceCollectionError(
                "rate_limited",
                (
                    "The public source returned HTTP 429; do not retry before "
                    f"the provider permits it.{detail}"
                ),
            ) from exc
        raise SourceCollectionError(
            "source_http_error",
            f"The public source returned HTTP {exc.code}.",
        ) from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise SourceCollectionError(
            "source_unavailable",
            "The approved public source could not be retrieved.",
        ) from exc
