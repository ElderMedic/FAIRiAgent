import os
import sys
import ctypes
import logging

logger = logging.getLogger(__name__)

def apply_libstdcxx_fix():
    """
    Patch for libstdc++ version mismatch in Conda/Mamba environments.
    
    On some Linux systems, the system-wide libstdc++.so.6 is older than the one
    required by libraries in the Conda environment (like libicu, used by sqlite3).
    Pre-load the environment's version before importing native extensions.
    Loading it after another extension selected the system library cannot
    replace that library's already-bound ABI. A nested venv may keep native
    libraries in its base interpreter environment rather than in sys.prefix.
    """
    if not sys.platform.startswith("linux"):
        return

    for prefix in dict.fromkeys((sys.prefix, sys.base_prefix)):
        env_lib_path = os.path.join(prefix, "lib", "libstdc++.so.6")
        if not os.path.exists(env_lib_path):
            logger.debug("Environment libstdc++ not found at %s", env_lib_path)
            continue
        try:
            # Pre-load the correct libstdc++ with global scope
            # mode=ctypes.RTLD_GLOBAL ensures it's available for other libraries
            ctypes.CDLL(env_lib_path, mode=ctypes.RTLD_GLOBAL)
            logger.debug("Pre-loaded environment libstdc++ from %s", env_lib_path)
            return
        except Exception as e:
            logger.warning(f"Failed to pre-load environment libstdc++ from {env_lib_path}: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    apply_libstdcxx_fix()
