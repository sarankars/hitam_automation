from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from openpyxl import load_workbook

from hitam_cli.portal import AnswerSheet
from hitam_cli.workbook import write_workbook


class WorkbookTests(TestCase):
    def test_workbook_contains_clickable_links_and_sheet_numbers_as_text(self):
        rows = [
            AnswerSheet("000001", "https://hitamexams.org/ScriptPDF/CS101/000001.pdf"),
            AnswerSheet("123456", "https://hitamexams.org/ScriptPDF/CS101/123456.pdf"),
        ]
        with TemporaryDirectory() as directory:
            output = Path(directory) / "answer-sheets.xlsx"
            saved = write_workbook(rows, output)
            workbook = load_workbook(saved)
            sheet = workbook["Answer sheets"]

            self.assertEqual(sheet["A1"].value, "Sheet No")
            self.assertEqual(sheet["B1"].value, "PDF Link")
            self.assertEqual(sheet["A2"].value, "000001")
            self.assertEqual(sheet["A2"].number_format, "@")
            self.assertEqual(sheet["B2"].hyperlink.target, rows[0].pdf_url)
            self.assertEqual(sheet.freeze_panes, "A2")
            self.assertEqual(sheet.auto_filter.ref, "A1:B3")
            workbook.close()

    def test_existing_output_is_not_overwritten(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "existing.xlsx"
            output.write_text("keep me", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_workbook(
                    [AnswerSheet("123456", "https://example.test/123456.pdf")], output
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "keep me")

    def test_empty_workbook_is_rejected(self):
        with TemporaryDirectory() as directory, self.assertRaises(ValueError):
            write_workbook([], Path(directory) / "empty.xlsx")
