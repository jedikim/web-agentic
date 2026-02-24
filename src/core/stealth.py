"""Browser stealth — anti-detection patches for Playwright contexts.

Applies JavaScript init-scripts to mask automation fingerprints.
Three stealth levels control how many patches are applied:

- **minimal**: suppress ``navigator.webdriver`` only.
- **standard**: + chrome.runtime, plugins, mimeTypes, permissions.
- **aggressive**: + WebGL vendor/renderer spoofing, canvas noise.

No external dependencies (no ``playwright-stealth`` package).
"""
from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from src.core.config import StealthConfig

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext

logger = logging.getLogger(__name__)


# ── Realistic User-Agent Rotation ────────────────────

_USER_AGENTS = [
    # Windows — Chrome 124
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    # macOS — Chrome 124
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    # Linux — Chrome 124
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
]


# ── JavaScript Patches ───────────────────────────────

# Level: minimal — just remove navigator.webdriver
_PATCH_WEBDRIVER = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});
"""

# Level: standard — chrome.runtime, plugins, mimeTypes, permissions
_PATCH_CHROME_RUNTIME = """
window.chrome = window.chrome || {};
window.chrome.runtime = {
    connect: function() {},
    sendMessage: function() {},
    onMessage: { addListener: function() {} },
    id: undefined,
};
"""

_PATCH_PLUGINS = """
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer',
              description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
              description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin',
              description: '' },
        ];
        plugins.length = 3;
        return plugins;
    },
});
"""

_PATCH_MIMETYPES = """
Object.defineProperty(navigator, 'mimeTypes', {
    get: () => {
        const mimes = [
            { type: 'application/pdf', suffixes: 'pdf',
              description: 'Portable Document Format',
              enabledPlugin: { name: 'Chrome PDF Plugin' } },
        ];
        mimes.length = 1;
        return mimes;
    },
});
"""

_PATCH_PERMISSIONS = """
const originalQuery = window.navigator.permissions.query.bind(
    window.navigator.permissions
);
window.navigator.permissions.query = (params) => {
    if (params.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission });
    }
    return originalQuery(params);
};
"""

# Level: aggressive — WebGL, canvas fingerprint noise
_PATCH_WEBGL = """
(function() {
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Intel Inc.';
        if (param === 37446) return 'Intel Iris OpenGL Engine';
        return getParam.call(this, param);
    };
})();
"""

_PATCH_CANVAS = """
(function() {
    const toBlob = HTMLCanvasElement.prototype.toBlob;
    const toDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toBlob = function() {
        const ctx = this.getContext('2d');
        if (ctx) {
            const style = ctx.fillStyle;
            ctx.fillStyle = 'rgba(0,0,1,0.01)';
            ctx.fillRect(0, 0, 1, 1);
            ctx.fillStyle = style;
        }
        return toBlob.apply(this, arguments);
    };
    HTMLCanvasElement.prototype.toDataURL = function() {
        const ctx = this.getContext('2d');
        if (ctx) {
            const style = ctx.fillStyle;
            ctx.fillStyle = 'rgba(0,0,1,0.01)';
            ctx.fillRect(0, 0, 1, 1);
            ctx.fillStyle = style;
        }
        return toDataURL.apply(this, arguments);
    };
})();
"""


def _get_patches(level: str) -> list[str]:
    """Return the list of JS patch strings for a given stealth level."""
    patches: list[str] = [_PATCH_WEBDRIVER]

    if level in ("standard", "aggressive"):
        patches.extend([
            _PATCH_CHROME_RUNTIME,
            _PATCH_PLUGINS,
            _PATCH_MIMETYPES,
            _PATCH_PERMISSIONS,
        ])

    if level == "aggressive":
        patches.extend([_PATCH_WEBGL, _PATCH_CANVAS])

    return patches


def get_patch_count(level: str) -> int:
    """Return how many JS patches a stealth level applies."""
    return len(_get_patches(level))


# ── Public API ───────────────────────────────────────


async def apply_stealth(
    context: BrowserContext,
    config: StealthConfig,
) -> None:
    """Apply stealth JS patches to an existing BrowserContext.

    Each patch is injected via ``context.add_init_script()`` so it runs
    before any page JS executes.

    Args:
        context: A Playwright BrowserContext.
        config: Stealth configuration.
    """
    if not config.enabled:
        logger.debug("Stealth disabled — skipping patches")
        return

    patches = _get_patches(config.level)
    for patch in patches:
        await context.add_init_script(patch)

    logger.info(
        "Applied %d stealth patches (level=%s)", len(patches), config.level
    )


async def create_stealth_context(
    browser: Browser,
    config: StealthConfig,
) -> BrowserContext:
    """Create a new BrowserContext with stealth patches applied.

    Sets realistic viewport, user-agent, locale, and timezone, then
    injects all stealth JS patches.

    Args:
        browser: The Playwright Browser to create a context on.
        config: Stealth configuration.

    Returns:
        A configured BrowserContext.
    """
    # User-agent selection
    ua = config.user_agent or random.choice(_USER_AGENTS)

    # Viewport with optional jitter
    base_width, base_height = 1920, 1080
    if config.randomize_viewport:
        j = config.viewport_jitter_px
        width = base_width + random.randint(-j, j)
        height = base_height + random.randint(-j, j)
    else:
        width, height = base_width, base_height

    context = await browser.new_context(
        viewport={"width": width, "height": height},
        user_agent=ua,
        locale=config.locale,
        timezone_id=config.timezone_id,
    )

    await apply_stealth(context, config)
    return context
