"""FAIRifier Agentic Framework for automated FAIR metadata generation."""

import warnings

# Suppress Pydantic V2 deprecation warnings from third-party libraries (like LangSmith)
try:
    from pydantic.warnings import PydanticDeprecatedSince20
    warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)
except ImportError:
    pass

__version__ = "1.3.1"
