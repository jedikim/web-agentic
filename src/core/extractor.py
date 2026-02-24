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
            const eid = el.id
                ? `${prefix}#${el.id}`
                : el.name
                    ? `${prefix}${el.tagName.toLowerCase()}[name="${el.name}"]`
                    : `${prefix}${el.tagName.toLowerCase()}:nth-of-type(${i + 1})`;
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
            const eid = el.id
                ? `${prefix}#${el.id}`
                : `${prefix}${tag}:nth-of-type(${i + 1})`;
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
    const cardSelectors = [
        '[data-product]',
        '[itemtype*="Product"]',
        '.product-card',
        '.product-item',
        '.product',
        'li[class*="product"]',
        'div[class*="product"]',
        '[class*="item-card"]',
        '[class*="goods"]',
    ];

    let cards = [];
    for (const sel of cardSelectors) {
        cards = document.querySelectorAll(sel);
        if (cards.length > 0) break;
    }

    cards.forEach(card => {
        const nameEl = card.querySelector(
            '[class*="name"], [class*="title"], h2, h3, h4, [itemprop="name"]'
        );
        const priceEl = card.querySelector(
            '[class*="price"], [itemprop="price"], .cost, .amount'
        );
        const linkEl = card.querySelector('a[href]');
        const imgEl = card.querySelector('img');
        const ratingEl = card.querySelector(
            '[class*="rating"], [class*="star"], [itemprop="ratingValue"]'
        );
        const reviewEl = card.querySelector(
            '[class*="review"], [class*="count"]'
        );

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

    // Popup detection
    const popupSelectors = [
        '[class*="modal"]', '[class*="popup"]', '[class*="overlay"]',
        '[class*="dialog"]', '[role="dialog"]', '[role="alertdialog"]',
        '[class*="layer"]',
    ];
    let hasPopup = false;
    for (const sel of popupSelectors) {
        const el = document.querySelector(sel);
        if (el) {
            const style = getComputedStyle(el);
            if (style.display !== 'none' && style.visibility !== 'hidden') {
                hasPopup = true;
                break;
            }
        }
    }

    // CAPTCHA detection
    const captchaSelectors = [
        '[class*="captcha"]', '[id*="captcha"]',
        'iframe[src*="recaptcha"]', 'iframe[src*="hcaptcha"]',
        '[class*="challenge"]', '#captcha',
    ];
    let hasCaptcha = false;
    for (const sel of captchaSelectors) {
        if (document.querySelector(sel)) {
            hasCaptcha = true;
            break;
        }
    }

    return {
        url: window.location.href,
        title: document.title || '',
        visible_text: visibleText,
        element_count: elementCount,
        has_popup: hasPopup,
        has_captcha: hasCaptcha,
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

    async def extract_inputs(self, page: Page) -> list[ExtractedElement]:
        """Extract form inputs, textareas, and selects from the page.

        Args:
            page: Playwright Page instance.

        Returns:
            List of ExtractedElement for each input-like element found.
        """
        raw: list[dict] = await page.evaluate(_JS_EXTRACT_INPUTS)
        return [self._to_element(item) for item in raw]

    async def extract_clickables(self, page: Page) -> list[ExtractedElement]:
        """Extract buttons, links, tabs, and other clickable elements.

        Args:
            page: Playwright Page instance.

        Returns:
            List of ExtractedElement for each clickable element found.
        """
        raw: list[dict] = await page.evaluate(_JS_EXTRACT_CLICKABLES)
        return [self._to_element(item) for item in raw]

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
