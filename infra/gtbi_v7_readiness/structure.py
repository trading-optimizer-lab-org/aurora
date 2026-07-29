"""Structural validation for the exact GTBI V7 master plan."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

TASK_RE = re.compile(r"PREV7-\d{4}")
GATE_RE = re.compile(r"(?<![A-Z0-9])G(?:0|1A|1B|2|3A|3B|4|5|6A|6B|7|8|9X?|10)(?![A-Z0-9])")
TABLE_SPLIT_RE = re.compile(r"(?<!\\)\|")
URL_RE = re.compile(r"https?://[^\s)>`]+")


@dataclass(frozen=True)
class StructuralCheck:
    check_id: str
    passed: bool
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructuralValidationResult:
    checks: tuple[StructuralCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(
            f"{check.check_id}: {detail}"
            for check in self.checks
            if not check.passed
            for detail in (check.details or ("failed",))
        )

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": [
                {
                    "check_id": check.check_id,
                    "passed": check.passed,
                    "details": list(check.details),
                }
                for check in self.checks
            ],
        }


@dataclass(frozen=True)
class MasterTask:
    task_id: str
    priority: str
    owner_role: str
    dependencies: tuple[str, ...]
    required_output: str


@dataclass(frozen=True)
class MasterGate:
    gate_id: str
    prerequisite_gate_ids: tuple[str, ...]
    required_task_ids: tuple[str, ...]
    required_condition: str


@dataclass(frozen=True)
class MasterPlanModel:
    tasks: tuple[MasterTask, ...]
    gates: tuple[MasterGate, ...]
    primary_gate_by_task: dict[str, str]


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip().replace("\\|", "|") for cell in TABLE_SPLIT_RE.split(stripped)[1:-1]]


def _find_table(lines: list[str], header_cells: list[str]) -> list[list[str]]:
    for index, line in enumerate(lines):
        if _table_cells(line) == header_cells:
            rows: list[list[str]] = []
            for candidate in lines[index + 2 :]:
                cells = _table_cells(candidate)
                if not cells:
                    break
                rows.append(cells)
            return rows
    raise ValueError(f"missing table with header {header_cells!r}")


def _task_matrix(lines: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    rows = _find_table(
        lines, ["ID", "P", "Owner", "Dependencies", "Required output"]
    )
    dependencies: dict[str, list[str]] = {}
    duplicate_ids: list[str] = []
    for row in rows:
        if len(row) != 5 or not TASK_RE.fullmatch(row[0]):
            continue
        task_id = row[0]
        if task_id in dependencies:
            duplicate_ids.append(task_id)
        references = TASK_RE.findall(row[3]) + GATE_RE.findall(row[3])
        dependencies[task_id] = references
    return dependencies, duplicate_ids


def _priority_map(lines: list[str]) -> tuple[dict[str, int], list[str], list[int]]:
    rows = _find_table(lines, ["priority_step", "primary_task_ids"])
    priority: dict[str, int] = {}
    duplicates: list[str] = []
    steps: list[int] = []
    for row in rows:
        if len(row) != 2 or not row[0].isdigit():
            continue
        step = int(row[0])
        steps.append(step)
        for task_id in TASK_RE.findall(row[1]):
            if task_id in priority:
                duplicates.append(task_id)
            priority[task_id] = step
    return priority, duplicates, steps


def _expand_gate_tasks(cell: str, known_tasks: set[str]) -> set[str]:
    output = set(TASK_RE.findall(cell))
    range_re = re.compile(r"`?(PREV7-(\d{4}))`?\s+through\s+`?(PREV7-(\d{4}))`?")
    for match in range_re.finditer(cell):
        start = int(match.group(2))
        end = int(match.group(4))
        output.update(
            task_id
            for task_id in known_tasks
            if start <= int(task_id[-4:]) <= end
        )
    return output


def _gate_map(
    lines: list[str], known_tasks: set[str]
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    rows = _find_table(
        lines, ["Gate", "Gate prerequisites", "Required tasks or condition"]
    )
    required_tasks: dict[str, set[str]] = {}
    prerequisites: dict[str, set[str]] = {}
    for row in rows:
        if len(row) != 3:
            continue
        gates = GATE_RE.findall(row[0])
        if len(gates) != 1:
            continue
        gate_id = gates[0]
        prerequisites[gate_id] = set(GATE_RE.findall(row[1]))
        required_tasks[gate_id] = _expand_gate_tasks(row[2], known_tasks)
    return required_tasks, prerequisites


def load_master_plan_model(plan_path: str | Path) -> MasterPlanModel:
    """Parse the canonical task matrix and exact gate map from the plan."""
    path = Path(plan_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    task_rows = _find_table(
        lines, ["ID", "P", "Owner", "Dependencies", "Required output"]
    )
    tasks: list[MasterTask] = []
    seen_tasks: set[str] = set()
    for row in task_rows:
        if len(row) != 5 or not TASK_RE.fullmatch(row[0]):
            continue
        task_id = row[0]
        if task_id in seen_tasks:
            raise ValueError(f"duplicate task ID {task_id}")
        seen_tasks.add(task_id)
        dependencies = tuple(TASK_RE.findall(row[3]) + GATE_RE.findall(row[3]))
        tasks.append(
            MasterTask(
                task_id=task_id,
                priority=row[1],
                owner_role=row[2],
                dependencies=dependencies,
                required_output=row[4],
            )
        )
    if not tasks:
        raise ValueError("master task matrix is empty")

    gate_rows = _find_table(
        lines, ["Gate", "Gate prerequisites", "Required tasks or condition"]
    )
    known_tasks = {task.task_id for task in tasks}
    gates: list[MasterGate] = []
    for row in gate_rows:
        if len(row) != 3:
            continue
        gate_ids = GATE_RE.findall(row[0])
        if len(gate_ids) != 1:
            continue
        required_task_ids = tuple(sorted(_expand_gate_tasks(row[2], known_tasks)))
        gates.append(
            MasterGate(
                gate_id=gate_ids[0],
                prerequisite_gate_ids=tuple(GATE_RE.findall(row[1])),
                required_task_ids=required_task_ids,
                required_condition=row[2],
            )
        )
    if not gates:
        raise ValueError("master gate map is empty")

    primary_gate_by_task: dict[str, str] = {}
    for gate in gates:
        for task_id in gate.required_task_ids:
            primary_gate_by_task.setdefault(task_id, gate.gate_id)
    primary_gate_by_task.update(
        {
            "PREV7-0308": "G3B",
            "PREV7-0610": "G6B",
            "PREV7-0611": "G6B",
            "PREV7-0910": "G9X",
            "PREV7-0914": "G9X",
            "PREV7-0911": "G9X",
            "PREV7-0912": "G9X",
            "PREV7-0913": "G9",
        }
    )
    missing = sorted(known_tasks - set(primary_gate_by_task))
    if missing:
        raise ValueError(f"tasks missing primary gate: {missing}")
    return MasterPlanModel(
        tasks=tuple(tasks),
        gates=tuple(gates),
        primary_gate_by_task=primary_gate_by_task,
    )


def _cycle_errors(graph: dict[str, set[str]]) -> list[str]:
    visited: set[str] = set()
    active: list[str] = []
    errors: list[str] = []

    def visit(node: str) -> None:
        if node in active:
            cycle = active[active.index(node) :] + [node]
            errors.append(" -> ".join(cycle))
            return
        if node in visited:
            return
        active.append(node)
        for dependency in sorted(graph.get(node, ())):
            if dependency in graph:
                visit(dependency)
        active.pop()
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    return sorted(set(errors))


def _balanced_fences(lines: list[str]) -> list[str]:
    open_fence: tuple[int, str] | None = None
    for number, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if not stripped.startswith("```"):
            continue
        if open_fence is None:
            open_fence = (number, stripped[3:].strip())
        else:
            open_fence = None
    return [] if open_fence is None else [f"unclosed fence opened at line {open_fence[0]}"]


def _table_errors(lines: list[str]) -> list[str]:
    errors: list[str] = []
    in_fence = False
    index = 0
    while index < len(lines):
        stripped = lines[index].lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            index += 1
            continue
        if in_fence or not _table_cells(lines[index]):
            index += 1
            continue
        start = index
        rows: list[list[str]] = []
        while index < len(lines) and _table_cells(lines[index]):
            rows.append(_table_cells(lines[index]))
            index += 1
        if len(rows) < 2:
            continue
        separator = rows[1]
        if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
            continue
        width = len(rows[0])
        for offset, row in enumerate(rows):
            if len(row) != width:
                errors.append(
                    f"line {start + offset + 1}: expected {width} cells, got {len(row)}"
                )
    return errors


def _url_errors(lines: Iterable[str]) -> list[str]:
    errors: list[str] = []
    for number, line in enumerate(lines, 1):
        for value in URL_RE.findall(line):
            parsed = urlparse(value.rstrip(".,;"))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"line {number}: malformed URL {value}")
    return errors


def _forbidden_term_errors(
    path: Path, lines: list[str], rules: Iterable[dict]
) -> list[str]:
    errors: list[str] = []
    normalized_path = path.as_posix()
    for rule in rules:
        token = str(rule["token"])
        mode = str(rule["match_mode"])
        allowed = [
            re.compile(pattern)
            for pattern in rule.get("allowed_section_or_path_patterns", [])
        ]
        flags = re.IGNORECASE if mode == "case_insensitive" else 0
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])",
            flags,
        )
        for number, line in enumerate(lines, 1):
            if not pattern.search(line):
                continue
            locator = f"{normalized_path}#L{number}:{line}"
            if not any(candidate.search(locator) for candidate in allowed):
                errors.append(f"line {number}: forbidden token {token!r}")
    return errors


def validate_master_plan_structure(
    plan_path: str | Path,
    *,
    forbidden_term_rules: Iterable[dict] = (),
) -> StructuralValidationResult:
    """Validate the structural promises frozen by section 1.1."""
    path = Path(plan_path)
    raw = path.read_bytes()
    encoding_errors: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        encoding_errors.append("UTF-8 BOM is forbidden")
    if b"\r" in raw:
        encoding_errors.append("CR or CRLF bytes are forbidden")
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        encoding_errors.append("document must have exactly one final LF")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        encoding_errors.append(f"invalid UTF-8: {exc}")
        text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()

    checks: list[StructuralCheck] = [
        StructuralCheck("canonical_text_bytes", not encoding_errors, tuple(encoding_errors))
    ]
    try:
        task_dependencies, duplicate_matrix_ids = _task_matrix(lines)
        task_ids = set(task_dependencies)
    except ValueError as exc:
        task_dependencies, duplicate_matrix_ids, task_ids = {}, [], set()
        checks.append(StructuralCheck("unique_task_ids", False, (str(exc),)))
    else:
        checks.append(
            StructuralCheck(
                "unique_task_ids",
                bool(task_ids) and not duplicate_matrix_ids,
                tuple(f"duplicate task ID {value}" for value in duplicate_matrix_ids),
            )
        )

    known_gates = {
        "G0", "G1A", "G1B", "G2", "G3A", "G3B", "G4", "G5",
        "G6A", "G6B", "G7", "G8", "G9", "G9X", "G10",
    }
    unknown_references = sorted(
        {
            reference
            for refs in task_dependencies.values()
            for reference in refs
            if reference not in task_ids and reference not in known_gates
        }
    )
    checks.append(
        StructuralCheck(
            "known_dependency_references",
            not unknown_references,
            tuple(f"unknown dependency {value}" for value in unknown_references),
        )
    )

    try:
        gate_tasks, gate_dependencies = _gate_map(lines, task_ids)
    except ValueError as exc:
        gate_tasks, gate_dependencies = {}, {}
        complete_gate_check = StructuralCheck(
            "complete_gate_assignment", False, (str(exc),)
        )
    else:
        assigned = set().union(*gate_tasks.values()) if gate_tasks else set()
        missing_gate_assignments = sorted(task_ids - assigned)
        unknown_gate_tasks = sorted(assigned - task_ids)
        details = [
            *(f"task has no gate assignment: {value}" for value in missing_gate_assignments),
            *(f"gate references unknown task: {value}" for value in unknown_gate_tasks),
        ]
        complete_gate_check = StructuralCheck(
            "complete_gate_assignment", not details, tuple(details)
        )

    graph: dict[str, set[str]] = {
        task_id: set(refs) for task_id, refs in task_dependencies.items()
    }
    graph.update(
        {
            gate_id: set(gate_dependencies.get(gate_id, set()))
            | set(gate_tasks.get(gate_id, set()))
            for gate_id in known_gates
        }
    )
    cycle_errors = _cycle_errors(graph)
    checks.append(
        StructuralCheck(
            "acyclic_dependency_graph",
            not cycle_errors,
            tuple(f"dependency cycle: {value}" for value in cycle_errors),
        )
    )
    checks.append(complete_gate_check)

    try:
        priority, duplicate_priority_ids, steps = _priority_map(lines)
    except ValueError as exc:
        priority, duplicate_priority_ids, steps = {}, [], []
        priority_errors = [str(exc)]
    else:
        priority_errors = []
        expected_steps = list(range(1, 47))
        if steps != expected_steps:
            priority_errors.append(
                f"priority steps must be exactly 1..46, got {steps!r}"
            )
        for task_id in sorted(task_ids - set(priority)):
            priority_errors.append(f"task missing from priority table: {task_id}")
        for task_id in sorted(set(priority) - task_ids):
            priority_errors.append(f"unknown task in priority table: {task_id}")
        for task_id in duplicate_priority_ids:
            priority_errors.append(f"task repeated in priority table: {task_id}")
        for task_id, references in task_dependencies.items():
            for dependency in references:
                if dependency in priority and priority[dependency] > priority.get(task_id, 0):
                    priority_errors.append(
                        f"{task_id} step {priority[task_id]} precedes dependency "
                        f"{dependency} step {priority[dependency]}"
                    )
    checks.append(
        StructuralCheck(
            "contiguous_execution_order",
            not priority_errors,
            tuple(priority_errors),
        )
    )

    fence_errors = _balanced_fences(lines)
    checks.append(
        StructuralCheck("balanced_code_fences", not fence_errors, tuple(fence_errors))
    )
    table_errors = _table_errors(lines)
    checks.append(
        StructuralCheck("valid_markdown_tables", not table_errors, tuple(table_errors))
    )
    url_errors = _url_errors(lines)
    checks.append(StructuralCheck("valid_urls", not url_errors, tuple(url_errors)))
    forbidden_errors = _forbidden_term_errors(path, lines, forbidden_term_rules)
    checks.append(
        StructuralCheck(
            "no_stale_forbidden_terms",
            not forbidden_errors,
            tuple(forbidden_errors),
        )
    )
    return StructuralValidationResult(tuple(checks))
