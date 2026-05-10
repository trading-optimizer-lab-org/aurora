"""Preflight result dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PreflightCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class PreflightReport:
    checks: list[PreflightCheck]
    all_passed: bool
    blockers: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = ["=" * 70, "PREFLIGHT REPORT", "=" * 70]
        for c in self.checks:
            status = "PASS" if c.passed else "FAIL"
            line = f"[{status}] {c.name}"
            if c.detail:
                line += f" - {c.detail}"
            lines.append(line)
        lines.append("-" * 70)
        lines.append(f"OVERALL: {'PASS' if self.all_passed else 'FAIL'}")
        if self.blockers:
            lines.append("Blockers:")
            for b in self.blockers:
                lines.append(f"  - {b}")
        lines.append("=" * 70)
        return "\n".join(lines)
