from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import TestCase

from hitam_cli.cli import (
    build_parser,
    confirm_upload,
    default_output_path,
    read_inputs,
    read_upload_inputs,
)
from hitam_cli.portal import UploadSummary


class CliTests(TestCase):
    def test_prompts_are_in_required_order_and_bundle_id_uses_secret_prompt(self):
        prompts: list[str] = []
        values = iter([" user ", " sub01 ", " bundle "])

        def plain(prompt: str) -> str:
            prompts.append(prompt)
            return next(values)

        def secret(prompt: str) -> str:
            prompts.append(prompt)
            return " key "

        result = read_inputs(plain, secret)

        self.assertEqual(
            prompts, ["User Code: ", "Subject Code: ", "Bundle No: ", "Bundle Key: "]
        )
        self.assertEqual(result.user_code, "user")
        self.assertEqual(result.subject_code, "SUB01")
        self.assertEqual(result.bundle_no, "bundle")
        self.assertEqual(result.bundle_key, "key")

    def test_empty_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Subject Code"):
            read_inputs(
                lambda prompt: "" if prompt == "Subject Code: " else "value",
                lambda _: "key",
            )

    def test_default_output_name_is_safe_and_timestamped(self):
        result = default_output_path(
            "24 PC/01", "B 17", datetime(2026, 9, 5, 10, 11, 12, tzinfo=UTC)
        )
        self.assertEqual(result.name, "hitam_24-PC-01_B-17_20260905_101112.xlsx")

    def test_nested_exam_commands(self):
        parser = build_parser()
        export = parser.parse_args(["exam", "export", "--headless"])
        upload = parser.parse_args(["exam", "upload", "marks.xlsx"])
        self.assertEqual((export.command, export.exam_command), ("exam", "export"))
        self.assertTrue(export.headless)
        self.assertEqual((upload.command, upload.exam_command), ("exam", "upload"))
        self.assertEqual(upload.workbook.name, "marks.xlsx")

    def test_removed_eval_command_is_rejected(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["eval"])

    def test_upload_prompts_only_for_user_code_and_bundle_key(self):
        prompts = []
        workbook = SimpleNamespace(subject_code="CS101", bundle_no="B17")
        result = read_upload_inputs(
            workbook,
            lambda prompt: prompts.append(prompt) or "USER",
            lambda prompt: prompts.append(prompt) or "KEY",
        )
        self.assertEqual(prompts, ["User Code: ", "Bundle Key: "])
        self.assertEqual(result.subject_code, "CS101")
        self.assertEqual(result.bundle_no, "B17")

    def test_upload_confirmation_requires_exact_word(self):
        summary = UploadSummary(2, 3, 6)
        self.assertTrue(confirm_upload(summary, lambda _: "UPLOAD"))
        self.assertFalse(confirm_upload(summary, lambda _: "yes"))
