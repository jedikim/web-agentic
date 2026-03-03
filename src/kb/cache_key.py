"""CacheKey — KB lookup key (domain + URL pattern + artifact type)."""

from __future__ import annotations

from dataclasses import dataclass


def normalize_domain(domain: str) -> str:
    """Strip ``www.`` prefix so www.a.com and a.com share one KB entry."""
    d = domain.lower().strip()
    if d.startswith("www."):
        d = d[4:]
    return d


@dataclass(frozen=True)
class CacheKey:
    """Knowledge Base lookup key.

    domain + url_pattern + artifact_type uniquely identifies an artifact.
    """

    domain: str  # "shopping.naver.com"
    url_pattern: str  # "/search?query=*" | "/catalog/*" | "/"
    artifact_type: str  # "profile" | "workflow" | "macro" | "prompt"

    @property
    def pattern_dir(self) -> str:
        """Convert URL pattern to directory name.

        /search?query=* → "search"
        /catalog/* → "catalog"
        / → "root"
        """
        clean = self.url_pattern.strip("/").split("?")[0].split("/")[0]
        return clean or "root"

    @property
    def site_dir(self) -> str:
        """Domain-level directory name."""
        return self.domain

    def __str__(self) -> str:
        return f"{self.domain}/{self.pattern_dir}/{self.artifact_type}"
