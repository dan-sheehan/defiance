"""Fetch and preserve the two reviewed Milestone 1 sources."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import ssl
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener, urlopen


class SourceError(RuntimeError):
    """Raised when configured source evidence cannot be trusted."""


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    kind: str
    url: str
    sha256: str


@dataclass(frozen=True)
class PreservedSource:
    config: SourceConfig
    raw_path: Path


LEGACY_BOX_SCORE_HOST = "sandiegost_ftp.sidearmsports.com"


class _ExactHostRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_host: str) -> None:
        super().__init__()
        self.allowed_host = allowed_host

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        redirected_host = urlparse(newurl).hostname
        if redirected_host != self.allowed_host:
            raise SourceError(
                f"refusing redirect from TLS-exception host {self.allowed_host} "
                f"to unexpected host {redirected_host or '<missing>'}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _legacy_tls_context(source: SourceConfig) -> ssl.SSLContext | None:
    hostname = urlparse(source.url).hostname
    if source.kind != "box_score" or hostname != LEGACY_BOX_SCORE_HOST:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    if context.verify_mode != ssl.CERT_REQUIRED:
        raise SourceError("legacy TLS context must retain certificate-chain validation")
    return context


def _validate_exception_response_host(response_url: str) -> None:
    final_host = urlparse(response_url).hostname
    if final_host != LEGACY_BOX_SCORE_HOST:
        raise SourceError(
            "TLS-exception response came from unexpected host "
            f"{final_host or '<missing>'}"
        )


def _read_response(source: SourceConfig, request: Request, timeout_seconds: float) -> bytes:
    context = _legacy_tls_context(source)
    if context is None:
        response_context = urlopen(request, timeout=timeout_seconds)
    else:
        opener = build_opener(
            _ExactHostRedirectHandler(LEGACY_BOX_SCORE_HOST),
            HTTPSHandler(context=context),
        )
        response_context = opener.open(request, timeout=timeout_seconds)

    with response_context as response:
        if context is not None:
            _validate_exception_response_host(response.geturl())
        return response.read()


def load_config(path: Path) -> tuple[SourceConfig, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceError(f"cannot read source configuration {path}: {exc}") from exc

    entries = payload.get("sources")
    if not isinstance(entries, list) or len(entries) != 2:
        raise SourceError("Milestone 1 requires exactly two configured sources")

    sources: list[SourceConfig] = []
    for entry in entries:
        try:
            source = SourceConfig(
                source_id=entry["source_id"],
                kind=entry["kind"],
                url=entry["url"],
                sha256=entry["sha256"],
            )
        except (KeyError, TypeError) as exc:
            raise SourceError("source configuration is missing a required field") from exc
        if source.kind not in {"box_score", "recap"}:
            raise SourceError(f"unsupported source kind: {source.kind}")
        if len(source.sha256) != 64:
            raise SourceError(f"invalid SHA-256 for {source.source_id}")
        sources.append(source)

    if {source.kind for source in sources} != {"box_score", "recap"}:
        raise SourceError("configuration must contain one box score and one recap")
    if len({source.source_id for source in sources}) != 2:
        raise SourceError("source IDs must be unique")
    return tuple(sources)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def raw_filename(source: SourceConfig) -> str:
    return f"{source.source_id}__{source.sha256}.html"


def verify_preserved(source: SourceConfig, path: Path) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise SourceError(f"configured raw file is missing: {path}") from exc
    actual = sha256_bytes(content)
    if actual != source.sha256:
        raise SourceError(
            f"SHA-256 mismatch for {source.source_id}: "
            f"expected {source.sha256}, got {actual}"
        )
    return content


def fetch_and_preserve(
    source: SourceConfig, raw_dir: Path, *, timeout_seconds: float = 20.0
) -> PreservedSource:
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = raw_dir / raw_filename(source)
    if destination.exists():
        verify_preserved(source, destination)
        return PreservedSource(source, destination)

    request = Request(source.url, headers={"User-Agent": "Defiance/0.1 source preservation"})
    try:
        content = _read_response(source, request, timeout_seconds)
    except OSError as exc:
        raise SourceError(f"failed to fetch {source.url}: {exc}") from exc

    actual = sha256_bytes(content)
    if actual != source.sha256:
        raise SourceError(
            f"SHA-256 mismatch for {source.source_id}: "
            f"expected {source.sha256}, got {actual}"
        )

    try:
        with destination.open("xb") as handle:
            handle.write(content)
    except FileExistsError:
        verify_preserved(source, destination)
    return PreservedSource(source, destination)
