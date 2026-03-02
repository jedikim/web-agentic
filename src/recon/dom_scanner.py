"""DOM Scanner — Stage 1 of site reconnaissance.

Collects all DOM-based information without any LLM/VLM calls.
Uses CDP DOMSnapshot + AXTree as primary, page.evaluate() as auxiliary.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class BrowserLike(Protocol):
    """Minimal browser interface for DOM scanning."""

    async def evaluate(self, expression: str) -> Any: ...
    async def cdp_send(self, method: str, params: dict[str, Any]) -> Any: ...


class DOMScanner:
    """Extract all DOM-based information from a page.

    Stage 1 of 3-stage recon. No LLM calls. Cost: $0, ~3s.
    """

    async def scan(self, browser: BrowserLike) -> dict[str, Any]:
        """Run all DOM scans in parallel.

        Returns:
            Merged dict of all scan results.
        """
        results = await asyncio.gather(
            self._scan_snapshot(browser),
            self._scan_structure(browser),
            self._scan_navigation(browser),
            self._scan_content(browser),
            self._scan_obstacles(browser),
            self._scan_forms(browser),
            self._scan_interactions(browser),
            return_exceptions=True,
        )
        merged: dict[str, Any] = {}
        for r in results:
            if isinstance(r, Exception):
                logger.warning("DOM scan partial failure: %s", r)
                continue
            if isinstance(r, dict):
                merged.update(r)
        return merged

    async def _scan_snapshot(self, browser: BrowserLike) -> dict[str, Any]:
        """CDP DOMSnapshot + AXTree for stable structure collection."""
        try:
            dom_snapshot = await browser.cdp_send(
                "DOMSnapshot.captureSnapshot",
                {
                    "computedStyles": ["display", "visibility", "pointer-events"],
                    "includeDOMRects": True,
                    "includePaintOrder": False,
                },
            )
            ax_tree = await browser.cdp_send(
                "Accessibility.getFullAXTree", {}
            )
        except Exception:
            logger.warning("CDP snapshot unavailable, falling back to evaluate")
            return {}

        node_count = sum(
            len(doc.get("nodes", {}).get("nodeName", []))
            for doc in dom_snapshot.get("documents", [])
        )
        layout_count = sum(
            len(doc.get("layout", {}).get("nodeIndex", []))
            for doc in dom_snapshot.get("documents", [])
        )
        interactive_roles = {
            "button", "link", "textbox", "combobox",
            "menuitem", "checkbox", "radio",
        }
        ax_interactive = sum(
            1
            for node in ax_tree.get("nodes", [])
            if str(node.get("role", {}).get("value", "")).lower()
            in interactive_roles
        )

        return {
            "snapshot_node_count": node_count,
            "snapshot_layout_count": layout_count,
            "ax_node_count": len(ax_tree.get("nodes", [])),
            "ax_interactive_count": ax_interactive,
        }

    async def _scan_structure(self, browser: BrowserLike) -> dict[str, Any]:
        """Structure analysis — framework, complexity, Shadow DOM."""
        return await browser.evaluate(
            """(() => {
            const all = document.querySelectorAll('*');
            const interactive = document.querySelectorAll(
                'a, button, input, select, textarea, [role="button"], [onclick], [tabindex]'
            );
            let framework = null;
            if (window.__REACT_DEVTOOLS_GLOBAL_HOOK__) framework = 'react';
            else if (window.__VUE__) framework = 'vue';
            else if (window.ng) framework = 'angular';
            else if (window.jQuery) framework = 'jquery';
            function maxDepth(el, depth) {
                if (!el.children.length) return depth;
                return Math.max(...[...el.children].map(c => maxDepth(c, depth + 1)));
            }
            const hasShadow = [...all].some(el => el.shadowRoot);
            const withId = [...all].filter(el => el.id).length;
            const withClass = [...all].filter(el => el.className).length;
            const withAria = [...interactive].filter(el =>
                el.getAttribute('aria-label') || el.getAttribute('role')
            ).length;
            return {
                total_elements: all.length,
                interactive_elements: interactive.length,
                max_depth: maxDepth(document.body, 0),
                framework,
                has_shadow_dom: hasShadow,
                iframe_count: document.querySelectorAll('iframe').length,
                unique_selectors_ratio: (withId + withClass) / Math.max(all.length, 1),
                text_node_ratio: document.body.innerText.length /
                    Math.max(document.body.innerHTML.length, 1),
                aria_coverage: withAria / Math.max(interactive.length, 1),
                is_spa: !!document.querySelector('[id="app"], [id="root"], [id="__next"]'),
            };
        })()"""
        )

    async def _scan_navigation(self, browser: BrowserLike) -> dict[str, Any]:
        """Menu, search, breadcrumb structure."""
        return await browser.evaluate(
            """(() => {
            const nav = document.querySelector(
                'nav, [role="navigation"], header ul, .gnb, .main-menu, ' +
                '#gnb, #gnbMenu, [class*="gnb"], [class*="main-nav"], ' +
                '[class*="global-nav"], [class*="top-menu"], [class*="nav-menu"], ' +
                '[class*="cate_menu"], [class*="lnb"]');
            const menuItems = nav ? [...nav.querySelectorAll('a')].map(a => ({
                text: a.textContent.trim().slice(0, 50),
                href: a.href,
                hasChildren: a.parentElement.querySelector('ul, .sub-menu, .dropdown') !== null,
            })) : [];
            const searchInput = document.querySelector(
                'input[type="search"], input[name="query"], input[name="q"], ' +
                'input[placeholder*="검색"], input[placeholder*="search"], [role="searchbox"]'
            );
            const searchConfig = searchInput ? {
                input_selector: searchInput.id ? '#' + searchInput.id : null,
                has_autocomplete: !!document.querySelector(
                    '[role="listbox"], .autocomplete, .suggest'),
                submit_button: !!document.querySelector(
                    'button[type="submit"], .search-btn, .btn-search'),
            } : null;
            const hamburger = document.querySelector('.hamburger, .menu-toggle, [class*="burger"]');
            const megaMenu = document.querySelector('.mega-menu, [class*="mega"]');
            const menuType = hamburger ? 'hamburger'
                : megaMenu ? 'mega_menu'
                : nav ? 'horizontal_nav' : 'unknown';
            const breadcrumb = document.querySelector(
                '[class*="breadcrumb"], [aria-label="breadcrumb"], .path'
            );
            return {
                menu_type: menuType,
                menu_items: menuItems.slice(0, 30),
                menu_requires_hover: menuType === 'mega_menu' || menuType === 'horizontal_nav',
                search: searchConfig,
                has_breadcrumb: !!breadcrumb,
            };
        })()"""
        )

    async def _scan_content(self, browser: BrowserLike) -> dict[str, Any]:
        """Whitelist-based content pattern recognition."""
        return await browser.evaluate(
            r"""(() => {
            function getTagHash(el) {
                const tags = [...el.children].map(c => c.tagName).join('>');
                let h = 0;
                for (let i = 0; i < tags.length; i++) {
                    h = ((h << 5) - h + tags.charCodeAt(i)) | 0;
                }
                return h.toString(36);
            }
            const repeatingPatterns = [];
            const containers = [...document.querySelectorAll('*')]
                .filter(el => el.children.length >= 3 && el.children.length <= 200);
            for (const parent of containers.slice(0, 100)) {
                const children = [...parent.children];
                const hashGroups = {};
                children.forEach(child => {
                    const hash = getTagHash(child);
                    if (!hashGroups[hash]) hashGroups[hash] = [];
                    hashGroups[hash].push(child);
                });
                for (const [hash, group] of Object.entries(hashGroups)) {
                    if (group.length < 3) continue;
                    const sample = group[0];
                    const hasText = sample.innerText?.trim().length > 10;
                    const hasLink = !!sample.querySelector('a[href]');
                    const hasImage = !!sample.querySelector('img');
                    const isContent = hasText && (hasLink || hasImage);
                    if (isContent) {
                        const parentSel = parent.id ? '#' + parent.id
                            : parent.className ? '.' + parent.className.trim().split(/\s+/)[0]
                            : parent.tagName.toLowerCase();
                        const itemSel = sample.className
                            ? '.' + sample.className.trim().split(/\s+/)[0]
                            : sample.tagName.toLowerCase();
                        repeatingPatterns.push({
                            parent_selector: parentSel,
                            item_tag_hash: hash,
                            item_count: group.length,
                            has_text: hasText,
                            has_link: hasLink,
                            has_image: hasImage,
                            is_content: true,
                            sample_item_selector: itemSel,
                        });
                    }
                }
            }
            const images = document.querySelectorAll('img');
            const totalArea = window.innerWidth * window.innerHeight;
            let imgArea = 0;
            images.forEach(img => {
                const rect = img.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) imgArea += rect.width * rect.height;
            });
            const imageDensity = imgArea / totalArea;
            const canvases = document.querySelectorAll('canvas');
            let canvasArea = 0;
            canvases.forEach(c => {
                const rect = c.getBoundingClientRect();
                canvasArea += rect.width * rect.height;
            });
            return {
                repeating_patterns: repeatingPatterns,
                image_density: imageDensity < 0.2 ? 'low' : imageDensity < 0.5 ? 'medium' : 'high',
                canvas_count: canvases.length,
                canvas_area_ratio: canvasArea / totalArea,
                total_images: images.length,
            };
        })()"""
        )

    async def _scan_obstacles(self, browser: BrowserLike) -> dict[str, Any]:
        """Detect interaction-blocking obstacles only (not ads)."""
        return await browser.evaluate(
            """(() => {
            const obstacles = [];
            const modals = document.querySelectorAll(
                '[class*="popup"], [class*="modal"], [class*="overlay"], [class*="dialog"],' +
                '[role="dialog"], [role="alertdialog"]'
            );
            modals.forEach(m => {
                const style = getComputedStyle(m);
                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    const closeBtn = m.querySelector(
                        '[class*="close"], [aria-label="close"], .btn-close, button:has(svg)'
                    );
                    obstacles.push({
                        type: m.className.includes('cookie') ? 'cookie_consent' : 'popup',
                        selector: m.id ? '#' + m.id : null,
                        close_selector: closeBtn ? (closeBtn.id ? '#' + closeBtn.id : null) : null,
                        visible: true,
                    });
                }
            });
            return { obstacles };
        })()"""
        )

    async def _scan_forms(self, browser: BrowserLike) -> dict[str, Any]:
        """Form structure analysis — both <form> elements and filter input groups."""
        return await browser.evaluate(
            """(() => {
            const forms = [...document.querySelectorAll('form')].slice(0, 10).map(f => ({
                action: f.action,
                method: f.method,
                selector: f.id ? '#' + f.id : null,
                fields: [...f.querySelectorAll('input, select, textarea')].map(e => ({
                    name: e.name,
                    type: e.type,
                    selector: e.id ? '#' + e.id : null,
                    required: e.required,
                    placeholder: e.placeholder || null,
                })),
                submit: f.querySelector('button[type="submit"], input[type="submit"]') ? {
                    text: f.querySelector('button[type="submit"]')?.textContent?.trim() || null,
                } : null,
            }));

            // Filter input groups: input + nearby button outside <form>
            const filterGroups = [];
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                if (btn.closest('form')) continue;
                if (btn.offsetWidth === 0 || btn.offsetHeight === 0) continue;
                const container = btn.parentElement;
                if (!container) continue;
                // Walk up max 3 levels to find inputs near this button
                let scope = container;
                for (let i = 0; i < 3 && scope; i++) {
                    const inputs = scope.querySelectorAll(
                        'input:not([type="hidden"]):not([type="checkbox"])' +
                        ':not([type="radio"]):not([type="submit"]):not([type="button"])');
                    if (inputs.length > 0 && inputs.length <= 4) {
                        const fields = [...inputs].filter(
                            inp => inp.offsetWidth > 0 && inp.offsetHeight > 0
                        ).map(inp => ({
                            name: inp.name || null,
                            type: inp.type,
                            selector: inp.id ? '#' + inp.id : null,
                            required: inp.required,
                            placeholder: inp.placeholder || null,
                            label: (inp.id && document.querySelector('label[for="' + inp.id + '"]')
                                    ?.textContent?.trim()?.slice(0, 50))
                                || inp.closest('.input-basic, .input-group, [class*="input"]')
                                    ?.querySelector('label')?.textContent?.trim()?.slice(0, 50)
                                || null,
                        }));
                        if (fields.length > 0) {
                            filterGroups.push({
                                action: null,
                                method: 'filter',
                                selector: scope.id ? '#' + scope.id
                                    : scope.className
                                        ? '.' + scope.className.trim().split(/\\s+/)[0]
                                        : null,
                                fields,
                                submit: {
                                    text: btn.textContent?.trim()?.slice(0, 20) || null,
                                    selector: btn.id ? '#' + btn.id : null,
                                },
                            });
                            break;
                        }
                    }
                    scope = scope.parentElement;
                }
            }

            return { forms, filter_groups: filterGroups.slice(0, 10) };
        })()"""
        )

    async def _scan_interactions(self, browser: BrowserLike) -> dict[str, Any]:
        """Interaction patterns — hover, drag, dynamic loading."""
        return await browser.evaluate(
            """(() => {
            const patterns = [];
            const hoverMenus = document.querySelectorAll(
                '[class*="dropdown"], [class*="flyout"], [class*="depth2"], ' +
                '[class*="sub-menu"], [class*="submenu"], [class*="mega"]');
            if (hoverMenus.length > 0)
                patterns.push({type: 'hover_menu', count: hoverMenus.length});
            const carousels = document.querySelectorAll(
                '[class*="carousel"], [class*="slider"], [class*="swiper"]'
            );
            if (carousels.length > 0) patterns.push({type: 'carousel', count: carousels.length});
            const tabs = document.querySelectorAll('[role="tab"], [class*="tab-"]');
            if (tabs.length > 0) patterns.push({type: 'tab_switch', count: tabs.length});
            const accordions = document.querySelectorAll(
                '[class*="accordion"], [class*="collapse"], details'
            );
            if (accordions.length > 0) patterns.push({type: 'accordion', count: accordions.length});
            const ranges = document.querySelectorAll(
                'input[type="range"], [class*="range-slider"]');
            if (ranges.length > 0) patterns.push({type: 'drag_slider', count: ranges.length});
            const lazyImages = document.querySelectorAll('img[loading="lazy"], img[data-src]');
            if (lazyImages.length > 5)
                patterns.push({type: 'lazy_image', count: lazyImages.length});
            return { interaction_patterns: patterns };
        })()"""
        )
