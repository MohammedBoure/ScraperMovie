from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 ArabCityScraper/1.0"
)

AKWAM_BASE_URL = os.environ.get("AKWAM_BASE_URL", "https://akwam.cyou").rstrip("/")
ALOOYTV_BASE_URL = os.environ.get("ALOOYTV_BASE_URL", "https://alooytv.co").rstrip("/")
REQUEST_TIMEOUT = float(os.environ.get("ARABCITY_TIMEOUT", "20"))
DEFAULT_AKWAM_BASE_URLS = ("https://ak.sv", "https://akwam.cyou", "https://akwem.com", "https://akwams.org")
QUALITY_WORDS = "WEB-DL|HDTV|BluRay|WebRip|BRRIP|DVDrip|DVDSCR|HD|HDTS|CAM|BDRIP|HDRIP|HC"


MANIFEST = {
    "id": "com.arabcity.addon",
    "version": "1.0.5",
    "name": "ArabCity",
    "description": "استمتع بمكتبة ضخمة من الأفلام والمسلسلات العربية",
    "resources": ["catalog", "meta", "stream"],
    "types": ["ArabCity-Akwam", "ArabCity-alooytv"],
    "idPrefixes": ["arabcity:"],
    "catalogs": [
        {"type": "ArabCity-Akwam", "id": "akoam-recent", "name": "🆕 أضيف حديثاً"},
        {"type": "ArabCity-Akwam", "id": "akoam-movies-all", "name": "🎬 كل الأفلام"},
        {"type": "ArabCity-Akwam", "id": "akoam-series-all", "name": "📺 كل المسلسلات"},
        {"type": "ArabCity-Akwam", "id": "akoam-movies-29", "name": "🎬 أفلام عربية"},
        {"type": "ArabCity-Akwam", "id": "akoam-series-29", "name": "📺 مسلسلات عربية"},
        {"type": "ArabCity-Akwam", "id": "akoam-movies-30", "name": "🎬 أفلام اجنبية"},
        {"type": "ArabCity-Akwam", "id": "akoam-series-30", "name": "📺 مسلسلات اجنبية"},
        {"type": "ArabCity-Akwam", "id": "akoam-movies-31", "name": "🎬 أفلام هندية"},
        {"type": "ArabCity-Akwam", "id": "akoam-series-31", "name": "📺 مسلسلات هندية"},
        {"type": "ArabCity-Akwam", "id": "akoam-movies-32", "name": "🎬 أفلام تركية"},
        {"type": "ArabCity-Akwam", "id": "akoam-series-32", "name": "📺 مسلسلات تركية"},
        {"type": "ArabCity-Akwam", "id": "akoam-movies-33", "name": "🎬 أفلام آسيوية"},
        {"type": "ArabCity-Akwam", "id": "akoam-series-33", "name": "📺 مسلسلات آسيوية"},
        {"type": "ArabCity-alooytv", "id": "alooytv-arabic", "name": "🎬 🇸🇦 عربية"},
        {"type": "ArabCity-alooytv", "id": "alooytv-turki", "name": "🎬 🇹🇷 تركية"},
        {"type": "ArabCity-alooytv", "id": "alooytv-ramadan-2025", "name": "🎬 🌙 رمضان 2025"},
        {"type": "ArabCity-alooytv", "id": "alooytv-ramadan-2026", "name": "🎬 🌙 رمضان 2026"},
    ],
}


@dataclass(frozen=True)
class CatalogRoute:
    provider: str
    name: str
    path: str
    kind: str = "mixed"
    filter_terms: tuple[str, ...] = ()


CATALOG_ROUTES: dict[str, CatalogRoute] = {
    "akoam-recent": CatalogRoute("akwam", "أضيف حديثاً", "/recent", "mixed"),
    "akoam-movies-all": CatalogRoute("akwam", "كل الأفلام", "/category/movies/", "movie"),
    "akoam-series-all": CatalogRoute("akwam", "كل المسلسلات", "/category/series/", "series"),
    "akoam-movies-29": CatalogRoute("akwam", "أفلام عربية", "/category/movies/", "movie", ("عربي", "عربية")),
    "akoam-series-29": CatalogRoute("akwam", "مسلسلات عربية", "/category/series/", "series", ("عربي", "عربية")),
    "akoam-movies-30": CatalogRoute("akwam", "أفلام اجنبية", "/category/movies/افلام-اجنبي/", "movie"),
    "akoam-series-30": CatalogRoute("akwam", "مسلسلات اجنبية", "/category/series/مسلسلات-اجنبي/", "series"),
    "akoam-movies-31": CatalogRoute("akwam", "أفلام هندية", "/category/movies/", "movie", ("هندي", "هندية")),
    "akoam-series-31": CatalogRoute("akwam", "مسلسلات هندية", "/category/series/", "series", ("هندي", "هندية")),
    "akoam-movies-32": CatalogRoute("akwam", "أفلام تركية", "/category/movies/", "movie", ("تركي", "تركية")),
    "akoam-series-32": CatalogRoute("akwam", "مسلسلات تركية", "/category/series/", "series", ("تركي", "تركية")),
    "akoam-movies-33": CatalogRoute("akwam", "أفلام آسيوية", "/category/movies/افلام-اسيوي/", "movie"),
    "akoam-series-33": CatalogRoute("akwam", "مسلسلات آسيوية", "/category/series/مسلسلات-اسيوية/", "series"),
    "alooytv-arabic": CatalogRoute("alooytv", "عربية", "/home/", "mixed", ("عربي", "عربية")),
    "alooytv-turki": CatalogRoute("alooytv", "تركية", "/home/", "mixed", ("تركي", "تركية")),
    "alooytv-ramadan-2025": CatalogRoute("alooytv", "رمضان 2025", "/home/", "series", ("رمضان", "2025")),
    "alooytv-ramadan-2026": CatalogRoute("alooytv", "رمضان 2026", "/home/", "series", ("رمضان", "2026")),
}


NOISE_TITLES = {
    "watch",
    "favorite",
    "",
    "مشاهدة",
    "شاهد الآن",
    "تحميل",
    "بحث",
    "قائمتي",
    "أضيف حديثا",
    "أضيف حديثاً",
    "افلام",
    "أفلام",
    "مسلسلات",
    "انمى",
    "انمي",
    "الكل",
    "المزيد",
    "دخول للموقع",
    "تصفح الموقع الآن",
}


@dataclass
class Link:
    href: str
    text: str = ""
    image: str = ""


@dataclass
class MediaItem:
    name: str
    kind: str
    url: str
    source: str
    image: str = ""
    episode_count: int | None = None
    discovered_episodes: set[int] = field(default_factory=set)
    raw_titles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "url": self.url,
            "source": self.source,
            "image": self.image,
            "episode_count": self.episode_count,
            "raw_titles": self.raw_titles[:5],
        }


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[Link] = []
        self._active: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "a" and attrs_map.get("href"):
            self.links.append(Link(href=attrs_map["href"]))
            self._active.append(len(self.links) - 1)
            title = attrs_map.get("title") or attrs_map.get("aria-label")
            if title:
                self.links[-1].text += " " + title
        elif tag.lower() == "img" and self._active:
            alt = attrs_map.get("alt") or attrs_map.get("title")
            if alt:
                self.links[self._active[-1]].text += " " + alt
            if attrs_map.get("src"):
                self.links[self._active[-1]].image = attrs_map["src"]

    def handle_data(self, data: str) -> None:
        if self._active and data.strip():
            self.links[self._active[-1]].text += " " + data

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._active:
            self._active.pop()


@dataclass
class Token:
    kind: str
    text: str
    href: str = ""
    image: str = ""


class TokenExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[Token] = []
        self._link_href: str | None = None
        self._link_text: list[str] = []
        self._link_image = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "a" and attrs_map.get("href"):
            self._link_href = attrs_map["href"]
            self._link_text = []
            self._link_image = ""
            title = attrs_map.get("title") or attrs_map.get("aria-label")
            if title:
                self._link_text.append(title)
        elif tag.lower() == "img" and self._link_href:
            alt = attrs_map.get("alt") or attrs_map.get("title")
            if alt:
                self._link_text.append(alt)
            image = first_image_url(attrs_map)
            if image:
                self._link_image = image

    def handle_data(self, data: str) -> None:
        text = clean_spaces(data)
        if not text:
            return
        if self._link_href:
            self._link_text.append(text)
        else:
            self.tokens.append(Token("text", text))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._link_href:
            self.tokens.append(Token("link", clean_spaces(" ".join(self._link_text)), self._link_href, self._link_image))
            self._link_href = None
            self._link_text = []
            self._link_image = ""


def clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def first_image_url(attrs: dict[str, str]) -> str:
    for key in ("data-src", "data-original", "data-lazy-src", "data-image", "src"):
        if attrs.get(key):
            return clean_spaces(attrs[key])
    srcset = attrs.get("srcset") or attrs.get("data-srcset")
    if srcset:
        return clean_spaces(srcset.split(",", 1)[0].strip().split(" ", 1)[0])
    return ""


def normalize_display_title(title: str) -> str:
    title = clean_spaces(title)
    title = re.sub(r"^(?:مشاهدة|تحميل)\s+", "", title)
    title = re.sub(r"\s+(?:حصرى|حصري)\b.*$", "", title)
    title = re.sub(r"\s+اون\s+لاين.*$", "", title)
    title = re.sub(r"\s+على\s+أكثر\s+من\s+سيرفر.*$", "", title)
    return clean_spaces(title)


def detect_episode_number(title: str) -> int | None:
    match = re.search(r"(?:الحلقة|حلقة|ح)\s*(\d+)", title, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\b(?:episode|ep)\s*(\d+)\b", title, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def detect_kind(title: str, fallback: str = "mixed") -> str:
    if re.search(r"\bفيلم\b", title):
        return "movie"
    if "مسلسل" in title or "الحلقة" in title or re.search(r"\b(?:episode|ep)\b", title, re.I):
        return "series"
    if fallback in {"movie", "series"}:
        return fallback
    return "mixed"


def normalize_media_name(title: str, kind: str) -> str:
    title = normalize_display_title(title)
    title = re.sub(r"^(?:مشاهدة\s+)?(?:مسلسل|فيلم)\s+", "", title)
    if kind == "series":
        title = re.split(r"\s+(?:الموسم|موسم|الحلقة|حلقة)\b", title, maxsplit=1)[0]
    title = re.sub(r"\b(?:مترجم|مترجمة|مدبلج|مدبلجة)\b", "", title)
    title = re.sub(r"\b\d{4}\b", "", title)
    return clean_spaces(title)


def should_skip_title(title: str) -> bool:
    clean = normalize_display_title(title)
    if clean in NOISE_TITLES:
        return True
    if len(clean) < 4:
        return True
    if re.fullmatch(r"[\d. /]+", clean):
        return True
    return False


def fetch_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ar,en-US;q=0.8,en;q=0.6",
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc.reason}") from exc


def unique_values(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = value.rstrip("/")
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def provider_bases(provider: str) -> list[str]:
    if provider == "akwam":
        env_urls = os.environ.get("AKWAM_BASE_URLS", "")
        configured = [*(part.strip() for part in env_urls.split(",") if part.strip())]
        if "AKWAM_BASE_URL" in os.environ:
            configured.insert(0, AKWAM_BASE_URL)
        return unique_values([*configured, *DEFAULT_AKWAM_BASE_URLS])
    if provider == "alooytv":
        return [ALOOYTV_BASE_URL]
    raise ValueError(f"Unknown provider: {provider}")


def route_paths(route: CatalogRoute) -> list[str]:
    if route.provider != "akwam":
        return [route.path]
    paths: list[str] = []
    if route.kind == "series":
        paths.append("/series")
    elif route.kind == "movie":
        paths.append("/movies")
    elif route.path == "/recent":
        paths.append("/recent")
    paths.append(route.path)
    return unique_values(paths)


def route_urls(route: CatalogRoute) -> list[str]:
    urls: list[str] = []
    for base_url in provider_bases(route.provider):
        for path in route_paths(route):
            urls.append(urljoin(base_url + "/", path.lstrip("/")))
    return unique_values(urls)


def page_url(first_page_url: str, page: int) -> str:
    if page <= 1:
        return first_page_url
    parsed = urlparse(first_page_url)
    if parsed.query:
        query = parse_qs(parsed.query)
        query["page"] = [str(page)]
        return parsed._replace(query=urlencode(query, doseq=True)).geturl()
    return first_page_url.rstrip("/") + f"/page/{page}/"


def extract_links(document: str, base_url: str) -> list[Link]:
    parser = LinkExtractor()
    parser.feed(document)
    links: list[Link] = []
    for link in parser.links:
        text = clean_spaces(link.text)
        if not text:
            continue
        links.append(Link(urljoin(base_url, link.href), text, urljoin(base_url, link.image) if link.image else ""))
    return links


def extract_tokens(document: str, base_url: str) -> list[Token]:
    parser = TokenExtractor()
    parser.feed(document)
    tokens: list[Token] = []
    for token in parser.tokens:
        if token.kind == "link":
            tokens.append(Token("link", clean_spaces(token.text), urljoin(base_url, token.href), urljoin(base_url, token.image) if token.image else ""))
        else:
            tokens.append(Token("text", clean_spaces(token.text)))
    return [token for token in tokens if token.text or token.image]


def nearby_episode_count(tokens: list[Token], index: int) -> int | None:
    pattern = re.compile(rf"(?:^|\s)(?:\d(?:\.\d)?\s+)?(\d{{1,4}})\s*(?:{QUALITY_WORDS})?(?:\s|$)", re.I)
    for token in reversed(tokens[max(0, index - 10) : index]):
        text = token.text
        if text in NOISE_TITLES:
            continue
        if re.search(r"\b(?:19|20)\d{2}\b", text) and not re.search(QUALITY_WORDS, text, re.I):
            continue
        match = pattern.search(text)
        if not match:
            continue
        count = int(match.group(1))
        if 0 < count < 2000:
            return count
    return None


def route_accepts_title(route: CatalogRoute, title: str, kind: str) -> bool:
    if route.kind in {"movie", "series"} and kind != route.kind:
        return False
    if route.filter_terms and not any(term in title for term in route.filter_terms):
        return False
    return True


def route_accepts_link(route: CatalogRoute, title: str, url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    path = parsed.path.lower()
    if route.kind == "series":
        return "/series/" in path or detect_episode_number(title) is not None
    if route.kind == "movie":
        return "/movie/" in path or "/movies/" in path or detect_kind(title, "mixed") == "movie"
    return (
        "/series/" in path
        or "/movie/" in path
        or "/movies/" in path
        or detect_kind(title, "mixed") in {"movie", "series"}
    )


def extract_media_items(document: str, page_source_url: str, route: CatalogRoute) -> list[MediaItem]:
    items: dict[str, MediaItem] = {}
    tokens = extract_tokens(document, page_source_url)
    images_by_href = {token.href: token.image for token in tokens if token.kind == "link" and token.href and token.image}
    for index, token in enumerate(tokens):
        if token.kind != "link":
            continue
        if should_skip_title(token.text):
            continue
        kind = detect_kind(token.text, route.kind)
        if not route_accepts_title(route, token.text, kind):
            continue
        if not route_accepts_link(route, token.text, token.href):
            continue
        name = normalize_media_name(token.text, kind)
        if not name or should_skip_title(name):
            continue
        episode = detect_episode_number(token.text)
        nearby_count = nearby_episode_count(tokens, index) if kind == "series" else None
        key = f"{kind}:{name.casefold()}"
        item = items.get(key)
        image = token.image or images_by_href.get(token.href, "")
        if not item:
            item = MediaItem(name=name, kind=kind, url=token.href, source=route.provider, image=image)
            items[key] = item
        elif image and not item.image:
            item.image = image
        if episode:
            item.discovered_episodes.add(episode)
        if nearby_count and (not item.episode_count or nearby_count > item.episode_count):
            item.episode_count = nearby_count
        raw = normalize_display_title(token.text)
        if raw not in item.raw_titles:
            item.raw_titles.append(raw)
    for item in items.values():
        if item.kind == "series" and item.discovered_episodes and not item.episode_count:
            item.episode_count = max(item.discovered_episodes)
    return list(items.values())


def count_episodes_from_html(document: str) -> int | None:
    episodes: set[int] = set()
    for link in extract_links(document, ""):
        episode = detect_episode_number(link.text)
        if episode:
            episodes.add(episode)
    if episodes:
        return max(episodes)
    text = clean_spaces(re.sub(r"<[^>]+>", " ", document))
    for match in re.finditer(r"(?:الحلقات|episodes?)\D{0,80}(\d+)", text, flags=re.IGNORECASE):
        episodes.add(int(match.group(1)))
    return max(episodes) if episodes else None


def merge_items(items: Iterable[MediaItem]) -> list[MediaItem]:
    merged: dict[str, MediaItem] = {}
    for item in items:
        key = f"{item.kind}:{item.name.casefold()}"
        current = merged.get(key)
        if not current:
            merged[key] = item
            continue
        if item.image and not current.image:
            current.image = item.image
        current.raw_titles.extend(title for title in item.raw_titles if title not in current.raw_titles)
        current.discovered_episodes.update(item.discovered_episodes)
        if item.episode_count and (not current.episode_count or item.episode_count > current.episode_count):
            current.episode_count = item.episode_count
    return list(merged.values())


def scrape_catalog(catalog_id: str, pages: int = 1, search: str = "", fetch_details: bool = False) -> dict[str, object]:
    route = CATALOG_ROUTES.get(catalog_id)
    if not route:
        raise ValueError(f"Unknown catalog id: {catalog_id}")
    pages = max(1, min(int(pages), 25))
    first_urls = route_urls(route)
    scraped_items: list[MediaItem] = []
    errors: list[str] = []
    fetched_urls: list[str] = []
    for page in range(1, pages + 1):
        page_errors: list[str] = []
        page_items: list[MediaItem] = []
        for first_url in first_urls:
            url = page_url(first_url, page)
            fetched_urls.append(url)
            try:
                document = fetch_html(url)
            except RuntimeError as exc:
                page_errors.append(str(exc))
                continue
            page_items = extract_media_items(document, url, route)
            if page_items:
                scraped_items.extend(page_items)
                break
            page_errors.append(f"No media items found at {url}")
        else:
            errors.extend(page_errors)
        time.sleep(0.15)
    items = merge_items(scraped_items)
    if search:
        needle = search.casefold()
        items = [item for item in items if needle in item.name.casefold() or any(needle in title.casefold() for title in item.raw_titles)]
    if fetch_details:
        for item in items:
            if item.kind != "series":
                continue
            if item.episode_count:
                continue
            try:
                count = count_episodes_from_html(fetch_html(item.url))
            except RuntimeError as exc:
                errors.append(str(exc))
                continue
            if count and (not item.episode_count or count > item.episode_count):
                item.episode_count = count
            time.sleep(0.15)
    items.sort(key=lambda item: (item.kind != "series", item.name))
    return {
        "catalog": catalog_id,
        "catalog_name": route.name,
        "source": route.provider,
        "urls": fetched_urls,
        "count": len(items),
        "errors": errors,
        "items": [item.to_dict() for item in items],
    }


INDEX_HTML = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ArabCity Scraper</title>
  <style>
    :root { color-scheme: light; --ink:#17202a; --muted:#667085; --line:#d8dee8; --panel:#ffffff; --brand:#0d9488; --bg:#f4f7fb; --bad:#b42318; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Tahoma, Arial, sans-serif; background: var(--bg); color: var(--ink); }
    header { padding: 22px clamp(14px, 4vw, 42px); background: #111827; color: white; }
    h1 { margin: 0 0 6px; font-size: clamp(24px, 4vw, 38px); letter-spacing: 0; }
    header p { margin: 0; color: #cbd5e1; }
    main { max-width: 1180px; margin: 0 auto; padding: 20px clamp(12px, 3vw, 28px) 34px; }
    form { display: grid; grid-template-columns: minmax(220px, 2fr) minmax(120px, .7fr) minmax(160px, 1fr) auto; gap: 10px; align-items: end; }
    label { display: grid; gap: 6px; font-size: 13px; color: var(--muted); }
    select, input, button { min-height: 42px; border: 1px solid var(--line); border-radius: 6px; padding: 0 12px; font: inherit; background: white; color: var(--ink); }
    button { border-color: var(--brand); background: var(--brand); color: white; cursor: pointer; font-weight: 700; }
    .toggle { display: flex; align-items: center; gap: 8px; color: var(--ink); min-height: 42px; }
    .toggle input { min-height: auto; }
    .status { margin: 16px 0; color: var(--muted); min-height: 24px; }
    .status.error { color: var(--bad); }
    table { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
    th, td { padding: 12px; border-bottom: 1px solid var(--line); text-align: right; vertical-align: top; }
    th { background: #eef4f8; font-size: 13px; color: #344054; }
    tr:last-child td { border-bottom: 0; }
    a { color: #0f766e; text-decoration: none; }
    .poster { width: 58px; height: 82px; object-fit: cover; border-radius: 6px; border: 1px solid var(--line); background: #e5e7eb; display: block; }
    .poster-missing { width: 58px; height: 82px; border-radius: 6px; border: 1px solid var(--line); background: linear-gradient(135deg, #e5e7eb, #f8fafc); display: grid; place-items: center; color: #64748b; font-size: 11px; }
    .pill { display: inline-block; min-width: 68px; text-align: center; border-radius: 999px; padding: 3px 9px; background: #e6f6f4; color: #0f766e; font-size: 12px; }
    .raw { color: var(--muted); font-size: 12px; margin-top: 4px; }
    @media (max-width: 760px) {
      form { grid-template-columns: 1fr; }
      th:nth-child(5), td:nth-child(5) { display: none; }
      table { font-size: 14px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>ArabCity Scraper</h1>
    <p>استخراج أسماء الأفلام والمسلسلات وعدد الحلقات المتاح من صفحات الكتالوج.</p>
  </header>
  <main>
    <form id="scrapeForm">
      <label>الكتالوج
        <select id="catalog"></select>
      </label>
      <label>عدد الصفحات
        <input id="pages" type="number" min="1" max="25" value="1">
      </label>
      <label>بحث داخل النتائج
        <input id="search" type="search" placeholder="اختياري">
      </label>
      <label class="toggle">
        <input id="details" type="checkbox" checked>
        حساب الحلقات من التفاصيل
      </label>
      <button type="submit">بدء الاستخراج</button>
    </form>
    <div id="status" class="status">جاهز.</div>
    <table>
      <thead>
        <tr>
          <th>الصورة</th>
          <th>الاسم</th>
          <th>النوع</th>
          <th>الحلقات</th>
          <th>المصدر</th>
          <th>الرابط</th>
        </tr>
      </thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <script>
    const catalog = document.querySelector("#catalog");
    const rows = document.querySelector("#rows");
    const statusBox = document.querySelector("#status");

    function setStatus(text, isError = false) {
      statusBox.textContent = text;
      statusBox.className = isError ? "status error" : "status";
    }

    async function loadCatalogs() {
      const response = await fetch("/api/catalogs");
      const data = await response.json();
      for (const item of data.catalogs) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = `${item.name} (${item.id})`;
        catalog.appendChild(option);
      }
    }

    function renderItems(items) {
      rows.innerHTML = "";
      for (const item of items) {
        const tr = document.createElement("tr");
        const raw = item.raw_titles && item.raw_titles.length ? `<div class="raw">${escapeHtml(item.raw_titles[0])}</div>` : "";
        tr.innerHTML = `
          <td>${posterMarkup(item)}</td>
          <td>${escapeHtml(item.name)}${raw}</td>
          <td><span class="pill">${item.kind === "series" ? "مسلسل" : item.kind === "movie" ? "فيلم" : "مختلط"}</span></td>
          <td>${item.kind === "series" ? (item.episode_count || "غير معروف") : "-"}</td>
          <td>${escapeHtml(item.source)}</td>
          <td><a href="${item.url}" target="_blank" rel="noreferrer">فتح</a></td>
        `;
        rows.appendChild(tr);
      }
    }

    function posterMarkup(item) {
      if (!item.image) return `<div class="poster-missing">N/A</div>`;
      return `<img class="poster" src="${escapeHtml(item.image)}" alt="${escapeHtml(item.name)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('div'), { className: 'poster-missing', textContent: 'N/A' }))">`;
    }

    function escapeHtml(value) {
      return String(value || "").replace(/[&<>"']/g, ch => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[ch]));
    }

    document.querySelector("#scrapeForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      rows.innerHTML = "";
      setStatus("جار الاستخراج...");
      const params = new URLSearchParams({
        catalog: catalog.value,
        pages: document.querySelector("#pages").value || "1",
        search: document.querySelector("#search").value || "",
        details: document.querySelector("#details").checked ? "1" : "0",
      });
      try {
        const response = await fetch(`/api/scrape?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "تعذر الاستخراج");
        renderItems(data.items);
        const suffix = data.errors.length ? ` مع ${data.errors.length} أخطاء` : "";
        setStatus(`تم استخراج ${data.count} نتيجة من ${data.catalog_name}${suffix}.`);
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    loadCatalogs().catch(error => setStatus(error.message, true));
  </script>
</body>
</html>
"""


class ArabCityHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_text(INDEX_HTML, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/catalogs":
            self.send_json({"manifest": MANIFEST, "catalogs": MANIFEST["catalogs"]})
            return
        if parsed.path == "/api/scrape":
            params = parse_qs(parsed.query)
            catalog = params.get("catalog", ["akoam-series-all"])[0]
            pages = int(params.get("pages", ["1"])[0] or "1")
            search = params.get("search", [""])[0]
            details = params.get("details", ["0"])[0] in {"1", "true", "yes"}
            try:
                self.send_json(scrape_catalog(catalog, pages=pages, search=search, fetch_details=details))
            except Exception as exc:  # noqa: BLE001 - API must return user-readable errors.
                self.send_json({"error": str(exc)}, status=400)
            return
        self.send_json({"error": "Not found"}, status=404)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_text(self, body: str, content_type: str, status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, payload: dict[str, object], status: int = 200) -> None:
        self.send_text(json.dumps(payload, ensure_ascii=False, indent=2), "application/json; charset=utf-8", status)


def serve(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), ArabCityHandler)
    try:
        print(f"ArabCity Scraper running at http://{host}:{port}", flush=True)
    except OSError:
        pass
    server.serve_forever()


def print_table(result: dict[str, object]) -> None:
    print(f"{result['catalog_name']} - {result['count']} items")
    for item in result["items"]:
        episode_count = item["episode_count"] if item["episode_count"] else "-"
        print(f"{item['kind']:6} | {episode_count!s:>4} | {item['name']} | {item['url']}")
    if result["errors"]:
        print("\nErrors:", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape ArabCity catalog names and series episode counts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape_parser = subparsers.add_parser("scrape", help="Scrape one catalog.")
    scrape_parser.add_argument("--catalog", default="akoam-series-all", choices=sorted(CATALOG_ROUTES))
    scrape_parser.add_argument("--pages", type=int, default=1)
    scrape_parser.add_argument("--search", default="")
    scrape_parser.add_argument("--details", action="store_true", help="Fetch detail pages to improve episode counts.")
    scrape_parser.add_argument("--json", action="store_true", help="Print JSON instead of a table.")

    serve_parser = subparsers.add_parser("serve", help="Run the local web UI.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        serve(args.host, args.port)
        return 0
    result = scrape_catalog(args.catalog, pages=args.pages, search=args.search, fetch_details=args.details)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_table(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
