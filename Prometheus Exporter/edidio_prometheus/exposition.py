"""Prometheus text exposition format (version 0.0.4), dependency-free.

A metric family is ``(name, type, help, samples)`` where each sample is
``(labels_dict, value)``. Kept pure so the output format is unit tested.
"""

from __future__ import annotations

import math

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _escape_label(value) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _escape_help(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def _format_value(value) -> str:
    value = float(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if value.is_integer():
        return str(int(value))
    return repr(value)


def render(families) -> str:
    """Render metric families to exposition text. Families with no samples still
    emit HELP/TYPE so dashboards can discover the metric."""
    out = []
    for name, mtype, help_text, samples in families:
        out.append(f"# HELP {name} {_escape_help(help_text)}")
        out.append(f"# TYPE {name} {mtype}")
        for labels, value in samples:
            if labels:
                body = ",".join(f'{k}="{_escape_label(v)}"' for k, v in sorted(labels.items()))
                out.append(f"{name}{{{body}}} {_format_value(value)}")
            else:
                out.append(f"{name} {_format_value(value)}")
    return "\n".join(out) + "\n"
