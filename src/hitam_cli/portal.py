"""Browser automation for the HITAM MidEvaluation portal."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from .workbook import MarksWorkbook

PORTAL_URL = "https://hitamexams.org/MidEvaluation/"
DEFAULT_TIMEOUT_MS = 30_000
SHEET_NUMBER_PATTERN = re.compile(r"^\s*(\d{6})\s*$")


class PortalError(RuntimeError):
    """Raised when the portal cannot complete the requested read-only workflow."""


@dataclass(frozen=True)
class EvaluationInputs:
    user_code: str
    subject_code: str
    bundle_no: str
    bundle_key: str


@dataclass(frozen=True)
class AnswerSheet:
    sheet_no: str
    pdf_url: str


@dataclass(frozen=True)
class QuestionSpec:
    label: str
    key: str
    maximum: Decimal


@dataclass(frozen=True)
class StudentSchema:
    sheet_no: str
    pdf_url: str
    questions: tuple[QuestionSpec, ...]


@dataclass(frozen=True)
class UploadSummary:
    student_count: int
    question_count: int
    mark_count: int


class UploadCancelled(RuntimeError):
    """Raised when the user declines the final upload confirmation."""


def normalise_question_label(value: object) -> str:
    """Map workbook labels such as Q1 to portal labels such as 1."""
    label = re.sub(r"\s+", "", str(value or "")).casefold()
    if len(label) > 1 and label.startswith("q") and label[1].isdigit():
        label = label[1:]
    return label


def normalise_inputs(
    user_code: str,
    subject_code: str,
    bundle_no: str,
    bundle_key: str,
) -> EvaluationInputs:
    """Trim and validate values collected by the CLI."""
    values = {
        "User Code": user_code.strip(),
        "Subject Code": subject_code.strip().upper(),
        "Bundle No": bundle_no.strip(),
        "Bundle Key": bundle_key.strip(),
    }
    missing = [label for label, value in values.items() if not value]
    if missing:
        raise ValueError(f"Required value is empty: {', '.join(missing)}")
    return EvaluationInputs(
        user_code=values["User Code"],
        subject_code=values["Subject Code"],
        bundle_no=values["Bundle No"],
        bundle_key=values["Bundle Key"],
    )


def deduplicate_sheet_numbers(labels: list[str]) -> list[str]:
    """Return unique six-digit sheet numbers in portal display order."""
    result: list[str] = []
    seen: set[str] = set()
    for label in labels:
        match = SHEET_NUMBER_PATTERN.fullmatch(label)
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            result.append(match.group(1))
    return result


def pdf_url_matches(url: str, subject_code: str, sheet_no: str) -> bool:
    """Check that a captured request is the requested sheet and subject PDF."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        return False
    decoded_path = unquote(parsed.path)
    if not decoded_path.casefold().endswith(f"/{sheet_no}.pdf".casefold()):
        return False
    subject = subject_code.strip().casefold()
    path_parts = [part.casefold() for part in decoded_path.split("/") if part]
    return subject in path_parts


def _portal_error_text(page: Page) -> str | None:
    labels = page.locator("label").all_inner_texts()
    ignored = {"PROGRAM", "USER CODE", "BUNDLE NO", "BUNDLE KEY"}
    messages = [
        text.strip()
        for text in labels
        if text.strip() and text.strip().upper() not in ignored
    ]
    return messages[-1] if messages else None


def _wait_visible(page: Page, label: str, timeout_ms: int) -> None:
    try:
        page.get_by_label(label, exact=True).wait_for(
            state="visible", timeout=timeout_ms
        )
    except PlaywrightTimeoutError as exc:
        detail = _portal_error_text(page)
        suffix = f" Portal message: {detail}" if detail else ""
        raise PortalError(f"The portal did not open the {label} step.{suffix}") from exc


def _submit_step(
    page: Page, label: str, value: str, next_label: str, timeout_ms: int
) -> None:
    page.get_by_label(label, exact=True).fill(value)
    page.get_by_role(
        "button", name=re.compile(r"^\s*VALIDATE\s*$", re.IGNORECASE)
    ).click()
    _wait_visible(page, next_label, timeout_ms)


def _open_bundle(page: Page, inputs: EvaluationInputs, timeout_ms: int) -> None:
    try:
        page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        page.get_by_role(
            "button", name=re.compile(r"FACULTY LOGIN", re.IGNORECASE)
        ).click()
        program = page.locator("select")
        program.wait_for(state="visible", timeout=timeout_ms)
        program.select_option(label="B.Tech")
        page.get_by_role(
            "button", name=re.compile(r"^\s*VALIDATE\s*$", re.IGNORECASE)
        ).click()
        _wait_visible(page, "USER CODE", timeout_ms)
        _submit_step(page, "USER CODE", inputs.user_code, "BUNDLE NO", timeout_ms)
        _submit_step(page, "BUNDLE NO", inputs.bundle_no, "BUNDLE KEY", timeout_ms)
        page.get_by_label("BUNDLE KEY", exact=True).fill(inputs.bundle_key)
        page.get_by_role(
            "button", name=re.compile(r"^\s*VALIDATE\s*$", re.IGNORECASE)
        ).click()
    except PortalError:
        raise
    except PlaywrightTimeoutError as exc:
        detail = _portal_error_text(page)
        suffix = f" Portal message: {detail}" if detail else ""
        raise PortalError(f"The HITAM portal timed out during login.{suffix}") from exc
    except PlaywrightError as exc:
        raise PortalError(f"The HITAM portal could not be opened: {exc}") from exc


def _sheet_numbers(page: Page, timeout_ms: int) -> list[str]:
    buttons = page.get_by_role("button", name=re.compile(r"^\s*\d{6}\s*$"))
    try:
        buttons.first.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeoutError as exc:
        detail = _portal_error_text(page)
        suffix = f" Portal message: {detail}" if detail else ""
        raise PortalError(f"No student sheet numbers were returned.{suffix}") from exc

    numbers = deduplicate_sheet_numbers(buttons.all_inner_texts())
    if not numbers:
        raise PortalError("No six-digit student sheet numbers were found.")
    return numbers


def _capture_pdf_urls(
    page: Page,
    sheet_numbers: list[str],
    subject_code: str,
    timeout_ms: int,
) -> list[AnswerSheet]:
    answer_sheets: list[AnswerSheet] = []
    for sheet_no in sheet_numbers:
        button = page.get_by_role(
            "button", name=re.compile(rf"^\s*{re.escape(sheet_no)}\s*$")
        ).first
        try:
            with page.expect_request(
                lambda request, number=sheet_no: pdf_url_matches(
                    request.url, subject_code, number
                ),
                timeout=timeout_ms,
            ) as request_info:
                button.click()
            pdf_url = request_info.value.url
        except PlaywrightTimeoutError as exc:
            raise PortalError(
                f"No PDF request was observed for sheet {sheet_no}. "
                f"Confirm that Subject Code {subject_code!r} matches this bundle."
            ) from exc
        answer_sheets.append(AnswerSheet(sheet_no=sheet_no, pdf_url=pdf_url))
    return answer_sheets


def _marks_table(page: Page, timeout_ms: int):
    table = (
        page.locator("table")
        .filter(has_text=re.compile(r"Q\.?\s*NO", re.IGNORECASE))
        .filter(has_text=re.compile(r"MAX\s*MARKS", re.IGNORECASE))
        .first
    )
    try:
        table.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeoutError as exc:
        raise PortalError("The portal did not show the question marks table.") from exc
    return table


def _question_rows(page: Page, timeout_ms: int):
    rows = _marks_table(page, timeout_ms).locator("tbody tr")
    result = []
    for index in range(rows.count()):
        row = rows.nth(index)
        cells = row.locator("td")
        if cells.count() < 3:
            continue
        label = cells.nth(0).inner_text().strip()
        maximum_text = cells.nth(1).inner_text().strip()
        mark_input = cells.nth(2).locator("input").first
        if not label or mark_input.count() == 0:
            continue
        try:
            maximum = Decimal(maximum_text)
        except InvalidOperation as exc:
            raise PortalError(
                f"The portal returned an invalid maximum for question {label!r}."
            ) from exc
        result.append(
            (QuestionSpec(label, normalise_question_label(label), maximum), mark_input)
        )
    if not result:
        raise PortalError("The portal returned no question rows for this student.")
    return result


def _is_marks_display_response(response) -> bool:
    """Identify the marks-table request made when a student button is clicked."""
    request = response.request
    if request.method != "POST":
        return False
    try:
        payload = request.post_data_json
    except (PlaywrightError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and "StudId" in payload
        and "SectionId" in payload
        and "ListQuestionWiseMarks" not in payload
    )


def _display_rows(response, sheet_no: str) -> tuple[tuple[QuestionSpec, str], ...]:
    """Validate and normalize the marks-table response for one student."""
    try:
        payload = response.json()
    except (PlaywrightError, ValueError) as exc:
        raise PortalError(
            f"Sheet {sheet_no}: the marks-table response could not be read."
        ) from exc
    if not response.ok:
        raise PortalError(
            f"Sheet {sheet_no}: the portal could not load the marks table."
        )
    raw_rows = payload.get("MarksDisplayTable1") if isinstance(payload, dict) else None
    if not isinstance(raw_rows, list) or not raw_rows:
        raise PortalError(
            f"Sheet {sheet_no}: the portal returned an empty marks table."
        )

    result: list[tuple[QuestionSpec, str]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            raise PortalError(
                f"Sheet {sheet_no}: the portal returned an invalid marks table."
            )
        label = str(row.get("QNo") or "").strip()
        maximum_text = str(row.get("QMaxMarks") or "").strip()
        try:
            maximum = Decimal(maximum_text)
        except InvalidOperation as exc:
            raise PortalError(
                f"Sheet {sheet_no}: invalid maximum for question {label!r}."
            ) from exc
        mark = row.get("Marks")
        result.append(
            (
                QuestionSpec(label, normalise_question_label(label), maximum),
                "" if mark is None else str(mark).strip(),
            )
        )
    return tuple(result)


def _mark_values_equal(actual: str, expected: str) -> bool:
    actual = actual.strip()
    expected = expected.strip()
    if actual == expected:
        return True
    if not actual or not expected:
        return False
    try:
        return Decimal(actual) == Decimal(expected)
    except InvalidOperation:
        return False


def _wait_for_student_table(
    page: Page,
    sheet_no: str,
    response_rows: tuple[tuple[QuestionSpec, str], ...],
    timeout_ms: int,
):
    """Wait until the response for the selected student is rendered in the UI."""
    expected = [
        (spec.key, spec.maximum, mark) for spec, mark in response_rows
    ]
    deadline = time.monotonic() + timeout_ms / 1000
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            table = _marks_table(page, min(500, timeout_ms))
            header = table.get_by_text(
                re.compile(
                    rf"^\s*Script Code:\s*{re.escape(sheet_no)}\s*$",
                    re.IGNORECASE,
                )
            ).first
            if header.count() and header.is_visible():
                rendered_rows = _question_rows(page, min(500, timeout_ms))
                actual = [
                    (spec.key, spec.maximum, mark_input.input_value().strip())
                    for spec, mark_input in rendered_rows
                ]
                if len(actual) == len(expected) and all(
                    actual_key == expected_key
                    and actual_maximum == expected_maximum
                    and _mark_values_equal(actual_mark, expected_mark)
                    for (actual_key, actual_maximum, actual_mark), (
                        expected_key,
                        expected_maximum,
                        expected_mark,
                    ) in zip(actual, expected, strict=True)
                ):
                    return rendered_rows
        except (PortalError, PlaywrightError) as exc:
            last_error = exc
        page.wait_for_timeout(50)

    detail = f" Last browser error: {last_error}" if last_error else ""
    raise PortalError(
        f"Sheet {sheet_no}: the selected student's marks table did not finish loading."
        f"{detail}"
    )


def _click_student_and_wait(
    page: Page, sheet_no: str, timeout_ms: int
):
    button = page.get_by_role(
        "button", name=re.compile(rf"^\s*{re.escape(sheet_no)}\s*$")
    ).first
    try:
        with page.expect_response(
            _is_marks_display_response, timeout=timeout_ms
        ) as response_info:
            button.click()
        response_rows = _display_rows(response_info.value, sheet_no)
        return _wait_for_student_table(page, sheet_no, response_rows, timeout_ms)
    except PlaywrightTimeoutError as exc:
        raise PortalError(
            f"Sheet {sheet_no}: no marks-table response was received."
        ) from exc


def _open_student_and_capture(
    page: Page,
    sheet_no: str,
    subject_code: str,
    timeout_ms: int,
) -> tuple[str, list[tuple[QuestionSpec, object]]]:
    button = page.get_by_role(
        "button", name=re.compile(rf"^\s*{re.escape(sheet_no)}\s*$")
    ).first
    try:
        with page.expect_request(
            lambda request: pdf_url_matches(request.url, subject_code, sheet_no),
            timeout=timeout_ms,
        ) as request_info, page.expect_response(
            _is_marks_display_response, timeout=timeout_ms
        ) as response_info:
            button.click()
        pdf_url = request_info.value.url
        response_rows = _display_rows(response_info.value, sheet_no)
    except PlaywrightTimeoutError as exc:
        raise PortalError(
            f"Sheet {sheet_no}: the PDF or marks-table request was not observed; "
            "the workbook or Subject Code may not match this bundle."
        ) from exc
    return pdf_url, _wait_for_student_table(
        page, sheet_no, response_rows, timeout_ms
    )


def _validate_upload(
    page: Page,
    inputs: EvaluationInputs,
    marks_workbook: MarksWorkbook,
    timeout_ms: int,
) -> tuple[list[StudentSchema], UploadSummary]:
    _open_bundle(page, inputs, timeout_ms)
    portal_numbers = _sheet_numbers(page, timeout_ms)
    workbook_students = {
        student.sheet_no: student for student in marks_workbook.students
    }
    if set(portal_numbers) != set(workbook_students):
        missing = sorted(set(portal_numbers) - set(workbook_students))
        extra = sorted(set(workbook_students) - set(portal_numbers))
        details = []
        if missing:
            details.append(f"missing sheets: {', '.join(missing)}")
        if extra:
            details.append(f"unexpected sheets: {', '.join(extra)}")
        raise PortalError(
            "Workbook does not match the portal bundle (" + "; ".join(details) + ")."
        )

    schemas: list[StudentSchema] = []
    total_questions = 0
    for sheet_no in portal_numbers:
        student = workbook_students[sheet_no]
        pdf_url, rows = _open_student_and_capture(
            page, sheet_no, inputs.subject_code, timeout_ms
        )
        if pdf_url != student.pdf_url:
            raise PortalError(
                f"Sheet {sheet_no}: PDF Link does not match the live portal."
            )
        if any(not mark_input.is_enabled() for _, mark_input in rows):
            raise PortalError(
                f"Sheet {sheet_no} cannot be edited; the bundle may already be finalized."
            )
        questions = tuple(spec for spec, _ in rows)
        portal_keys = [question.key for question in questions]
        if len(portal_keys) != len(set(portal_keys)):
            raise PortalError(
                f"Sheet {sheet_no}: portal question labels are duplicated."
            )
        workbook_keys = set(student.marks)
        if set(portal_keys) != workbook_keys:
            missing = [
                question.label
                for question in questions
                if question.key not in workbook_keys
            ]
            extra = sorted(workbook_keys - set(portal_keys))
            details = []
            if missing:
                details.append(f"missing questions: {', '.join(missing)}")
            if extra:
                details.append(f"unknown questions: {', '.join(extra)}")
            raise PortalError(f"Sheet {sheet_no}: " + "; ".join(details) + ".")
        for question in questions:
            mark = student.marks[question.key]
            if mark > question.maximum:
                raise PortalError(
                    f"Sheet {sheet_no}, question {question.label}: {mark} exceeds "
                    f"the maximum {question.maximum}."
                )
        schemas.append(StudentSchema(sheet_no, pdf_url, questions))
        total_questions += len(questions)

    question_counts = {len(schema.questions) for schema in schemas}
    question_count = next(iter(question_counts)) if len(question_counts) == 1 else 0
    return schemas, UploadSummary(
        student_count=len(schemas),
        question_count=question_count,
        mark_count=total_questions,
    )


def _format_mark(mark: Decimal) -> str:
    return format(mark, "f")


def _rows_by_key(page: Page, timeout_ms: int):
    rows = _question_rows(page, timeout_ms)
    result = {spec.key: (spec, mark_input) for spec, mark_input in rows}
    if len(result) != len(rows):
        raise PortalError("The portal question labels changed or are duplicated.")
    return result


def _validate_rendered_schema(
    schema: StudentSchema, rows_by_key: dict[str, tuple[QuestionSpec, object]]
) -> None:
    expected = {question.key: question.maximum for question in schema.questions}
    actual = {key: spec.maximum for key, (spec, _) in rows_by_key.items()}
    if actual != expected:
        raise PortalError(
            f"Sheet {schema.sheet_no}: the question table changed after preflight."
        )


def _wait_for_input_value(
    page: Page,
    schema: StudentSchema,
    question: QuestionSpec,
    expected: str,
    timeout_ms: int,
) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            rows_by_key = _rows_by_key(page, min(500, timeout_ms))
            _validate_rendered_schema(schema, rows_by_key)
            actual = rows_by_key[question.key][1].input_value()
            if _mark_values_equal(actual, expected):
                return
        except (KeyError, PortalError, PlaywrightError):
            pass
        page.wait_for_timeout(50)
    raise PortalError(
        f"Sheet {schema.sheet_no}, question {question.label}: "
        "the entered mark did not remain in the portal input."
    )


def _current_marks_total(
    page: Page, schema: StudentSchema, timeout_ms: int
) -> Decimal:
    rows_by_key = _rows_by_key(page, timeout_ms)
    _validate_rendered_schema(schema, rows_by_key)
    total = Decimal("0")
    for question in schema.questions:
        value = rows_by_key[question.key][1].input_value().strip()
        if not value:
            continue
        try:
            total += Decimal(value)
        except InvalidOperation as exc:
            raise PortalError(
                f"Sheet {schema.sheet_no}, question {question.label}: "
                "the portal input became non-numeric."
            ) from exc
    return total


def _validate_total_response(
    response,
    sheet_no: str,
    question: QuestionSpec,
    expected_total: Decimal,
) -> None:
    try:
        payload = response.json()
    except (PlaywrightError, ValueError) as exc:
        raise PortalError(
            f"Sheet {sheet_no}, question {question.label}: "
            "the total-validation response could not be read."
        ) from exc
    if not response.ok or not isinstance(payload, dict) or payload.get("Total") is None:
        raise PortalError(
            f"Sheet {sheet_no}, question {question.label}: "
            "the portal rejected total validation."
        )
    try:
        actual_total = Decimal(str(payload["Total"]))
    except InvalidOperation as exc:
        raise PortalError(
            f"Sheet {sheet_no}, question {question.label}: "
            "the portal returned an invalid total."
        ) from exc
    if actual_total != expected_total:
        raise PortalError(
            f"Sheet {sheet_no}, question {question.label}: the portal validated "
            f"a total of {actual_total}, but the displayed marks total "
            f"{expected_total}; marks were not saved."
        )


def _verify_all_entered_marks(
    page: Page,
    schema: StudentSchema,
    marks: dict[str, Decimal],
    timeout_ms: int,
) -> None:
    rows_by_key = _rows_by_key(page, timeout_ms)
    _validate_rendered_schema(schema, rows_by_key)
    for question in schema.questions:
        expected = marks[question.key]
        actual_text = rows_by_key[question.key][1].input_value().strip()
        try:
            actual = Decimal(actual_text)
        except InvalidOperation as exc:
            raise PortalError(
                f"Sheet {schema.sheet_no}, question {question.label}: "
                "the portal input is blank or non-numeric; marks were not saved."
            ) from exc
        if actual != expected:
            raise PortalError(
                f"Sheet {schema.sheet_no}, question {question.label}: expected "
                f"{_format_mark(expected)} but the portal shows {actual_text!r}; "
                "marks were not saved."
            )


def _save_student(
    page: Page,
    schema: StudentSchema,
    marks: dict[str, Decimal],
    timeout_ms: int,
) -> None:
    loaded_rows = _click_student_and_wait(page, schema.sheet_no, timeout_ms)
    _validate_rendered_schema(
        schema, {spec.key: (spec, mark_input) for spec, mark_input in loaded_rows}
    )

    def is_total_response(response) -> bool:
        return (
            "MIDValuaterSavingMarksCheckTotalGridNew" in response.url
            and response.request.method == "POST"
        )

    for question in schema.questions:
        expected = _format_mark(marks[question.key])
        try:
            rows_by_key = _rows_by_key(page, timeout_ms)
            _validate_rendered_schema(schema, rows_by_key)
            mark_input = rows_by_key[question.key][1]
            mark_input.click()
            mark_input.select_text()
            mark_input.press_sequentially(expected, delay=50)
            _wait_for_input_value(page, schema, question, expected, timeout_ms)
            expected_total = _current_marks_total(page, schema, timeout_ms)
            with page.expect_response(
                is_total_response, timeout=timeout_ms
            ) as response_info:
                mark_input.press("Tab")
            total_response = response_info.value
        except PlaywrightTimeoutError as exc:
            raise PortalError(
                f"Sheet {schema.sheet_no}, question {question.label}: "
                "the portal did not validate the marks total."
            ) from exc
        except (KeyError, PlaywrightError) as exc:
            raise PortalError(
                f"Sheet {schema.sheet_no}, question {question.label}: "
                "the mark could not be entered."
            ) from exc
        _validate_total_response(
            total_response, schema.sheet_no, question, expected_total
        )
        _wait_for_input_value(
            page, schema, question, expected, timeout_ms
        )

    _verify_all_entered_marks(page, schema, marks, timeout_ms)

    try:
        with page.expect_response(
            lambda response: (
                "MIDSecuritySavingMarksNew" in response.url
                and response.request.method == "POST"
            ),
            timeout=timeout_ms,
        ) as response_info:
            page.get_by_role(
                "button", name=re.compile(r"^\s*SAVE\s*$", re.IGNORECASE)
            ).click()
        response = response_info.value
        payload = response.json()
    except PlaywrightTimeoutError as exc:
        raise PortalError(
            f"Sheet {schema.sheet_no}: no save response was received."
        ) from exc
    except (PlaywrightError, ValueError) as exc:
        raise PortalError(
            f"Sheet {schema.sheet_no}: the save response could not be read."
        ) from exc
    if (
        not response.ok
        or payload.get("SavingMarksToGrid") != "SuccessFully Saved Data."
    ):
        message = (
            payload.get("SavingMarksToGrid")
            or payload.get("Message")
            or "unknown error"
        )
        raise PortalError(f"Sheet {schema.sheet_no}: portal save failed: {message}")
    page.evaluate("sessionStorage.removeItem('markslist2')")


def upload_from_page(
    page: Page,
    inputs: EvaluationInputs,
    marks_workbook: MarksWorkbook,
    confirm: Callable[[UploadSummary], bool],
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> int:
    """Validate the full workbook, confirm once, then save each student."""
    schemas, summary = _validate_upload(page, inputs, marks_workbook, timeout_ms)
    if not confirm(summary):
        raise UploadCancelled("Upload cancelled; no marks were changed.")

    students = {student.sheet_no: student for student in marks_workbook.students}
    saved = 0
    for schema in schemas:
        try:
            _save_student(page, schema, students[schema.sheet_no].marks, timeout_ms)
        except PortalError as exc:
            raise PortalError(
                f"Stopped after saving {saved} of {len(schemas)} students. {exc}"
            ) from exc
        saved += 1
    return saved


def upload_marks(
    inputs: EvaluationInputs,
    marks_workbook: MarksWorkbook,
    confirm: Callable[[UploadSummary], bool],
    *,
    headless: bool = False,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> int:
    """Launch Chromium and perform the validated marks upload."""
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            try:
                page = browser.new_page()
                return upload_from_page(
                    page, inputs, marks_workbook, confirm, timeout_ms
                )
            finally:
                browser.close()
    except (PortalError, UploadCancelled):
        raise
    except PlaywrightError as exc:
        message = str(exc)
        if "Executable doesn't exist" in message:
            raise PortalError(
                "Playwright Chromium is not installed. Run: playwright install chromium"
            ) from exc
        raise PortalError(f"Browser automation failed: {message}") from exc


def extract_from_page(
    page: Page,
    inputs: EvaluationInputs,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> list[AnswerSheet]:
    """Run the portal workflow in an existing page (also useful for tests)."""
    _open_bundle(page, inputs, timeout_ms)
    sheet_numbers = _sheet_numbers(page, timeout_ms)
    return _capture_pdf_urls(page, sheet_numbers, inputs.subject_code, timeout_ms)


def fetch_answer_sheets(
    inputs: EvaluationInputs,
    *,
    headless: bool = False,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> list[AnswerSheet]:
    """Launch Chromium, extract answer-sheet URLs, and always close the browser."""
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            try:
                page = browser.new_page()
                return extract_from_page(page, inputs, timeout_ms)
            finally:
                browser.close()
    except PortalError:
        raise
    except PlaywrightError as exc:
        message = str(exc)
        if "Executable doesn't exist" in message:
            raise PortalError(
                "Playwright Chromium is not installed. Run: playwright install chromium"
            ) from exc
        raise PortalError(f"Browser automation failed: {message}") from exc
