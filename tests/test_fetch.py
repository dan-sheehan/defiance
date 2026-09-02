from __future__ import annotations

from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request

from defiance.fetch import (
    LEGACY_BOX_SCORE_HOST,
    SourceConfig,
    SourceError,
    _ExactHostRedirectHandler,
    _legacy_tls_context,
    _validate_exception_response_host,
    fetch_and_preserve,
    raw_filename,
    sha256_bytes,
)


LEGACY_URL = f"https://{LEGACY_BOX_SCORE_HOST}/custompages/example.html"


class LegacyTlsBoundaryTest(unittest.TestCase):
    def test_exception_retains_chain_validation_for_exact_box_host(self) -> None:
        source = SourceConfig("box", "box_score", LEGACY_URL, "0" * 64)
        context = _legacy_tls_context(source)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertFalse(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_exception_is_not_available_to_other_sources_or_hosts(self) -> None:
        recap = SourceConfig("recap", "recap", LEGACY_URL, "0" * 64)
        other_host = SourceConfig("box", "box_score", "https://example.com/box.html", "0" * 64)
        lookalike = SourceConfig(
            "box",
            "box_score",
            f"https://evil.{LEGACY_BOX_SCORE_HOST}/box.html",
            "0" * 64,
        )
        self.assertIsNone(_legacy_tls_context(recap))
        self.assertIsNone(_legacy_tls_context(other_host))
        self.assertIsNone(_legacy_tls_context(lookalike))

    def test_redirect_handler_refuses_a_different_hostname(self) -> None:
        handler = _ExactHostRedirectHandler(LEGACY_BOX_SCORE_HOST)
        request = Request(LEGACY_URL)
        with self.assertRaises(SourceError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://example.com/box.html",
            )

    def test_redirect_handler_allows_only_the_exact_hostname(self) -> None:
        handler = _ExactHostRedirectHandler(LEGACY_BOX_SCORE_HOST)
        request = Request(LEGACY_URL)
        redirected = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            f"https://{LEGACY_BOX_SCORE_HOST}/custompages/moved.html",
        )
        self.assertEqual(redirected.full_url, f"https://{LEGACY_BOX_SCORE_HOST}/custompages/moved.html")

    def test_final_response_hostname_is_checked(self) -> None:
        _validate_exception_response_host(LEGACY_URL)
        with self.assertRaises(SourceError):
            _validate_exception_response_host("https://example.com/box.html")

    def test_hash_mismatch_is_not_preserved(self) -> None:
        expected = b"reviewed source bytes"
        source = SourceConfig("box", "box_score", LEGACY_URL, sha256_bytes(expected))
        with tempfile.TemporaryDirectory() as temporary:
            raw_dir = Path(temporary)
            with patch("defiance.fetch._read_response", return_value=b"altered source bytes"):
                with self.assertRaises(SourceError):
                    fetch_and_preserve(source, raw_dir)
            self.assertFalse((raw_dir / raw_filename(source)).exists())

    def test_certificate_chain_failure_is_not_bypassed(self) -> None:
        source = SourceConfig("box", "box_score", LEGACY_URL, sha256_bytes(b"unused"))
        opener = Mock()
        opener.open.side_effect = ssl.SSLCertVerificationError(1, "chain validation failed")
        with tempfile.TemporaryDirectory() as temporary:
            raw_dir = Path(temporary)
            with patch("defiance.fetch.build_opener", return_value=opener):
                with self.assertRaises(SourceError):
                    fetch_and_preserve(source, raw_dir)
            self.assertFalse((raw_dir / raw_filename(source)).exists())


if __name__ == "__main__":
    unittest.main()
