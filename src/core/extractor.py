"""E(Extractor) module — DOM extraction with zero LLM token cost.

Extracts interactive elements, product data, and page state from the
live DOM using Playwright's page.evaluate() for JavaScript execution.
Handles iframes, Shadow DOM, and generates unique element IDs (eids)
based on CSS selectors.

See docs/PRD.md section 3.2 and docs/ARCHITECTURE.md for design context.
"""
from __future__ import annotations

import logging

from playwright.async_api import Page

from src.core.types import ExtractedElement, PageState, ProductData
from src.observability.tracing import trace

logger = logging.getLogger(__name__)

# Maximum length for truncated visible text in PageState.
_MAX_VISIBLE_TEXT = 2000


# ── JavaScript snippets executed via page.evaluate() ─────────────

_JS_EXTRACT_INPUTS = """
() => {
    const results = [];

    function processRoot(root, prefix) {
        const selectors = 'input, textarea, select';
        const elements = root.querySelectorAll(selectors);
        elements.forEach((el, i) => {
            const rect = el.getBoundingClientRect();
            const visible = rect.width > 0 && rect.height > 0
                && getComputedStyle(el).visibility !== 'hidden'
                && getComputedStyle(el).display !== 'none';
            const tag = el.tagName.toLowerCase();
            let eid;
            if (el.id) {
                eid = `${prefix}#${el.id}`;
            } else if (el.name) {
                eid = `${prefix}${tag}[name="${el.name}"]`;
            } else if (el.placeholder) {
                const ph = el.placeholder.slice(0, 30).replace(/"/g, '\\"');
                eid = `${prefix}${tag}[placeholder*="${ph}"]`;
            } else if (el.getAttribute('aria-label')) {
                const al = el.getAttribute('aria-label').slice(0, 30).replace(/"/g, '\\"');
                eid = `${prefix}${tag}[aria-label*="${al}"]`;
            } else {
                const nth = Array.from(el.parentElement?.children || [])
                    .filter(c => c.tagName === el.tagName)
                    .indexOf(el) + 1;
                eid = `${prefix}${tag}:nth-of-type(${nth})`;
            }
            const typeAttr = el.getAttribute('type') || el.tagName.toLowerCase();
            const text = el.placeholder || el.getAttribute('aria-label')
                || el.labels?.[0]?.textContent?.trim() || null;
            const role = el.getAttribute('role') || null;
            const parentEl = el.closest('form, fieldset, section, div[class]');
            const parentContext = parentEl
                ? (parentEl.getAttribute('aria-label')
                    || parentEl.className?.split?.(' ')?.[0]
                    || null)
                : null;
            const landmarkEl = el.closest('nav, header, footer, aside, main, section');
            const landmarkTag = landmarkEl ? landmarkEl.tagName.toLowerCase() : null;
            results.push({
                eid,
                type: typeAttr === 'textarea' ? 'input' : 'input',
                text,
                role,
                bbox: [
                    Math.round(rect.x), Math.round(rect.y),
                    Math.round(rect.width), Math.round(rect.height)
                ],
                visible,
                parent_context: parentContext,
                landmark: landmarkTag,
            });
        });
    }

    // Main document
    processRoot(document, '');

    // Iframes (same-origin only)
    try {
        document.querySelectorAll('iframe').forEach((iframe, fi) => {
            try {
                const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
                if (iframeDoc) {
                    processRoot(iframeDoc, `iframe[${fi}] `);
                }
            } catch(e) { /* cross-origin, skip */ }
        });
    } catch(e) {}

    // Shadow DOM
    document.querySelectorAll('*').forEach(el => {
        if (el.shadowRoot) {
            processRoot(el.shadowRoot, `shadow(${el.tagName.toLowerCase()}) `);
        }
    });

    return results;
}
"""

_JS_EXTRACT_CLICKABLES = """
() => {
    const results = [];
    const seen = new Set();

    function processRoot(root, prefix) {
        const selectors = [
            'a[href]',
            'button',
            '[role="button"]',
            '[role="tab"]',
            '[role="link"]',
            '[role="menuitem"]',
            '[role="option"]',
            '[onclick]',
            '[tabindex="0"]',
            'summary',
            'label[for]',
        ].join(', ');
        const elements = root.querySelectorAll(selectors);
        elements.forEach((el, i) => {
            const rect = el.getBoundingClientRect();
            const visible = rect.width > 0 && rect.height > 0
                && getComputedStyle(el).visibility !== 'hidden'
                && getComputedStyle(el).display !== 'none';
            const tag = el.tagName.toLowerCase();
            let eid;
            if (el.id) {
                eid = `${prefix}#${el.id}`;
            } else if (el.getAttribute('aria-label')) {
                const al = el.getAttribute('aria-label').slice(0, 30).replace(/"/g, '\\"');
                eid = `${prefix}${tag}[aria-label*="${al}"]`;
            } else {
                const text = (el.textContent || '').trim().slice(0, 20);
                if (text && text.length >= 2) {
                    eid = `${prefix}${tag}:has-text("${text.replace(/"/g, '\\"')}")`;
                } else if (tag === 'a' && el.href) {
                    const href = el.getAttribute('href') || '';
                    const short = href.slice(0, 60).replace(/"/g, '\\"');
                    eid = `${prefix}a[href="${short}"]`;
                } else {
                    const nth = Array.from(el.parentElement?.children || [])
                        .filter(c => c.tagName === el.tagName)
                        .indexOf(el) + 1;
                    eid = `${prefix}${tag}:nth-of-type(${nth})`;
                }
            }
            if (seen.has(eid)) return;
            seen.add(eid);

            let elType = 'button';
            if (tag === 'a') elType = 'link';
            else if (el.getAttribute('role') === 'tab') elType = 'tab';
            else if (el.getAttribute('role') === 'option') elType = 'option';
            else if (el.getAttribute('role') === 'menuitem') elType = 'button';

            const text = (el.textContent || '').trim().slice(0, 200) || null;
            const role = el.getAttribute('role') || null;
            const parentEl = el.closest('nav, header, footer, aside, section, div[class]');
            const parentContext = parentEl
                ? (parentEl.getAttribute('aria-label')
                    || parentEl.className?.split?.(' ')?.[0]
                    || null)
                : null;
            const landmarkEl = el.closest('nav, header, footer, aside, main, section');
            const landmarkTag = landmarkEl ? landmarkEl.tagName.toLowerCase() : null;

            results.push({
                eid,
                type: elType,
                text,
                role,
                bbox: [
                    Math.round(rect.x), Math.round(rect.y),
                    Math.round(rect.width), Math.round(rect.height)
                ],
                visible,
                parent_context: parentContext,
                landmark: (landmarkTag === 'div') ? null : landmarkTag,
            });
        });
    }

    processRoot(document, '');

    try {
        document.querySelectorAll('iframe').forEach((iframe, fi) => {
            try {
                const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
                if (iframeDoc) {
                    processRoot(iframeDoc, `iframe[${fi}] `);
                }
            } catch(e) {}
        });
    } catch(e) {}

    document.querySelectorAll('*').forEach(el => {
        if (el.shadowRoot) {
            processRoot(el.shadowRoot, `shadow(${el.tagName.toLowerCase()}) `);
        }
    });

    return results;
}
"""

_JS_EXTRACT_PRODUCTS = """
() => {
    const results = [];
    // Schema.org / data-attribute standards only — no class-name selectors
    const cardSelectors = [
        '[itemtype*="Product"]',
        '[data-product]',
        '[itemscope][itemtype*="schema.org"]',
    ];

    let cards = [];
    for (const sel of cardSelectors) {
        cards = document.querySelectorAll(sel);
        if (cards.length > 0) break;
    }

    cards.forEach(card => {
        // Use Schema.org itemprop attributes + semantic HTML only
        const nameEl = card.querySelector(
            '[itemprop="name"], h2, h3, h4'
        );
        const priceEl = card.querySelector(
            '[itemprop="price"], [itemprop="priceCurrency"]'
        );
        const linkEl = card.querySelector('a[href]');
        const imgEl = card.querySelector('img');
        const ratingEl = card.querySelector('[itemprop="ratingValue"]');
        const reviewEl = card.querySelector('[itemprop="reviewCount"]');

        const name = nameEl?.textContent?.trim();
        if (!name) return;

        const price = priceEl?.textContent?.trim() || null;
        const url = linkEl?.href || null;
        const image_url = imgEl?.src || imgEl?.dataset?.src || null;

        let rating = null;
        if (ratingEl) {
            const ratingText = ratingEl.textContent?.trim();
            const parsed = parseFloat(ratingText);
            if (!isNaN(parsed)) rating = parsed;
        }

        let review_count = null;
        if (reviewEl) {
            const match = reviewEl.textContent?.match(/(\\d[\\d,]*)/);
            if (match) review_count = parseInt(match[1].replace(/,/g, ''), 10);
        }

        results.push({ name, price, url, image_url, rating, review_count });
    });

    return results;
}
"""

_JS_EXTRACT_STATE = """
() => {
    const body = document.body;
    const visibleText = body ? body.innerText || '' : '';

    // Count interactive elements
    const interactiveSelectors = 'a, button, input, textarea, select, [role="button"], [tabindex]';
    const elementCount = document.querySelectorAll(interactiveSelectors).length;

    // Popup detection — ARIA standard + CSS property based (no class names)
    const ariaDialogs = document.querySelectorAll('[role="dialog"], [role="alertdialog"]');
    let hasPopup = false;
    let dialogText = '';

    // Check ARIA dialogs first
    for (const el of ariaDialogs) {
        const style = getComputedStyle(el);
        if (style.display !== 'none' && style.visibility !== 'hidden') {
            hasPopup = true;
            dialogText = (el.textContent || '').trim().slice(0, 500);
            break;
        }
    }

    // CSS property-based overlay detection (no class name dependency)
    if (!hasPopup) {
        const allEls = document.querySelectorAll('*');
        for (const el of allEls) {
            const s = getComputedStyle(el);
            if (s.position === 'fixed'
                && parseInt(s.zIndex || '0') > 900
                && el.offsetWidth > window.innerWidth * 0.3
                && el.offsetHeight > window.innerHeight * 0.3
                && s.display !== 'none' && s.visibility !== 'hidden') {
                hasPopup = true;
                dialogText = (el.textContent || '').trim().slice(0, 500);
                break;
            }
        }
    }

    // CAPTCHA detection — semantic signals only (no vendor-specific selectors)
    const captchaHints = document.querySelectorAll(
        '[class*="captcha" i], [id*="captcha" i], [class*="challenge" i]'
    );
    const iframeCount = document.querySelectorAll('iframe').length;
    const hasCaptcha = captchaHints.length > 0;

    return {
        url: window.location.href,
        title: document.title || '',
        visible_text: visibleText,
        element_count: elementCount,
        has_popup: hasPopup,
        has_captcha: hasCaptcha,
        dialog_text: dialogText,
        iframe_count: iframeCount,
        scroll_position: Math.round(window.scrollY || 0),
    };
}
"""


class DOMExtractor:
    """DOM extraction engine implementing the IExtractor protocol.

    All extraction happens via page.evaluate() JavaScript execution
    with zero LLM token cost. Handles iframes and Shadow DOM.

    Example:
        extractor = DOMExtractor()
        inputs = await extractor.extract_inputs(page)
        state = await extractor.extract_state(page)
    """

    @trace(name="extract-inputs")
    async def extract_inputs(self, page: Page) -> list[ExtractedElement]:
        """Extract form inputs, textareas, and selects from the page.

        Args:
            page: Playwright Page instance.

        Returns:
            List of ExtractedElement for each input-like element found.
        """
        raw: list[dict] = await page.evaluate(_JS_EXTRACT_INPUTS)
        return [self._to_element(item) for item in raw]

    @trace(name="extract-clickables")
    async def extract_clickables(self, page: Page) -> list[ExtractedElement]:
        """Extract buttons, links, tabs, and other clickable elements.

        Args:
            page: Playwright Page instance.

        Returns:
            List of ExtractedElement for each clickable element found.
        """
        raw: list[dict] = await page.evaluate(_JS_EXTRACT_CLICKABLES)
        return [self._to_element(item) for item in raw]

    @trace(name="extract-products")
    async def extract_products(self, page: Page) -> list[ProductData]:
        """Extract product cards from e-commerce pages.

        Searches for common product card patterns (data-product,
        schema.org Product, class-based selectors) and extracts
        name, price, URL, image, rating, and review count.

        Args:
            page: Playwright Page instance.

        Returns:
            List of ProductData for each product card found.
        """
        raw: list[dict] = await page.evaluate(_JS_EXTRACT_PRODUCTS)
        return [self._to_product(item) for item in raw]

    @trace(name="extract-state")
    async def extract_state(self, page: Page) -> PageState:
        """Extract current page state snapshot.

        Captures URL, title, truncated visible text, element count,
        popup/captcha detection, and scroll position.

        Args:
            page: Playwright Page instance.

        Returns:
            PageState representing the current page snapshot.
        """
        raw: dict = await page.evaluate(_JS_EXTRACT_STATE)
        visible_text = (raw.get("visible_text") or "")[:_MAX_VISIBLE_TEXT]
        return PageState(
            url=raw.get("url", ""),
            title=raw.get("title", ""),
            visible_text=visible_text,
            element_count=raw.get("element_count", 0),
            has_popup=raw.get("has_popup", False),
            has_captcha=raw.get("has_captcha", False),
            dialog_text=raw.get("dialog_text", ""),
            iframe_count=raw.get("iframe_count", 0),
            scroll_position=raw.get("scroll_position", 0),
        )

    # ── Private helpers ──────────────────────────────────

    @staticmethod
    def _to_element(data: dict) -> ExtractedElement:
        """Convert a raw JS dict to an ExtractedElement dataclass.

        Args:
            data: Dictionary from page.evaluate() result.

        Returns:
            Frozen ExtractedElement instance.
        """
        bbox_raw = data.get("bbox", [0, 0, 0, 0])
        bbox = (
            int(bbox_raw[0]) if len(bbox_raw) > 0 else 0,
            int(bbox_raw[1]) if len(bbox_raw) > 1 else 0,
            int(bbox_raw[2]) if len(bbox_raw) > 2 else 0,
            int(bbox_raw[3]) if len(bbox_raw) > 3 else 0,
        )
        return ExtractedElement(
            eid=data.get("eid", ""),
            type=data.get("type", ""),
            text=data.get("text"),
            role=data.get("role"),
            bbox=bbox,
            visible=data.get("visible", True),
            parent_context=data.get("parent_context"),
            landmark=data.get("landmark"),
        )

    @staticmethod
    def _to_product(data: dict) -> ProductData:
        """Convert a raw JS dict to a ProductData dataclass.

        Args:
            data: Dictionary from page.evaluate() result.

        Returns:
            Frozen ProductData instance.
        """
        return ProductData(
            name=data.get("name", ""),
            price=data.get("price"),
            url=data.get("url"),
            image_url=data.get("image_url"),
            rating=data.get("rating"),
            review_count=data.get("review_count"),
        )
