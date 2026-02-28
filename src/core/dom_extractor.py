"""CDP-based DOM Extractor — parallel DOM tree + Accessibility tree extraction.

Extracts interactive DOM nodes using Chrome DevTools Protocol:
- DOM.getDocument(depth=-1, pierce=True) for full DOM including Shadow DOM
- Accessibility.getFullAXTree() for ARIA roles and names

Returns a flat list of DOMNode objects ready for TextMatcher filtering.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.browser import Browser
from src.core.types import DOMNode

# Tags that indicate interactive elements
_INTERACTIVE_TAGS = frozenset({
    "a", "button", "input", "select", "textarea", "option",
    "details", "summary", "label",
})

# Attributes indicating interactivity
_INTERACTIVE_ATTRS = frozenset({
    "onclick", "onmousedown", "onmouseup", "ontouchstart",
    "role", "tabindex", "href", "contenteditable",
})

# ARIA roles that indicate interactivity
_INTERACTIVE_ROLES = frozenset({
    "button", "link", "menuitem", "menuitemcheckbox", "menuitemradio",
    "option", "radio", "switch", "tab", "checkbox", "combobox",
    "searchbox", "textbox", "spinbutton", "slider",
    "treeitem", "gridcell", "row",
})


class DOMExtractor:
    """Extract interactive DOM nodes via CDP.

    Usage:
        extractor = DOMExtractor()
        nodes = await extractor.extract(browser)
    """

    async def extract(self, browser: Browser) -> list[DOMNode]:
        """Extract all interactive DOM nodes from the page.

        Runs DOM.getDocument and Accessibility.getFullAXTree in parallel,
        then merges results into a flat list of DOMNode objects.
        """
        cdp = await browser.get_cdp()

        # Parallel extraction: DOM tree + Accessibility tree
        dom_result, ax_result = await asyncio.gather(
            cdp.send("DOM.getDocument", {"depth": -1, "pierce": True}),
            cdp.send("Accessibility.getFullAXTree"),
        )

        # Build AX lookup: node_id -> (role, name)
        ax_map = self._build_ax_map(ax_result)

        # Flatten DOM tree into interactive nodes
        root = dom_result.get("root", {})
        nodes: list[DOMNode] = []
        self._walk_dom(root, ax_map, nodes)

        return nodes

    def _build_ax_map(
        self, ax_result: dict[str, Any],
    ) -> dict[int, tuple[str, str]]:
        """Build a mapping from backend node ID to (role, name) from AX tree."""
        ax_map: dict[int, tuple[str, str]] = {}
        ax_nodes = ax_result.get("nodes", [])
        for ax_node in ax_nodes:
            backend_id = ax_node.get("backendDOMNodeId")
            if backend_id is None:
                continue

            role_obj = ax_node.get("role", {})
            role = role_obj.get("value", "") if isinstance(role_obj, dict) else ""

            name_obj = ax_node.get("name", {})
            name = name_obj.get("value", "") if isinstance(name_obj, dict) else ""

            if role or name:
                ax_map[backend_id] = (role, name)

        return ax_map

    def _walk_dom(
        self,
        node: dict[str, Any],
        ax_map: dict[int, tuple[str, str]],
        result: list[DOMNode],
    ) -> None:
        """Recursively walk the DOM tree, collecting interactive nodes."""
        node_type = node.get("nodeType", 0)

        # Only process Element nodes (nodeType=1)
        if node_type == 1:
            tag = (node.get("nodeName") or "").lower()
            node_id = node.get("backendNodeId", node.get("nodeId", 0))
            attrs_raw = node.get("attributes", [])

            # Parse attributes from flat [name, value, name, value, ...] list
            attrs: dict[str, str] = {}
            for i in range(0, len(attrs_raw) - 1, 2):
                attrs[str(attrs_raw[i])] = str(attrs_raw[i + 1])

            # Determine if this node is interactive
            is_interactive = self._is_interactive(tag, attrs)

            if is_interactive:
                # Collect text content from child text nodes
                text = self._collect_text(node)

                # Get AX info
                ax_role: str | None = None
                ax_name: str | None = None
                if node_id in ax_map:
                    ax_role, ax_name = ax_map[node_id]

                result.append(DOMNode(
                    node_id=node_id,
                    tag=tag,
                    text=text.strip()[:500],  # Truncate long text
                    attrs=attrs,
                    ax_role=ax_role or None,
                    ax_name=ax_name or None,
                ))

        # Recurse into children
        children = node.get("children", [])
        for child in children:
            self._walk_dom(child, ax_map, result)

        # Also recurse into shadow DOM and content documents
        shadow_roots = node.get("shadowRoots", [])
        for shadow in shadow_roots:
            self._walk_dom(shadow, ax_map, result)

        content_doc = node.get("contentDocument")
        if content_doc:
            self._walk_dom(content_doc, ax_map, result)

    def _is_interactive(self, tag: str, attrs: dict[str, str]) -> bool:
        """Determine if an element is interactive."""
        # Direct interactive tags
        if tag in _INTERACTIVE_TAGS:
            return True

        # Has interactive attributes
        if any(attr in _INTERACTIVE_ATTRS for attr in attrs):
            return True

        # Has interactive ARIA role
        role = attrs.get("role", "")
        return role in _INTERACTIVE_ROLES

    def _collect_text(self, node: dict[str, Any]) -> str:
        """Collect visible text from a node and its direct children."""
        parts: list[str] = []

        # Check for nodeValue on text nodes
        if node.get("nodeType") == 3:  # Text node
            val = node.get("nodeValue", "")
            if val.strip():
                parts.append(val.strip())

        # Collect from children
        for child in node.get("children", []):
            child_type = child.get("nodeType", 0)
            if child_type == 3:  # Text node
                val = child.get("nodeValue", "")
                if val.strip():
                    parts.append(val.strip())
            elif child_type == 1:  # Element — only go 1 level deep
                for grandchild in child.get("children", []):
                    if grandchild.get("nodeType") == 3:
                        val = grandchild.get("nodeValue", "")
                        if val.strip():
                            parts.append(val.strip())

        return " ".join(parts)
