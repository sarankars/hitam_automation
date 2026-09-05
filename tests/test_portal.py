from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from hitam_cli.portal import (
    PortalError,
    QuestionSpec,
    StudentSchema,
    UploadCancelled,
    UploadSummary,
    deduplicate_sheet_numbers,
    normalise_inputs,
    pdf_url_matches,
    upload_from_page,
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

    def test_declined_upload_makes_no_save_calls(self):
        schema = StudentSchema(
            "000001",
            "https://example.test/000001.pdf",
            (QuestionSpec("1", "1", Decimal(5)),),
        )
        workbook = SimpleNamespace(
            students=(SimpleNamespace(sheet_no="000001", marks={"1": Decimal(4)}),)
        )
        with (
            patch(
                "hitam_cli.portal._validate_upload",
                return_value=([schema], UploadSummary(1, 1, 1)),
            ),
            patch("hitam_cli.portal._save_student") as save,
            self.assertRaises(UploadCancelled),
        ):
            upload_from_page(Mock(), Mock(), workbook, lambda _: False)
        save.assert_not_called()

    def test_upload_stops_and_reports_saved_count_on_first_failure(self):
        question = (QuestionSpec("1", "1", Decimal(5)),)
        schemas = [
            StudentSchema("000001", "https://example.test/000001.pdf", question),
            StudentSchema("000002", "https://example.test/000002.pdf", question),
        ]
        workbook = SimpleNamespace(
            students=tuple(
                SimpleNamespace(sheet_no=schema.sheet_no, marks={"1": Decimal(4)})
                for schema in schemas
            )
        )
        with (
            patch(
                "hitam_cli.portal._validate_upload",
                return_value=(schemas, UploadSummary(2, 1, 2)),
            ),
            patch(
                "hitam_cli.portal._save_student",
                side_effect=[None, PortalError("failed")],
            ),
            self.assertRaisesRegex(PortalError, "saving 1 of 2"),
        ):
            upload_from_page(Mock(), Mock(), workbook, lambda _: True)
