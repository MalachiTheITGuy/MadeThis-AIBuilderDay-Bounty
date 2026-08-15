"""Dev entrypoint for the gtm-loop API.

Usage:
    python run.py            # serve the API + UI on http://127.0.0.1:8000
    python run.py --demo     # same, with a fast 10s heartbeat for demos
"""

import argparse
import os
import sys

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="gtm-loop API")
    parser.add_argument("--demo", action="store_true", help="10s heartbeat (demo mode)")
    args = parser.parse_args()

    if args.demo:
        os.environ.setdefault("HEARTBEAT_INTERVAL_SECONDS", "10")

    host = os.environ.get("GTM_HOST", "127.0.0.1")
    port = int(os.environ.get("GTM_PORT", "8000"))
    uvicorn.run("src.api.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    sys.exit(main())
