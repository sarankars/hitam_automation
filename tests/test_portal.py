from __future__ import annotations

from unittest import TestCase

from hitam_cli.portal import (
    deduplicate_sheet_numbers,
    normalise_inputs,
    pdf_url_matches,
)


class PortalHelpersTests(TestCase):
    def test_normalise_inputs(self):
        result = normalise_inputs(" U1 ", " cs101 ", " 12 ", " secret ")
        self.assertEqual(result.user_code, "U1")
        self.assertEqual(result.subject_code, "CS101")
        self.assertEqual(result.bundle_no, "12")
        self.assertEqual(result.bundle_key, "secret")

    def test_sheet_numbers_are_filtered_and_deduplicated_in_order(self):
        result = deduplicate_sheet_numbers(
            [" 123456 ", "VALIDATE", "000001", "123456", "12345"]
        )
        self.assertEqual(result, ["123456", "000001"])

    def test_pdf_url_must_match_https_subject_path_and_sheet(self):
        url = "https://hitamexams.org/ScriptPDF/2026/Scripts/SEP-2026/CS101/123456.pdf"
        self.assertTrue(pdf_url_matches(url, "cs101", "123456"))
        self.assertFalse(pdf_url_matches(url, "CS102", "123456"))
        self.assertFalse(pdf_url_matches(url, "CS101", "654321"))
        self.assertFalse(
            pdf_url_matches(url.replace("https://", "http://"), "CS101", "123456")
        )

    def test_url_decodes_subject_path(self):
        url = "https://hitamexams.org/ScriptPDF/24%20PC%2001/000001.pdf"
        self.assertTrue(pdf_url_matches(url, "24 PC 01", "000001"))
