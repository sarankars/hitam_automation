"""Command-line interface for the HITAM answer-sheet exporter."""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from .portal import (
    EvaluationInputs,
    PortalError,
    UploadCancelled,
    UploadSummary,
    fetch_answer_sheets,
    normalise_inputs,
    upload_marks,
)
from .workbook import MarksWorkbook, read_marks_workbook, write_workbook

InputFunction = Callable[[str], str]


def read_inputs(
    input_func: InputFunction = input,
    secret_func: InputFunction = getpass.getpass,
) -> EvaluationInputs:
    """Collect the four inputs required by `hitam exam export`."""
    return normalise_inputs(
        input_func("User Code: "),
        input_func("Subject Code: "),
        input_func("Bundle No: "),
        secret_func("Bundle Key: "),
    )


def read_upload_inputs(
    marks_workbook: MarksWorkbook,
    input_func: InputFunction = input,
    secret_func: InputFunction = getpass.getpass,
) -> EvaluationInputs:
    """Collect secrets while reusing non-secret workbook metadata."""
    return normalise_inputs(
        input_func("User Code: "),
        marks_workbook.subject_code,
        marks_workbook.bundle_no,
        secret_func("Bundle Key: "),
    )


def _safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return cleaned.strip("-._") or "unknown"


def default_output_path(
    subject_code: str, bundle_no: str, now: datetime | None = None
) -> Path:
    timestamp = (now or datetime.now().astimezone()).strftime("%Y%m%d_%H%M%S")
    name = (
        f"hitam_{_safe_filename_part(subject_code)}_"
        f"{_safe_filename_part(bundle_no)}_{timestamp}.xlsx"
    )
    return Path.cwd() / name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hitam", description="Prepare and submit HITAM exam evaluation workbooks."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    exam = subparsers.add_parser("exam", help="Work with an evaluation bundle")
    exam_subparsers = exam.add_subparsers(dest="exam_command", required=True)

    export = exam_subparsers.add_parser(
        "export", help="Create a workbook with answer-sheet details"
    )
    export.add_argument("--output", type=Path, help="Destination .xlsx file")
    export.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium without showing its window",
    )

    upload = exam_subparsers.add_parser(
        "upload", help="Validate and upload marks from a completed workbook"
    )
    upload.add_argument("workbook", type=Path, help="Completed HITAM .xlsx workbook")
    upload.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium without showing its window",
    )
    return parser


def run_export(args: argparse.Namespace) -> int:
    if args.output is not None and args.output.suffix.lower() != ".xlsx":
        raise ValueError("Output file must use the .xlsx extension.")
    inputs = read_inputs()
    output = args.output or default_output_path(inputs.subject_code, inputs.bundle_no)
    if output.expanduser().exists():
        raise FileExistsError(
            f"Output file already exists: {output.expanduser().resolve()}"
        )

    print("Opening the HITAM evaluation portal...")
    answer_sheets = fetch_answer_sheets(inputs, headless=args.headless)
    saved_path = write_workbook(
        answer_sheets,
        output,
        subject_code=inputs.subject_code,
        bundle_no=inputs.bundle_no,
    )
    print(f"Exported {len(answer_sheets)} answer-sheet links to {saved_path}")
    return 0


def confirm_upload(summary: UploadSummary, input_func: InputFunction = input) -> bool:
    question_text = (
        str(summary.question_count) if summary.question_count else "a varying number of"
    )
    print(
        f"Validated {summary.student_count} students, {question_text} questions per "
        f"student, and {summary.mark_count} marks to overwrite."
    )
    print("This will overwrite the corresponding marks currently in the HITAM portal.")
    return input_func("Type UPLOAD to continue: ").strip() == "UPLOAD"


def run_upload(args: argparse.Namespace) -> int:
    marks_workbook = read_marks_workbook(args.workbook)
    inputs = read_upload_inputs(marks_workbook)
    print("Opening the HITAM evaluation portal and validating the workbook...")
    saved = upload_marks(
        inputs,
        marks_workbook,
        confirm_upload,
        headless=args.headless,
    )
    print(f"Saved marks for {saved} students.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "exam" and args.exam_command == "export":
            return run_export(args)
        if args.command == "exam" and args.exam_command == "upload":
            return run_upload(args)
    except UploadCancelled as exc:
        print(str(exc))
        return 0
    except (ValueError, OSError, PortalError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except EOFError:
        print(
            "Error: input ended before all required values were provided.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
