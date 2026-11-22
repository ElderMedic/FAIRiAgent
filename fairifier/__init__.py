"""FAIRifier Agentic Framework for automated FAIR metadata generation."""

import warnings

from .utils.env_patch import apply_libstdcxx_fix

# Native extensions must agree on the C++ runtime before the first one loads.
# This is a no-op outside Linux and when the environment has no bundled runtime.
apply_libstdcxx_fix()

# Suppress Pydantic V2 deprecation warnings from third-party libraries (like LangSmith)
try:
    from pydantic.warnings import PydanticDeprecatedSince20
    warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)
except ImportError:
    pass

__version__ = "2.3.2"
