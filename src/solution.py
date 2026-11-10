"""Entry point for the deterministic Larkfield support core."""
from __future__ import annotations

import os

from .api import app


def main() -> None:
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
