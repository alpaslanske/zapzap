"""ZapZap executable module."""

import os
import sys

# =========================================================================
# CHROMIUM VE GPU PARAMETRELERİNİ EN BAŞTA ENJEKTE EDİYORUZ
# =========================================================================
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-gpu "
    "--disable-gpu-compositing "
    "--disable-vulkan "
    "--disable-features=Vulkan,VulkanFromANGLE "
    "--no-sandbox"
)
# =========================================================================

from zapzap.app.application import main


if __name__ == "__main__":
    sys.exit(main())
