"""Command-line interface for the HITAM answer-sheet exporter."""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from .portal import EvaluationInputs, PortalError, fetch_answer_sheets, normalise_inputs
from .workbook import write_workbook

InputFunction = Callable[[str], str]


def read_inputs(
    input_func: InputFunction = input,
    secret_func: InputFunction = getpass.getpass,
) -> EvaluationInputs:
    """Collect exactly the four interactive inputs required by `hitam eval`."""
    return normalise_inputs(
        input_func("User Code: "),
        input_func("Subject Code: "),
        input_func("Bundle No: "),
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
        prog="hitam", description="Export HITAM answer-sheet PDF links to Excel."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("eval", help="Export one evaluation bundle")
    evaluate.add_argument("--output", type=Path, help="Destination .xlsx file")
    evaluate.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium without showing its window",
    )
    return parser


def run_eval(args: argparse.Namespace) -> int:
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
    saved_path = write_workbook(answer_sheets, output)
    print(f"Exported {len(answer_sheets)} answer-sheet links to {saved_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "eval":
            return run_eval(args)
    except (ValueError, OSError, PortalError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except EOFError:
        print(
            "Error: input ended before all four values were provided.", file=sys.stderr
        )
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
