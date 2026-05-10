"""Shared CSS for the HTML tearsheet."""
from __future__ import annotations


_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
       max-width: 1100px; margin: 30px auto; color: #222; background: #fafafa; padding: 0 20px; }
h1 { font-size: 26px; border-bottom: 2px solid #333; padding-bottom: 8px; }
h2 { font-size: 18px; color: #333; margin-top: 32px; border-left: 4px solid #1f77b4;
     padding-left: 10px; }
table { border-collapse: collapse; margin: 14px 0; font-size: 13px; }
th, td { padding: 6px 14px; text-align: right; border-bottom: 1px solid #ddd; }
th { background: #ececec; text-align: left; }
td.label { text-align: left; font-weight: 600; }
img { max-width: 100%; height: auto; display: block; margin: 8px 0; }
.section { background: white; padding: 18px 22px; margin: 16px 0;
           border: 1px solid #e0e0e0; border-radius: 5px; }
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
              margin: 12px 0; }
.stat { padding: 10px; background: #f0f4f9; border-left: 4px solid #1f77b4;
        border-radius: 3px; }
.stat .label { font-size: 11px; color: #666; text-transform: uppercase; }
.stat .value { font-size: 18px; font-weight: 600; color: #222; }
.muted { color: #888; font-size: 11px; }
.pos { color: #1a7e1a; }
.neg { color: #b22222; }
.split-tables { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
@media (max-width: 800px) { .split-tables { grid-template-columns: 1fr; } }
"""
