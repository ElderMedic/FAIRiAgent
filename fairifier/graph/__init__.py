"""LangGraph workflow implementation for FAIRifier."""

__all__ = ["FAIRifierLangGraphApp"]


def __getattr__(name: str):
    if name == "FAIRifierLangGraphApp":
        from .app import FAIRifierLangGraphApp

        return FAIRifierLangGraphApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
