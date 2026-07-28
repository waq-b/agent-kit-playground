#!/usr/bin/env python
"""Write the playground's OpenAPI schema to frontend/openapi.json.

The frontend generates its TypeScript types from this file rather than
hand-writing interfaces, so the types track the real Pydantic models. Run
offline against the imported app — no server needs to be listening.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_kit.playground.app import app  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "frontend" / "openapi.json"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"wrote {OUT.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
