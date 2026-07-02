"""Local lipreading inference server package."""

__all__ = ["LipreadingEngine"]


def __getattr__(name):
    # Lazy so `python -m server.engine` doesn't re-import engine via the package
    # (avoids a spurious runpy RuntimeWarning) and so importing the package
    # doesn't pull torch until it's actually needed.
    if name == "LipreadingEngine":
        from .engine import LipreadingEngine

        return LipreadingEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
