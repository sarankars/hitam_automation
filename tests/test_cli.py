from __future__ import annotations

from datetime import UTC, datetime
from unittest import TestCase

from hitam_cli.cli import default_output_path, read_inputs


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
