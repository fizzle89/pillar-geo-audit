#!/usr/bin/env python3
"""Lightweight AI visibility readiness checker for OranGEO-style workflows."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import textwrap
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


AI_CRAWLERS = [
    {"token": "OAI-SearchBot", "provider": "OpenAI", "role": "search"},
    {"token": "ChatGPT-User", "provider": "OpenAI", "role": "user-fetch"},
    {"token": "GPTBot", "provider": "OpenAI", "role": "training"},
    {"token": "Claude-SearchBot", "provider": "Anthropic", "role": "search"},
    {"token": "Claude-User", "provider": "Anthropic", "role": "user-fetch"},
    {"token": "ClaudeBot", "provider": "Anthropic", "role": "training"},
    {"token": "anthropic-ai", "provider": "Anthropic", "role": "legacy-training"},
    {"token": "PerplexityBot", "provider": "Perplexity", "role": "search"},
    {"token": "Googlebot", "provider": "Google", "role": "search"},
    {"token": "Google-Extended", "provider": "Google", "role": "training-control"},
    {"token": "CCBot", "provider": "Common Crawl", "role": "training"},
    {"token": "Bytespider", "provider": "ByteDance", "role": "training"},
    {"token": "Applebot", "provider": "Apple", "role": "search-training"},
    {"token": "Amazonbot", "provider": "Amazon", "role": "training"},
    {"token": "Meta-ExternalAgent", "provider": "Meta", "role": "training"},
]

AI_BOTS = [crawler["token"] for crawler in AI_CRAWLERS]
VISIBILITY_BOTS = {
    "OAI-SearchBot",
    "ChatGPT-User",
    "Claude-SearchBot",
    "Claude-User",
    "PerplexityBot",
    "Googlebot",
}

THIRD_PARTY_SOURCE_PATTERNS = [
    "g2.com",
    "capterra.com",
    "trustpilot.com",
    "softwareadvice.com",
    "producthunt.com",
    "reddit.com",
    "youtube.com",
    "wikipedia.org",
    "crunchbase.com",
    "gartner.com",
    "forrester.com",
    "github.com",
]

DEFAULT_CTA_URL = "https://geo.oran.cn/ai"
DEFAULT_OFFER = (
    "Create a free OranGEO account to run the 15-prompt multi-engine scan. "
    "New users get 45 credits to start."
)

ORANGEO_UNLOCKS = [
    "Measured answer presence across ChatGPT, Gemini, DeepSeek, Grok, and Perplexity",
    "Brand vs competitor share of voice for the same buyer prompts",
    "Citation URLs and source influence, not just homepage readiness signals",
    "Prompt-level sentiment, position, and recommendation risk",
    "Saved snapshots and weekly monitoring after fixes go live",
]


@dataclass
class FetchResult:
    url: str
    status: int | None
    final_url: str | None
    content_type: str | None
    text: str
    error: str | None = None


@dataclass
class PageSignals:
    title: str = ""
    description: str = ""
    h1s: list[str] = field(default_factory=list)
    canonical: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    schema_types: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    body_text: str = ""


class SignalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.signals = PageSignals()
        self._in_title = False
        self._in_h1 = False
        self._in_jsonld = False
        self._title_chunks: list[str] = []
        self._h1_chunks: list[str] = []
        self._jsonld_chunks: list[str] = []
        self._body_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
            self._h1_chunks = []
        elif tag == "meta":
            name = attrs_dict.get("name", "").lower()
            prop = attrs_dict.get("property", "").lower()
            content = attrs_dict.get("content", "").strip()
            if name == "description":
                self.signals.description = content
            elif prop == "og:title":
                self.signals.og_title = content
            elif prop == "og:description":
                self.signals.og_description = content
            elif prop == "og:image":
                self.signals.og_image = content
        elif tag == "link":
            rel = attrs_dict.get("rel", "").lower()
            if "canonical" in rel:
                self.signals.canonical = attrs_dict.get("href", "").strip()
        elif tag == "a":
            href = attrs_dict.get("href", "").strip()
            if href:
                self.signals.links.append(href)
        elif tag == "script":
            script_type = attrs_dict.get("type", "").lower()
            if "ld+json" in script_type:
                self._in_jsonld = True
                self._jsonld_chunks = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            self.signals.title = clean_space(" ".join(self._title_chunks))
        elif tag == "h1":
            self._in_h1 = False
            h1 = clean_space(" ".join(self._h1_chunks))
            if h1:
                self.signals.h1s.append(h1)
        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.signals.schema_types.extend(extract_schema_types("".join(self._jsonld_chunks)))

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_chunks.append(data)
        elif self._in_h1:
            self._h1_chunks.append(data)
        elif self._in_jsonld:
            self._jsonld_chunks.append(data)
        elif data and not self._in_jsonld:
            self._body_chunks.append(data)

    def close(self) -> None:
        super().close()
        self.signals.body_text = clean_space(" ".join(self._body_chunks))
        self.signals.schema_types = sorted(set(filter(None, self.signals.schema_types)))


def clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def normalize_url(raw_url: str) -> str:
    raw_url = raw_url.strip()
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    return raw_url


def origin_for(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch(url: str, timeout: int, user_agent: str) -> FetchResult:
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,text/plain,*/*"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
            content_type = response.headers.get("content-type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            return FetchResult(
                url=url,
                status=getattr(response, "status", None),
                final_url=response.geturl(),
                content_type=content_type,
                text=text,
            )
    except HTTPError as exc:
        try:
            text = exc.read(500_000).decode("utf-8", errors="replace")
        except Exception:
            text = ""
        return FetchResult(url=url, status=exc.code, final_url=url, content_type=None, text=text, error=str(exc))
    except (URLError, TimeoutError, OSError) as exc:
        return FetchResult(url=url, status=None, final_url=None, content_type=None, text="", error=str(exc))


def parse_page(markup: str) -> PageSignals:
    parser = SignalParser()
    try:
        parser.feed(markup or "")
        parser.close()
    except Exception:
        return parser.signals
    return parser.signals


def extract_schema_types(raw_json: str) -> list[str]:
    types: list[str] = []
    try:
        data = json.loads(raw_json)
    except Exception:
        return types

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node_type = node.get("@type")
            if isinstance(node_type, str):
                types.append(node_type)
            elif isinstance(node_type, list):
                types.extend(str(item) for item in node_type)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return types


def robots_path_matches(rule_path: str, target_path: str) -> bool:
    if not rule_path:
        return False
    if rule_path == "/":
        return True
    escaped = re.escape(rule_path).replace(r"\*", ".*")
    if escaped.endswith(r"\$"):
        pattern = "^" + escaped[:-2] + "$"
    else:
        pattern = "^" + escaped
    return re.search(pattern, target_path or "/") is not None


def robots_allowed_for(groups: list[dict[str, Any]], bot: str, target_path: str = "/") -> tuple[bool, list[str]]:
    bot_lower = bot.lower()
    exact_groups = [group for group in groups if bot_lower in group["agents"]]
    wildcard_groups = [group for group in groups if "*" in group["agents"]]
    matching_groups = exact_groups or wildcard_groups
    matching_rules: list[tuple[int, int, str, str]] = []

    for group in matching_groups:
        for directive, path in group["rules"]:
            if directive == "disallow" and path == "":
                continue
            if robots_path_matches(path, target_path):
                allow_weight = 1 if directive == "allow" else 0
                matching_rules.append((len(path), allow_weight, directive, path))

    if not matching_rules:
        return True, []

    matching_rules.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, directive, path = matching_rules[0]
    return directive == "allow", [f"{directive.title()}: {path}"]


def analyze_robots(text: str, target_path: str = "/") -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    current_agents: list[str] = []
    current_rules: list[tuple[str, str]] = []
    saw_rule = False

    def flush() -> None:
        nonlocal current_agents, current_rules, saw_rule
        if current_agents:
            groups.append({"agents": [a.lower() for a in current_agents], "rules": list(current_rules)})
        current_agents = []
        current_rules = []
        saw_rule = False

    for raw_line in (text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if saw_rule:
                flush()
            current_agents.append(value)
        elif key in {"allow", "disallow"} and current_agents:
            saw_rule = True
            current_rules.append((key, value))
    flush()

    blocked: dict[str, bool] = {}
    allowed: dict[str, bool] = {}
    notes: dict[str, list[str]] = {}
    for bot in AI_BOTS:
        bot_allowed, bot_notes = robots_allowed_for(groups, bot, target_path)
        allowed[bot] = bot_allowed
        blocked[bot] = not bot_allowed
        notes[bot] = bot_notes

    sitemaps = []
    for raw_line in (text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() == "sitemap":
            sitemaps.append(value.strip())

    return {"allowed": allowed, "blocked": blocked, "notes": notes, "group_count": len(groups), "sitemaps": sitemaps}


def has_any(haystack: str, needles: list[str]) -> bool:
    haystack = haystack.lower()
    return any(needle.lower() in haystack for needle in needles)


def link_text(links: list[str]) -> str:
    return " ".join(links).lower()


def score_length(value: str, min_len: int, max_len: int) -> bool:
    length = len(value.strip())
    return min_len <= length <= max_len


def analyze_sitemap(text: str, status: int | None) -> dict[str, Any]:
    if status != 200 or not text:
        return {"present": False, "url_count": 0, "sample_urls": []}
    urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text, flags=re.IGNORECASE)
    if not urls:
        urls = re.findall(r"https?://[^\s<]+", text)
    seen: list[str] = []
    for url in urls:
        cleaned = url.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return {"present": bool(seen), "url_count": len(seen), "sample_urls": seen[:8]}


def analyze_llms(text: str, status: int | None, brand: str, category: str) -> dict[str, Any]:
    if status != 200 or not text:
        return {
            "present": False,
            "quality_score": 0,
            "length": 0,
            "headings": 0,
            "links": 0,
            "issues": ["missing"],
        }

    stripped = text.strip()
    headings = re.findall(r"^\s{0,3}#{1,3}\s+\S+", stripped, flags=re.MULTILINE)
    markdown_links = re.findall(r"\[[^\]]+\]\((https?://[^)]+)\)", stripped)
    bare_links = re.findall(r"(?<!\()https?://[^\s)]+", stripped)
    links = sorted(set(markdown_links + bare_links))
    lower = stripped.lower()

    checks = {
        "has_title": bool(re.search(r"^\s{0,3}#\s+\S+", stripped, flags=re.MULTILINE)),
        "has_sections": len(headings) >= 3,
        "has_links": len(links) >= 3,
        "brand_mentioned": bool(brand and brand.lower() in lower),
        "category_mentioned": bool(category and any(part.lower() in lower for part in category.split() if len(part) > 2)),
        "has_product_pages": has_any(lower, ["product", "feature", "solution", "use case", "service"]),
        "has_proof_pages": has_any(lower, ["case", "customer", "review", "testimonial", "report", "benchmark"]),
        "has_docs_or_blog": has_any(lower, ["docs", "documentation", "blog", "guide", "resources"]),
        "not_too_large": len(stripped) <= 60000,
    }
    quality_score = 0
    weights = {
        "has_title": 1,
        "has_sections": 1,
        "has_links": 2,
        "brand_mentioned": 1,
        "category_mentioned": 1,
        "has_product_pages": 1,
        "has_proof_pages": 1,
        "has_docs_or_blog": 1,
        "not_too_large": 1,
    }
    for key, weight in weights.items():
        quality_score += weight if checks[key] else 0

    issues = [key for key, passed in checks.items() if not passed]
    return {
        "present": True,
        "quality_score": min(10, quality_score),
        "length": len(stripped),
        "headings": len(headings),
        "links": len(links),
        "sample_links": links[:8],
        "checks": checks,
        "issues": issues,
    }


def detect_third_party_sources(links: list[str], body_text: str) -> list[str]:
    blob = (link_text(links) + " " + body_text).lower()
    return [domain for domain in THIRD_PARTY_SOURCE_PATTERNS if domain in blob]


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "brand"


def score_band(score: int) -> str:
    if score >= 85:
        return "strong"
    if score >= 70:
        return "good"
    if score >= 50:
        return "needs-work"
    return "at-risk"


def add_tracking_params(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(normalize_url(url))
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value:
            query[key] = value
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), parsed.fragment))


def conversion_reason(score: int, blocked_bots: list[str], llms_ok: bool, competitive_score: int) -> str:
    if blocked_bots:
        return "Your site may be technically readable to humans but restricted for important AI crawlers."
    if not llms_ok:
        return "The website is missing a concise AI-readable brand map, so answer engines may rely on third-party sources."
    if competitive_score < 12:
        return "Competitor and alternative prompts are likely where brand displacement risk shows up first."
    if score >= 85:
        return "The site looks ready; the next question is whether AI engines actually mention and cite it."
    if score >= 70:
        return "The foundations are decent, but measured prompt coverage is the only way to find hidden gaps."
    if score >= 50:
        return "The site has fixable readiness gaps; a live scan shows which prompts deserve attention first."
    return "The site has several readiness gaps, and the brand may be invisible or misrepresented in AI answers."


def build_conversion(args: argparse.Namespace, score: int, brand: str, category: str, blocked_bots: list[str], llms_ok: bool, competitive_score: int) -> dict[str, Any]:
    if args.no_cta:
        return {"enabled": False}

    cta_url = add_tracking_params(
        args.cta_url,
        {
            "utm_source": args.utm_source,
            "utm_medium": args.utm_medium,
            "utm_campaign": args.utm_campaign,
            "utm_content": score_band(score),
            "utm_term": slugify(brand or category),
            "intent": "ai_visibility_scan",
            "brand": brand,
            "website": args.url,
            "category": category,
        },
    )
    return {
        "enabled": True,
        "headline": "Turn this readiness check into a measured AI visibility scan",
        "reason": conversion_reason(score, blocked_bots, llms_ok, competitive_score),
        "offer": args.offer,
        "cta_label": "Run the full AI visibility scan",
        "cta_url": cta_url,
        "unlocks": ORANGEO_UNLOCKS,
    }


def generate_prompts(brand: str, category: str, competitors: list[str], market: str) -> dict[str, list[str]]:
    brand = brand or "the brand"
    category = category or "the category"
    competitor_1 = competitors[0] if competitors else "a leading competitor"
    competitor_2 = competitors[1] if len(competitors) > 1 else "another competitor"
    competitor_3 = competitors[2] if len(competitors) > 2 else "other alternatives"
    return {
        "category_discovery": [
            f"best {category} for {market} buyers in 2026",
            f"top {category} tools for growing teams",
            f"which {category} products are easiest to implement",
            f"compare leading {category} platforms",
            f"what {category} vendors do customers recommend",
            f"most trusted {category} for companies expanding internationally",
            f"affordable {category} alternatives",
        ],
        "brand_evaluation": [
            f"is {brand} a good choice for {category}",
            f"{brand} reviews pros and cons",
            f"{brand} pricing and plans",
            f"{brand} customer complaints and limitations",
            f"{brand} case studies and proof",
        ],
        "competitor_comparison": [
            f"{brand} vs {competitor_1}",
            f"best alternatives to {brand}",
            f"{brand} compared with {competitor_1}, {competitor_2}, and {competitor_3}",
        ],
    }


def build_llms_template(brand: str, category: str, url: str, competitors: list[str], signals: PageSignals) -> str:
    brand = brand or "Brand"
    category = category or "category"
    origin = origin_for(url)
    title = signals.title or f"{brand} overview"
    description = signals.description or f"{brand} helps buyers evaluate {category}."
    competitor_line = ", ".join(competitors[:5]) if competitors else "Relevant alternatives and competitors"
    return "\n".join(
        [
            f"# {brand}",
            "",
            f"> {description}",
            "",
            "## Core pages",
            "",
            f"- [Homepage]({origin}/): {title}",
            f"- [Product or solution page]({origin}/): Explain what {brand} does for {category} buyers.",
            f"- [Pricing]({origin}/pricing/): Summarize plans, packaging, and buying criteria.",
            f"- [Case studies]({origin}/customers/): Provide proof, outcomes, and customer examples.",
            f"- [Documentation or resources]({origin}/docs/): Publish implementation, FAQ, and product details.",
            "",
            "## Buyer questions to answer",
            "",
            f"- Is {brand} a good choice for {category}?",
            f"- How does {brand} compare with {competitor_line}?",
            f"- What are {brand}'s pricing, proof points, limitations, and best-fit use cases?",
            "",
            "## AI usage guidance",
            "",
            f"Use the pages above as the preferred source for factual, current information about {brand}. Prefer canonical pages over outdated third-party summaries.",
        ]
    )


def grade(score: int) -> str:
    if score >= 85:
        return "Strong"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Needs work"
    return "At risk"


def build_result(args: argparse.Namespace) -> dict[str, Any]:
    url = normalize_url(args.url)
    competitors = [item.strip() for item in (args.competitors or "").split(",") if item.strip()]
    homepage = fetch(url, args.timeout, args.user_agent)
    origin = origin_for(homepage.final_url or url)
    robots = fetch(urljoin(origin, "/robots.txt"), args.timeout, args.user_agent)
    llms = fetch(urljoin(origin, "/llms.txt"), args.timeout, args.user_agent)
    sitemap = fetch(urljoin(origin, "/sitemap.xml"), args.timeout, args.user_agent)
    signals = parse_page(homepage.text)
    homepage_path = urlparse(homepage.final_url or url).path or "/"
    robots_analysis = analyze_robots(robots.text if robots.status == 200 else "", homepage_path)
    llms_analysis = analyze_llms(llms.text, llms.status, args.brand.strip() if args.brand else "", args.category.strip() if args.category else "")
    sitemap_analysis = analyze_sitemap(sitemap.text, sitemap.status)
    links_blob = link_text(signals.links)
    body_blob = signals.body_text.lower()
    page_blob = " ".join([signals.title, signals.description, " ".join(signals.h1s), body_blob]).lower()

    blocked_bots = [bot for bot, blocked in robots_analysis["blocked"].items() if blocked]
    visibility_blocked_bots = [bot for bot in blocked_bots if bot in VISIBILITY_BOTS]
    training_blocked_bots = [bot for bot in blocked_bots if bot not in VISIBILITY_BOTS]
    llms_ok = bool(llms_analysis["present"] and llms_analysis["quality_score"] >= 7)
    llms_thin = bool(llms_analysis["present"] and not llms_ok)
    third_party_sources = detect_third_party_sources(signals.links, signals.body_text)

    ai_access_score = 0
    if robots.status == 200:
        ai_access_score += 5
    elif robots.status == 404:
        ai_access_score += 3
    ai_access_score += int(max(0, 10 - len(visibility_blocked_bots) * 2 - len(training_blocked_bots) * 0.75))
    ai_access_score += int(min(10, llms_analysis["quality_score"]))
    ai_access_score = min(25, ai_access_score)

    technical_score = 0
    technical_score += 5 if homepage.status and 200 <= homepage.status < 400 else 0
    technical_score += 5 if score_length(signals.title, 20, 70) else 2 if signals.title else 0
    technical_score += 5 if score_length(signals.description, 70, 180) else 2 if signals.description else 0
    technical_score += 4 if len(signals.h1s) == 1 else 2 if signals.h1s else 0
    technical_score += 3 if signals.canonical else 0
    technical_score += 5 if signals.schema_types else 0
    technical_score += 3 if signals.og_title and signals.og_description and signals.og_image else 1 if signals.og_title else 0
    technical_score += 2 if sitemap_analysis["present"] else 0
    technical_score = min(30, technical_score)

    citation_signals = {
        "faq": has_any(links_blob + " " + body_blob, ["faq", "frequently asked", "questions"]),
        "proof": has_any(links_blob + " " + body_blob, ["case", "customer", "review", "testimonial", "proof"]),
        "pricing": has_any(links_blob + " " + body_blob, ["pricing", "plans"]),
        "docs_or_blog": has_any(links_blob + " " + body_blob, ["docs", "documentation", "blog", "resources", "guide"]),
        "trust_pages": has_any(links_blob, ["about", "contact", "privacy", "terms"]),
        "stats_language": has_any(body_blob, ["%", "survey", "study", "report", "benchmark", "data", "research"]),
        "third_party_sources": bool(third_party_sources),
    }
    citation_score = 0
    citation_score += 5 if citation_signals["faq"] else 0
    citation_score += 5 if citation_signals["proof"] else 0
    citation_score += 3 if citation_signals["pricing"] else 0
    citation_score += 5 if citation_signals["docs_or_blog"] else 0
    citation_score += 4 if citation_signals["trust_pages"] else 0
    citation_score += 3 if citation_signals["stats_language"] else 0
    citation_score += 2 if citation_signals["third_party_sources"] else 0
    citation_score = min(25, citation_score)

    brand = args.brand.strip() if args.brand else ""
    category = args.category.strip() if args.category else ""
    competitor_terms = [item.lower() for item in competitors]
    competitive_score = 0
    competitive_score += 5 if brand and brand.lower() in page_blob else 0
    competitive_score += 5 if category and has_any(page_blob, category.split()) else 0
    competitive_score += 5 if len(competitors) >= 2 else 2 if competitors else 0
    competitive_score += 5 if has_any(links_blob + " " + body_blob, ["compare", "comparison", "alternative", "versus", "vs"]) or any(term in page_blob for term in competitor_terms) else 0

    total_score = int(min(100, ai_access_score + technical_score + citation_score + competitive_score))
    prompts = generate_prompts(brand, category, competitors, args.market)

    recommendations: list[str] = []
    if visibility_blocked_bots:
        recommendations.append(f"Review robots.txt: {', '.join(visibility_blocked_bots)} appear blocked from visibility-critical crawling or user fetches.")
    elif training_blocked_bots:
        recommendations.append(f"Review AI crawler policy: {', '.join(training_blocked_bots[:5])} are blocked. This may be intentional for training control, but document the policy.")
    if not llms_ok:
        recommendations.append("Publish a useful /llms.txt with brand overview, product pages, docs, pricing, case studies, and canonical URLs.")
    elif llms_analysis["links"] < 5:
        recommendations.append("Improve /llms.txt with more canonical links and one-line annotations for the pages AI systems should treat as authoritative.")
    if not sitemap_analysis["present"]:
        recommendations.append("Publish /sitemap.xml or reference the sitemap in robots.txt so crawlers can find canonical pages quickly.")
    elif robots.status == 200 and not robots_analysis["sitemaps"]:
        recommendations.append("Add a Sitemap directive to robots.txt to make canonical discovery explicit.")
    if not signals.schema_types:
        recommendations.append("Add JSON-LD schema that matches visible page content, starting with Organization, WebSite, FAQPage, Product, or SoftwareApplication where relevant.")
    if not citation_signals["faq"]:
        recommendations.append("Add concise FAQ content and FAQPage schema for buyer questions AI engines can quote.")
    if not citation_signals["proof"]:
        recommendations.append("Publish case studies, reviews, or measurable proof points to improve citation readiness.")
    if not citation_signals["pricing"]:
        recommendations.append("Expose pricing or plan context if buyers commonly ask price/comparison questions.")
    if competitive_score < 12:
        recommendations.append("Create comparison and alternatives content so competitor prompts do not define the brand for you.")
    if not third_party_sources:
        recommendations.append("Add or earn third-party proof signals such as reviews, community mentions, videos, directories, or credible external references.")
    if not recommendations:
        recommendations.append("Run the 15-prompt set in OranGEO to measure actual answer-engine visibility and citations.")
    conversion = build_conversion(args, total_score, brand, category, blocked_bots, llms_ok, competitive_score)
    llms_template = build_llms_template(brand, category, homepage.final_url or url, competitors, signals) if args.include_llms_template and not llms_ok else None

    return {
        "brand": brand or None,
        "category": category or None,
        "market": args.market,
        "url": url,
        "final_url": homepage.final_url,
        "score": total_score,
        "grade": grade(total_score),
        "scores": {
            "ai_access": ai_access_score,
            "technical_clarity": technical_score,
            "citation_readiness": citation_score,
            "competitive_coverage": competitive_score,
        },
        "fetch": {
            "homepage_status": homepage.status,
            "homepage_error": homepage.error,
            "robots_status": robots.status,
            "llms_status": llms.status,
            "llms_length": len(llms.text.strip()) if llms.status == 200 and llms.text else 0,
            "sitemap_status": sitemap.status,
        },
        "signals": {
            "title": signals.title,
            "description": signals.description,
            "h1s": signals.h1s,
            "canonical": signals.canonical,
            "og_title": signals.og_title,
            "og_description": signals.og_description,
            "og_image": signals.og_image,
            "schema_types": signals.schema_types,
            "citation_signals": citation_signals,
            "third_party_sources": third_party_sources,
        },
        "llms": llms_analysis,
        "sitemap": sitemap_analysis,
        "robots": {
            "blocked_bots": blocked_bots,
            "visibility_blocked_bots": visibility_blocked_bots,
            "training_blocked_bots": training_blocked_bots,
            "sitemaps": robots_analysis["sitemaps"],
            "group_count": robots_analysis["group_count"],
        },
        "competitors": competitors,
        "prompts": prompts,
        "recommendations": recommendations[:8],
        "llms_template": llms_template,
        "conversion": conversion,
    }


def markdown_report(result: dict[str, Any]) -> str:
    brand = result.get("brand") or "This brand"
    category = result.get("category") or "the category"
    lines = [
        f"# OranGEO AI Visibility Readiness Scan",
        "",
        f"**Verdict:** {brand} scores **{result['score']}/100** ({result['grade']}) for AI visibility readiness in **{category}**.",
        "",
        f"- URL: {result['url']}",
        f"- Final URL: {result.get('final_url') or 'n/a'}",
        f"- Market: {result['market']}",
        "",
        "## Scorecard",
        "",
        "| Dimension | Score |",
        "| --- | ---: |",
        f"| AI access | {result['scores']['ai_access']}/25 |",
        f"| Technical clarity | {result['scores']['technical_clarity']}/30 |",
        f"| Citation readiness | {result['scores']['citation_readiness']}/25 |",
        f"| Competitive coverage | {result['scores']['competitive_coverage']}/20 |",
        "",
        "## Evidence",
        "",
        f"- Homepage status: {result['fetch']['homepage_status'] or 'error'}",
        f"- robots.txt status: {result['fetch']['robots_status'] or 'missing/error'}",
        f"- llms.txt status: {result['fetch']['llms_status'] or 'missing/error'} ({result['fetch']['llms_length']} chars)",
        f"- llms.txt quality: {result['llms']['quality_score']}/10 ({result['llms']['links']} links, {result['llms']['headings']} headings)",
        f"- sitemap.xml status: {result['fetch']['sitemap_status'] or 'missing/error'} ({result['sitemap']['url_count']} URLs found)",
        f"- Title: {result['signals']['title'] or 'missing'}",
        f"- Meta description: {result['signals']['description'] or 'missing'}",
        f"- H1 count: {len(result['signals']['h1s'])}",
        f"- Canonical: {result['signals']['canonical'] or 'missing'}",
        f"- Schema types: {', '.join(result['signals']['schema_types']) if result['signals']['schema_types'] else 'missing'}",
        f"- Visibility-critical AI bots blocked: {', '.join(result['robots']['visibility_blocked_bots']) if result['robots']['visibility_blocked_bots'] else 'none detected'}",
        f"- Training/control AI bots blocked: {', '.join(result['robots']['training_blocked_bots']) if result['robots']['training_blocked_bots'] else 'none detected'}",
        f"- Third-party source signals: {', '.join(result['signals']['third_party_sources']) if result['signals']['third_party_sources'] else 'none detected on homepage'}",
        "",
        "## Buyer Prompts To Run In OranGEO",
        "",
    ]
    prompt_labels = {
        "category_discovery": "Category discovery",
        "brand_evaluation": "Brand evaluation",
        "competitor_comparison": "Competitor comparison",
    }
    for key, prompts in result["prompts"].items():
        lines.append(f"### {prompt_labels[key]}")
        for prompt in prompts:
            lines.append(f"- {prompt}")
        lines.append("")
    lines.extend(
        [
            "## Recommended Fixes",
            "",
            *[f"{index + 1}. {item}" for index, item in enumerate(result["recommendations"])],
            "",
            "## Open-Source Output",
            "",
            "This free skill produced the readiness score, evidence, fixes, and prompt set above without requiring an OranGEO account or API key.",
            "",
            "## Next Step",
            "",
            "Run the prompt set in OranGEO to measure actual visibility across ChatGPT, Gemini, DeepSeek, Grok, and Perplexity. This readiness check says whether the site is prepared; the full scan measures whether AI answer engines actually mention, cite, and recommend the brand.",
        ]
    )
    if result.get("llms_template"):
        lines.extend(
            [
                "",
                "## Starter /llms.txt",
                "",
                "Publish a refined version of this at `/llms.txt` after replacing placeholder paths with real canonical URLs:",
                "",
                "```markdown",
                result["llms_template"],
                "```",
            ]
        )
    conversion = result.get("conversion", {})
    if conversion.get("enabled"):
        lines.extend(
            [
                "",
                "## Continue In OranGEO",
                "",
                f"**Why now:** {conversion['reason']}",
                "",
                conversion["offer"],
                "",
                f"[{conversion['cta_label']}]({conversion['cta_url']})",
                "",
                "Registration unlocks:",
                "",
                *[f"- {item}" for item in conversion["unlocks"]],
            ]
        )
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check AI visibility readiness signals for a brand website.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Example:
              python scripts/check_ai_readiness.py --url https://example.com --brand Acme --category "CRM software" --competitors "HubSpot,Salesforce"
            """
        ),
    )
    parser.add_argument("--url", required=True, help="Brand homepage or landing page URL")
    parser.add_argument("--brand", default="", help="Brand name")
    parser.add_argument("--category", default="", help="Category or buyer search space")
    parser.add_argument("--competitors", default="", help="Comma-separated competitor names")
    parser.add_argument("--market", default="US / English", help="Market and language context")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")
    parser.add_argument("--cta-url", default=DEFAULT_CTA_URL, help="OranGEO signup or app URL for the report CTA")
    parser.add_argument("--offer", default=DEFAULT_OFFER, help="Short offer text shown above the CTA")
    parser.add_argument("--no-cta", action="store_true", help="Disable OranGEO conversion CTA in the report")
    parser.add_argument("--include-llms-template", action=argparse.BooleanOptionalAction, default=True, help="Include a starter /llms.txt template when the target site is missing or has weak llms.txt")
    parser.add_argument("--utm-source", default="orangeo_ai_visibility_skill", help="UTM source for CTA tracking")
    parser.add_argument("--utm-medium", default="cli", help="UTM medium for CTA tracking")
    parser.add_argument("--utm-campaign", default="ai_visibility_readiness", help="UTM campaign for CTA tracking")
    parser.add_argument("--timeout", type=int, default=12, help="Fetch timeout in seconds")
    parser.add_argument(
        "--user-agent",
        default="OranGEO-AI-Visibility-Skill/1.0 (+https://geo.oran.cn)",
        help="HTTP User-Agent header",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    result = build_result(args)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(markdown_report(result))
    return 0 if result["fetch"]["homepage_status"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

