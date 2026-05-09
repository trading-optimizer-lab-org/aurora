"""PDF tearsheet renderer skeleton (R84).

Today the tearsheet ships as HTML. This module wraps the HTML render
pipeline with WeasyPrint (already in `pyproject.toml`'s `report`
extra) so operators can produce archivable PDFs.

Design choice: the HTML renderer already exists; this module renders
the same HTML to PDF rather than reinventing layout. Adding new
sections happens in the HTML renderer; this module follows for free.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PdfRenderConfig:
    """Knobs for the WeasyPrint render."""

    base_url: Optional[str] = None
    presentational_hints: bool = True


def render_html_to_pdf(
    html_source: str,
    output_path: Path,
    *,
    config: Optional[PdfRenderConfig] = None,
) -> Path:
    """Render an existing HTML tearsheet to PDF.

    Args:
        html_source: full HTML document as a string.
        output_path: where to write the PDF.
        config: WeasyPrint knobs.

    Returns:
        ``output_path`` on success.

    Raises:
        ImportError: ``weasyprint`` is not installed. The caller
            should install with ``pip install quantforge[report]``.
    """
    if config is None:
        config = PdfRenderConfig()
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise ImportError(
            "weasyprint is required for PDF rendering. "
            "Install via `pip install quantforge[report]`."
        ) from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(
        string=html_source,
        base_url=config.base_url,
    ).write_pdf(
        target=str(output_path),
        presentational_hints=config.presentational_hints,
    )
    return output_path


def can_render_pdf() -> bool:
    """True iff WeasyPrint is importable in the current environment."""
    try:
        import weasyprint  # noqa: F401
    except ImportError:
        return False
    return True


__all__ = [
    "PdfRenderConfig",
    "render_html_to_pdf",
    "can_render_pdf",
]
