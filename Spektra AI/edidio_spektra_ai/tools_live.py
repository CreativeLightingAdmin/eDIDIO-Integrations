"""MCP tools for live operations, diagnostics, device settings and live authoring
of lists / inputs / outputs / logic. Registered on the shared ``server`` (imported
by server.py). Reads and transient actions run at once; anything the controller
stores goes through preview -> confirm(token), like the rest of Spektra AI.

Indices in every tool are 0-based (as the controller and the .spektra file use
them); replies also show the 1-based name a person sees ("List 3 (index 2)").

The tools live in edidio_spektra_ai/live/, one module per topic. This module imports
them all (which registers their tools on the server) and re-exports every name, so
`from edidio_spektra_ai import tools_live` keeps working as before. To replace a name
for a test, patch it on the module that defines it (e.g. live.programming).
"""

from __future__ import annotations

from .live import (common, dali_tools, diagnostics, programming, rdm_tools, sd_card,
                   settings, state)

for _m in (common, state, diagnostics, settings, programming, sd_card, dali_tools, rdm_tools):
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith("__")})
del _m
