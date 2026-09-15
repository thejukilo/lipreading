"""``python -m server.api`` -> run the dev server."""

from __future__ import annotations


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="Lipreading multi-user API.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()
    uvicorn.run("server.api.main:app", host=args.host, port=args.port,
                reload=args.reload)


if __name__ == "__main__":
    main()
