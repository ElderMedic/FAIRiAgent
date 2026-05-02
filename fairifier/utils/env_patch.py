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
    This function pre-loads the environment's version of libstdc++.so.6 to ensure
    it is used instead of the system version.
    """
    if not sys.platform.startswith("linux"):
        return

    # Path to the environment's libstdc++
    # Usually in <sys.prefix>/lib/libstdc++.so.6
    env_lib_path = os.path.join(sys.prefix, "lib", "libstdc++.so.6")
    
    if os.path.exists(env_lib_path):
        try:
            # Pre-load the correct libstdc++ with global scope
            # mode=ctypes.RTLD_GLOBAL ensures it's available for other libraries
            ctypes.CDLL(env_lib_path, mode=ctypes.RTLD_GLOBAL)
            logger.debug(f"Pre-loaded environment libstdc++ from {env_lib_path}")
        except Exception as e:
            logger.warning(f"Failed to pre-load environment libstdc++ from {env_lib_path}: {e}")
    else:
        logger.debug(f"Environment libstdc++ not found at {env_lib_path}, skipping patch")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    apply_libstdcxx_fix()
