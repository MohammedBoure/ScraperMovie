from __future__ import annotations

import argparse
from collections import OrderedDict
from copy import deepcopy
import html
import ipaddress
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 ArabCityScraper/1.0"
)

AKWAM_BASE_URL = os.environ.get("AKWAM_BASE_URL", "https://akwam.cyou").rstrip("/")
ALOOYTV_BASE_URL = os.environ.get("ALOOYTV_BASE_URL", "https://alooytv.co").rstrip("/")
ARABCITY_ADDON_BASE_URL = os.environ.get("ARABCITY_ADDON_BASE_URL", "https://arabcity.fly.dev").rstrip("/")
REQUEST_TIMEOUT = float(os.environ.get("ARABCITY_TIMEOUT", "20"))
DEFAULT_AKWAM_BASE_URLS = (
    "https://tv.akwam.tv",
    "https://ak.sv",
    "https://akwam.cyou",
    "https://akwem.com",
    "https://akwams.org",
)
QUALITY_WORDS = "WEB-DL|HDTV|BluRay|WebRip|BRRIP|DVDrip|DVDSCR|HD|HDTS|CAM|BDRIP|HDRIP|HC"


def env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


def env_float(name: str, default: float, minimum: float = 0.0, maximum: float | None = None) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    value = max(minimum, value)
    return min(value, maximum) if maximum is not None else value


WORKER_HARD_CAP = 8
DEFAULT_WORKERS = 6
SOURCE_SUBMIT_DELAY = 0.03
EPISODE_CACHE_LIMIT = env_int("ARABCITY_EPISODE_CACHE_SIZE", 128)
CATALOG_CACHE_LIMIT = env_int("ARABCITY_CATALOG_CACHE_SIZE", 32)
EPISODE_META_CACHE: OrderedDict[tuple[str, str, str], tuple[list["EpisodeLink"], list[str]]] = OrderedDict()
EPISODE_META_CACHE_LOCK = Lock()
EPISODE_LINKS_CACHE: OrderedDict[str, tuple[list["EpisodeLink"], list[str]]] = OrderedDict()
EPISODE_LINKS_CACHE_LOCK = Lock()
CATALOG_CACHE: OrderedDict[tuple[str, int, str, bool, bool, str, int], dict[str, object]] = OrderedDict()
CATALOG_CACHE_LOCK = Lock()
EPISODE_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
ARABIC_SEARCH_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ئ": "ي",
        "ؤ": "و",
        "ة": "ه",
        "ۀ": "ه",
        "ـ": "",
    }
)
ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")


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

COMPLETE_LIBRARY_CATALOG_ID = "arabcity-complete-library"
SOURCE_FILTERS = {"all", "akwam", "alooytv"}


def manifest_catalog_ids() -> tuple[str, ...]:
    return tuple(
        str(catalog.get("id"))
        for catalog in MANIFEST["catalogs"]
        if str(catalog.get("id")) in CATALOG_ROUTES
    )


CATALOG_GROUPS: dict[str, tuple[str, ...]] = {
    COMPLETE_LIBRARY_CATALOG_ID: manifest_catalog_ids(),
}
VIRTUAL_CATALOGS = [
    {"type": "ArabCity-combined", "id": COMPLETE_LIBRARY_CATALOG_ID, "name": "⭐ المكتبة الكاملة: أفلام ومسلسلات"},
]


def available_catalogs() -> list[dict[str, str]]:
    return [*VIRTUAL_CATALOGS, *MANIFEST["catalogs"]]


def all_catalog_ids() -> tuple[str, ...]:
    return (*CATALOG_GROUPS, *CATALOG_ROUTES)


def normalize_source_filter(source_filter: str = "all") -> str:
    value = clean_spaces(source_filter).casefold()
    return value if value in SOURCE_FILTERS else "all"


def catalog_matches_source_filter(catalog_id: str, source_filter: str = "all") -> bool:
    source_filter = normalize_source_filter(source_filter)
    if source_filter == "all":
        return True
    route = CATALOG_ROUTES.get(catalog_id)
    return bool(route and route.provider == source_filter)


def worker_request_value(value: object | None = None, env_name: str = "ARABCITY_GROUP_WORKERS") -> int:
    raw_value = os.environ.get(env_name, str(DEFAULT_WORKERS)) if value in {None, ""} else value
    try:
        return int(str(raw_value).strip())
    except (TypeError, ValueError):
        return DEFAULT_WORKERS


def bounded_worker_count(value: object | None = None, env_name: str = "ARABCITY_GROUP_WORKERS") -> int:
    requested = worker_request_value(value, env_name=env_name)
    return max(1, min(requested, WORKER_HARD_CAP))


def source_submit_delay() -> float:
    return env_float("ARABCITY_SOURCE_SUBMIT_DELAY", SOURCE_SUBMIT_DELAY, minimum=0.0, maximum=0.5)


def performance_info(worker_count: int, requested_workers: int, task_count: int = 0) -> dict[str, object]:
    return {
        "workers": worker_count,
        "requested_workers": requested_workers,
        "worker_cap": WORKER_HARD_CAP,
        "source_delay_ms": int(source_submit_delay() * 1000),
        "tasks": task_count,
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
    description: str = ""
    episode_count: int | None = None
    playable: bool = False
    playable_checked: bool = False
    playable_streams: int = 0
    discovered_episodes: set[int] = field(default_factory=set)
    raw_titles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "url": self.url,
            "source": self.source,
            "image": self.image,
            "description": self.description,
            "episode_count": self.episode_count,
            "playable": self.playable,
            "playable_checked": self.playable_checked,
            "playable_streams": self.playable_streams,
            "raw_titles": self.raw_titles[:5],
        }


@dataclass(frozen=True)
class EpisodeLink:
    title: str
    url: str
    number: int | None = None
    image: str = ""
    stream_id: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "url": self.url,
            "number": self.number,
            "image": self.image,
            "stream_id": self.stream_id,
            "playable_reference": has_episode_playable_reference(self),
        }


@dataclass(frozen=True)
class PlayerLink:
    url: str
    kind: str
    title: str = "Direct player"

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "kind": self.kind,
            "title": self.title,
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


class PlayerExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.players: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        src = attrs_map.get("src") or attrs_map.get("data-src") or attrs_map.get("data-lazy-src")
        if not src:
            return
        tag = tag.lower()
        if tag in {"iframe", "embed"}:
            self.players.append((src, "iframe"))
        elif tag in {"video", "source"}:
            self.players.append((src, "video" if is_video_url(src) else "iframe"))


def clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def normalize_search_text(value: object) -> str:
    text = clean_spaces(str(value or ""))
    text = ARABIC_DIACRITICS_RE.sub("", text)
    text = text.translate(EPISODE_DIGIT_TRANSLATION).translate(ARABIC_SEARCH_TRANSLATION)
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return clean_spaces(text.casefold())


def kind_search_terms(kind: str) -> list[str]:
    if kind == "series":
        return ["series", "show", "tv", "مسلسل", "مسلسلات"]
    if kind == "movie":
        return ["movie", "film", "فيلم", "افلام", "أفلام"]
    return [kind, "mixed", "مختلط"] if kind else []


def item_search_text(item: "MediaItem") -> str:
    fields = [
        item.name,
        item.kind,
        item.source,
        item.description,
        *kind_search_terms(item.kind),
        *item.raw_titles,
    ]
    return normalize_search_text(" ".join(field for field in fields if field))


def search_matches_item(item: "MediaItem", query: str) -> bool:
    needle = normalize_search_text(query)
    if not needle:
        return True
    haystack = item_search_text(item)
    compact_haystack = haystack.replace(" ", "")
    for term in needle.split():
        compact_term = term.replace(" ", "")
        if term not in haystack and compact_term not in compact_haystack:
            return False
    return True


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


def episode_number_from_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    text = clean_spaces(str(value or "")).translate(EPISODE_DIGIT_TRANSLATION)
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def detect_episode_number(title: str) -> int | None:
    title = clean_spaces(title).translate(EPISODE_DIGIT_TRANSLATION)
    match = re.search(r"(?:الحلقة|حلقة)\s*(\d+)", title, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"(?:^|\s)ح\s*(\d+)(?=\s|$)", title, flags=re.IGNORECASE)
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
    if detect_episode_number(clean) is not None:
        return False
    if len(clean) < 4:
        return True
    if re.fullmatch(r"[\d. /]+", clean):
        return True
    return False


def request_safe_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").encode("idna").decode("ascii")
    netloc = host
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if parsed.username:
        userinfo = quote(parsed.username, safe="")
        if parsed.password:
            userinfo = f"{userinfo}:{quote(parsed.password, safe='')}"
        netloc = f"{userinfo}@{netloc}"
    path = quote(parsed.path or "/", safe="/%:@")
    query = quote(parsed.query, safe="=&?/%:+,;@")
    fragment = quote(parsed.fragment, safe="=&?/%:+,;@")
    return urlunsplit((parsed.scheme, netloc, path, query, fragment))


def fetch_html(url: str) -> str:
    request = Request(
        request_safe_url(url),
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


def fetch_json(url: str) -> dict[str, object]:
    request = Request(
        request_safe_url(url),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "ar,en-US;q=0.8,en;q=0.6",
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(raw.decode(charset, errors="replace"))
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON while fetching {url}") from exc


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


def is_private_or_local_host(host: str) -> bool:
    host = host.strip("[]").casefold()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def is_allowed_source_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.netloc.casefold()
    if "@" in host:
        return False
    hostname = parsed.hostname or ""
    if is_private_or_local_host(hostname):
        return False
    allowed_hosts = {
        urlparse(base_url).netloc.casefold()
        for provider in ("akwam", "alooytv")
        for base_url in provider_bases(provider)
        if urlparse(base_url).netloc
    }
    if any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts):
        return True
    return "." in hostname


def looks_like_episode_link(title: str, url: str) -> bool:
    if detect_episode_number(title) is not None:
        return True
    path = urlparse(url).path.casefold()
    return bool(re.search(r"/(?:episode|episodes|watch|video|videos)(?:/|$)", path))


def is_video_url(url: str) -> bool:
    return bool(re.search(r"\.(?:mp4|m3u8|mpd|webm|ogg|mov)(?:$|[?#])", urlparse(url).path.casefold()))


def has_episode_playable_reference(episode: EpisodeLink) -> bool:
    return bool(episode.stream_id) or (bool(episode.url) and is_video_url(episode.url) and is_allowed_source_url(episode.url))


def extract_episode_links(document: str, page_source_url: str) -> list[EpisodeLink]:
    episodes: dict[str, EpisodeLink] = {}
    for token in extract_tokens(document, page_source_url):
        if token.kind != "link":
            continue
        title = normalize_display_title(token.text)
        if should_skip_title(title) or not looks_like_episode_link(title, token.href):
            continue
        key = token.href.rstrip("/")
        if key in episodes:
            continue
        number = detect_episode_number(title)
        if not title:
            title = f"Episode {number}" if number else "Watch"
        episode = EpisodeLink(title=title, url=token.href, number=number, image=token.image)
        if not has_episode_playable_reference(episode):
            continue
        episodes[key] = episode
    return sorted(
        episodes.values(),
        key=lambda episode: (
            episode.number is None,
            -(episode.number or 0),
            episode.title.casefold(),
        ),
    )


BLOCKED_PLAYER_HOST_TERMS = (
    "doubleclick",
    "googlesyndication",
    "google-analytics",
    "facebook",
    "twitter",
    "adservice",
    "taboola",
)


def player_score(player: PlayerLink, page_url: str) -> tuple[int, str]:
    parsed = urlparse(player.url)
    path = parsed.path.casefold()
    host = parsed.netloc.casefold()
    score = 0
    if player.kind == "video":
        score += 60
    if re.search(r"(?:embed|player|watch|video|stream)", path):
        score += 30
    if host and host != urlparse(page_url).netloc.casefold():
        score += 5
    if any(term in host for term in BLOCKED_PLAYER_HOST_TERMS):
        score -= 100
    return score, player.url


def extract_player_links(document: str, page_source_url: str) -> list[PlayerLink]:
    parser = PlayerExtractor()
    parser.feed(document)
    players: dict[str, PlayerLink] = {}
    for raw_url, kind in parser.players:
        url = urljoin(page_source_url, clean_spaces(raw_url))
        if not is_allowed_source_url(url):
            continue
        players[url.rstrip("/")] = PlayerLink(url=url, kind=kind)
    for match in re.finditer(r"https?://[^\s\"'<>]+", document):
        url = html.unescape(match.group(0)).rstrip(").,;")
        if not is_video_url(url) or not is_allowed_source_url(url):
            continue
        players[url.rstrip("/")] = PlayerLink(url=url, kind="video", title="Direct video")
    return sorted(players.values(), key=lambda player: player_score(player, page_source_url), reverse=True)


def addon_type_for_source(source: str = "akwam") -> str:
    return "ArabCity-alooytv" if source == "alooytv" else "ArabCity-Akwam"


def stremio_url(resource: str, item_type: str, item_id: str) -> str:
    encoded_id = quote(item_id, safe="")
    return f"{ARABCITY_ADDON_BASE_URL}/{resource}/{item_type}/{encoded_id}.json"


def stremio_catalog_url(item_type: str, catalog_id: str, extra: str = "") -> str:
    if extra:
        return f"{ARABCITY_ADDON_BASE_URL}/catalog/{item_type}/{catalog_id}/{quote(extra, safe='=&')}.json"
    return f"{ARABCITY_ADDON_BASE_URL}/catalog/{item_type}/{catalog_id}.json"


def source_slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return tail or "item"


def media_url_from_addon_id(item_id: str) -> str:
    if ":" not in item_id:
        return ""
    return unquote(item_id.rsplit(":", 1)[-1])


def build_addon_item_id(media_url: str, kind: str = "series", source: str = "akwam", name: str = "") -> str:
    slug = name or source_slug_from_url(media_url)
    provider = "alooytv" if source == "alooytv" else "akoam"
    addon_kind = "movie" if kind == "movie" else "series"
    return f"arabcity:{provider}:{addon_kind}:{slug}:{quote(media_url, safe='')}"


def addon_meta_for_media(media_url: str, kind: str = "series", source: str = "akwam", name: str = "") -> dict[str, object]:
    item_type = addon_type_for_source(source)
    item_id = build_addon_item_id(media_url, kind=kind, source=source, name=name)
    return fetch_json(stremio_url("meta", item_type, item_id))


def addon_episode_links(media_url: str, source: str = "akwam", name: str = "") -> list[EpisodeLink]:
    payload = addon_meta_for_media(media_url, kind="series", source=source, name=name)
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return []
    videos = meta.get("videos")
    if not isinstance(videos, list):
        return []
    episodes: list[EpisodeLink] = []
    for video in videos:
        if not isinstance(video, dict):
            continue
        stream_id = str(video.get("id") or "")
        if not stream_id:
            continue
        title = clean_spaces(str(video.get("title") or ""))
        number = episode_number_from_value(video.get("episode")) or detect_episode_number(title)
        episode_url = unquote(stream_id.rsplit(":", 1)[-1]) if ":" in stream_id else media_url
        episodes.append(
            EpisodeLink(
                title=title or (f"Episode {number}" if number else "Watch"),
                url=episode_url,
                number=number,
                image=str(video.get("thumbnail") or ""),
                stream_id=stream_id,
            )
        )
    return sorted(
        episodes,
        key=lambda episode: (
            episode.number is None,
            -(episode.number or 0),
            episode.title.casefold(),
        ),
    )


def episode_meta_cache_key(media_url: str, source: str = "akwam", name: str = "") -> tuple[str, str, str]:
    return media_url.rstrip("/"), source or "akwam", name.casefold()


def episode_links_cache_key(media_url: str) -> str:
    return media_url.rstrip("/")


def trim_episode_cache(cache: OrderedDict, limit: int | None = None) -> None:
    limit = EPISODE_CACHE_LIMIT if limit is None else limit
    while len(cache) > limit:
        cache.popitem(last=False)


def clear_episode_cache() -> None:
    with EPISODE_LINKS_CACHE_LOCK:
        EPISODE_LINKS_CACHE.clear()


def clear_episode_caches() -> None:
    with EPISODE_META_CACHE_LOCK:
        EPISODE_META_CACHE.clear()
    clear_episode_cache()


def clear_episode_meta_cache() -> None:
    clear_episode_caches()


def cached_addon_episode_links(media_url: str, source: str = "akwam", name: str = "") -> tuple[list[EpisodeLink], list[str]]:
    key = episode_meta_cache_key(media_url, source, name)
    with EPISODE_META_CACHE_LOCK:
        cached = EPISODE_META_CACHE.get(key)
        if cached is not None:
            EPISODE_META_CACHE.move_to_end(key)
    if cached is not None:
        return cached

    errors: list[str] = []
    episodes: list[EpisodeLink] = []
    for source_name in item_sources(source):
        try:
            episodes = addon_episode_links(media_url, source=source_name, name=name)
        except Exception as exc:  # noqa: BLE001 - meta prechecks should degrade to "unconfirmed".
            errors.append(str(exc))
            continue
        if episodes:
            break

    result = (episodes, errors)
    with EPISODE_META_CACHE_LOCK:
        EPISODE_META_CACHE[key] = result
        EPISODE_META_CACHE.move_to_end(key)
        trim_episode_cache(EPISODE_META_CACHE)
    return result


def cached_episode_links(media_url: str, source: str = "akwam", name: str = "") -> tuple[list[EpisodeLink], list[str]]:
    key = episode_links_cache_key(media_url)
    with EPISODE_LINKS_CACHE_LOCK:
        cached = EPISODE_LINKS_CACHE.get(key)
        if cached is not None:
            EPISODE_LINKS_CACHE.move_to_end(key)
    if cached is not None:
        return cached

    errors: list[str] = []
    episodes, meta_errors = cached_addon_episode_links(media_url, source=source, name=name)
    errors.extend(meta_errors)
    if not episodes:
        document = fetch_html(media_url)
        episodes = extract_episode_links(document, media_url)
    episodes = [episode for episode in episodes if has_episode_playable_reference(episode)]

    result = (episodes, errors)
    with EPISODE_LINKS_CACHE_LOCK:
        EPISODE_LINKS_CACHE[key] = result
        EPISODE_LINKS_CACHE.move_to_end(key)
        trim_episode_cache(EPISODE_LINKS_CACHE)
    return result


def player_from_addon_stream(stream_id: str, item_type: str = "ArabCity-Akwam") -> list[PlayerLink]:
    if not stream_id:
        return []
    payload = fetch_json(stremio_url("stream", item_type, stream_id))
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return []
    players: list[PlayerLink] = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        direct_url = str(stream.get("url") or "")
        external_url = str(stream.get("externalUrl") or "")
        stream_url = direct_url or (external_url if is_video_url(external_url) else "")
        if not stream_url or not is_allowed_source_url(stream_url):
            continue
        title = clean_spaces(str(stream.get("title") or stream.get("name") or "ArabCity stream"))
        players.append(PlayerLink(url=stream_url, kind="video", title=title))
    return players


def direct_video_players(players: Iterable[PlayerLink]) -> list[PlayerLink]:
    return [player for player in players if player.kind == "video" and is_allowed_source_url(player.url)]


def item_sources(source: str) -> list[str]:
    sources = [part.strip() for part in source.split("+") if part.strip()]
    return sources or ["akwam"]


def check_player_availability(
    media_url: str = "",
    kind: str = "mixed",
    source: str = "akwam",
    name: str = "",
    stream_id: str = "",
) -> dict[str, object]:
    if not media_url and not stream_id:
        raise ValueError("Missing media URL")
    if media_url and not is_allowed_source_url(media_url):
        raise ValueError("Unsupported media URL")
    if media_url and is_video_url(media_url):
        return {
            "url": media_url,
            "kind": kind,
            "source": source,
            "name": name,
            "checked": True,
            "status": "direct",
            "playable": True,
            "streams": 1,
            "errors": [],
        }

    errors: list[str] = []
    stream_count = 0

    def count_stream_players(current_stream_id: str, item_type: str) -> int:
        if not current_stream_id:
            return 0
        try:
            return len(direct_video_players(player_from_addon_stream(current_stream_id, item_type=item_type)))
        except RuntimeError as exc:
            errors.append(str(exc))
            return 0

    for source_name in item_sources(source):
        item_type = addon_type_for_source(source_name)
        if stream_id:
            stream_count += count_stream_players(stream_id, item_type)
        if not stream_id and kind in {"movie", "mixed"}:
            movie_stream_id = build_addon_item_id(media_url, kind="movie", source=source_name, name=name)
            stream_count += count_stream_players(movie_stream_id, item_type)
        if stream_count:
            break
        if not stream_id and kind in {"series", "mixed"}:
            episodes, episode_errors = cached_addon_episode_links(media_url, source=source_name, name=name)
            errors.extend(episode_errors)
            for episode in episodes:
                stream_count += count_stream_players(episode.stream_id, item_type)
                if stream_count:
                    break
        if stream_count:
            break

    status = "direct" if stream_count else "uncertain" if errors else "unavailable"
    return {
        "url": media_url,
        "kind": kind,
        "source": source,
        "name": name,
        "checked": True,
        "status": status,
        "playable": stream_count > 0,
        "streams": stream_count,
        "errors": errors,
    }


def playable_stream_count(item: MediaItem) -> int:
    for source in item_sources(item.source):
        item_type = addon_type_for_source(source)
        if item.kind in {"movie", "mixed"}:
            stream_id = build_addon_item_id(item.url, kind="movie", source=source, name=item.name)
            try:
                players = direct_video_players(player_from_addon_stream(stream_id, item_type=item_type))
            except RuntimeError:
                players = []
            if players:
                return len(players)
        if item.kind in {"series", "mixed"}:
            episodes, _errors = cached_addon_episode_links(item.url, source=source, name=item.name)
            for episode in episodes:
                if not episode.stream_id:
                    continue
                try:
                    players = direct_video_players(player_from_addon_stream(episode.stream_id, item_type=item_type))
                except RuntimeError:
                    continue
                if players:
                    return len(players)
    return 0


def mark_playability(item: MediaItem) -> MediaItem:
    try:
        count = playable_stream_count(item)
    except Exception:  # noqa: BLE001 - one bad stream check should only exclude that item.
        count = 0
    item.playable_checked = True
    item.playable_streams = count
    item.playable = count > 0
    return item


def filter_playable_items(items: list[MediaItem], workers: object | None = None) -> list[MediaItem]:
    if not items:
        return []
    worker_count = min(len(items), bounded_worker_count(workers, env_name="ARABCITY_PLAYABLE_WORKERS"))
    submit_delay = source_submit_delay()
    checked: list[MediaItem] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = []
        for index, item in enumerate(items):
            if index and submit_delay and index % worker_count == 0:
                time.sleep(submit_delay)
            futures.append(executor.submit(mark_playability, item))
        for future in as_completed(futures):
            checked.append(future.result())
    return [item for item in checked if item.playable]


def media_item_from_addon_meta(meta: dict[str, object], route: CatalogRoute) -> MediaItem | None:
    item_id = str(meta.get("id") or "")
    url = media_url_from_addon_id(item_id)
    if not url:
        return None
    name = clean_spaces(str(meta.get("name") or ""))
    if not name:
        return None
    kind = "series" if ":series:" in item_id else "movie" if ":movie:" in item_id else detect_kind(name, route.kind)
    item = MediaItem(
        name=name,
        kind=kind,
        url=url,
        source=route.provider,
        image=str(meta.get("poster") or meta.get("background") or ""),
        description=clean_spaces(str(meta.get("description") or "")),
        raw_titles=[name],
    )
    return item


def addon_catalog_items(catalog_id: str, route: CatalogRoute, pages: int, search: str = "") -> tuple[list[MediaItem], list[str], list[str]]:
    items: list[MediaItem] = []
    errors: list[str] = []
    fetched_urls: list[str] = []
    item_type = addon_type_for_source(route.provider)
    page_size = 100
    for page in range(1, pages + 1):
        extras: list[str] = []
        if search:
            extras.append(f"search={search}")
        if page > 1:
            extras.append(f"skip={(page - 1) * page_size}")
        url = stremio_catalog_url(item_type, catalog_id, "&".join(extras))
        fetched_urls.append(url)
        try:
            payload = fetch_json(url)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        metas = payload.get("metas")
        if not isinstance(metas, list):
            errors.append(f"Invalid catalog payload at {url}")
            continue
        for meta in metas:
            if not isinstance(meta, dict):
                continue
            item = media_item_from_addon_meta(meta, route)
            if item:
                items.append(item)
    return items, errors, fetched_urls


def scrape_player(media_url: str, stream_id: str = "") -> dict[str, object]:
    if not media_url and not stream_id:
        raise ValueError("Missing media URL")
    players: list[PlayerLink] = []
    errors: list[str] = []
    if stream_id:
        try:
            players = direct_video_players(player_from_addon_stream(stream_id))
        except RuntimeError as exc:
            errors.append(str(exc))
    if not media_url:
        media_url = players[0].url if players else ""
    if media_url and not is_allowed_source_url(media_url):
        raise ValueError("Unsupported media URL")
    if not players and media_url and is_video_url(media_url):
        players = [PlayerLink(url=media_url, kind="video", title="Direct video")]
    if not players:
        document = fetch_html(media_url)
        players = direct_video_players(extract_player_links(document, media_url))
    if not players:
        raise ValueError("لا يوجد رابط فيديو مباشر قابل للتشغيل داخل الصفحة.")
    selected = players[0]
    return {
        "url": media_url,
        "selected": selected.to_dict(),
        "errors": errors,
        "players": [player.to_dict() for player in players],
    }


def scrape_episode_meta(media_url: str, source: str = "akwam", name: str = "") -> dict[str, object]:
    if not media_url:
        raise ValueError("Missing media URL")
    if not is_allowed_source_url(media_url):
        raise ValueError("Unsupported media URL")
    episodes, errors = cached_addon_episode_links(media_url, source=source, name=name)
    episodes = [episode for episode in episodes if has_episode_playable_reference(episode)]
    return {
        "url": media_url,
        "source": source,
        "name": name,
        "checked": True,
        "count": len(episodes),
        "errors": errors,
        "episodes": [episode.to_dict() for episode in episodes],
    }


def scrape_episodes(media_url: str, source: str = "akwam", name: str = "") -> dict[str, object]:
    if not media_url:
        raise ValueError("Missing media URL")
    if not is_allowed_source_url(media_url):
        raise ValueError("Unsupported media URL")
    episodes, errors = cached_episode_links(media_url, source=source, name=name)
    return {
        "url": media_url,
        "count": len(episodes),
        "errors": errors,
        "episodes": [episode.to_dict() for episode in episodes],
    }


def merge_items(items: Iterable[MediaItem]) -> list[MediaItem]:
    merged: dict[str, MediaItem] = {}
    for item in items:
        source_key = "+".join(sorted(source.strip().casefold() for source in item.source.split("+") if source.strip()))
        key = f"{item.kind}:{source_key}:{item.name.casefold()}"
        current = merged.get(key)
        if not current:
            merged[key] = item
            continue
        if item.image and not current.image:
            current.image = item.image
        if item.description and not current.description:
            current.description = item.description
        current.raw_titles.extend(title for title in item.raw_titles if title not in current.raw_titles)
        current.discovered_episodes.update(item.discovered_episodes)
        if item.episode_count and (not current.episode_count or item.episode_count > current.episode_count):
            current.episode_count = item.episode_count
    return list(merged.values())


def media_stats(items: Iterable[MediaItem]) -> dict[str, int]:
    stats = {
        "total": 0,
        "movies": 0,
        "series": 0,
        "mixed": 0,
        "sources": 0,
        "with_episodes": 0,
        "playable": 0,
        "checked": 0,
    }
    sources: set[str] = set()
    for item in items:
        stats["total"] += 1
        if item.kind == "movie":
            stats["movies"] += 1
        elif item.kind == "series":
            stats["series"] += 1
        else:
            stats["mixed"] += 1
        if item.episode_count and item.episode_count > 0:
            stats["with_episodes"] += 1
        if item.playable_checked:
            stats["checked"] += 1
        if item.playable:
            stats["playable"] += 1
        sources.update(source.strip() for source in item.source.split("+") if source.strip())
    stats["sources"] = len(sources)
    return stats


def media_item_from_payload(payload: dict[str, object]) -> MediaItem:
    episode_count = payload.get("episode_count")
    raw_titles = payload.get("raw_titles")
    return MediaItem(
        name=str(payload.get("name") or ""),
        kind=str(payload.get("kind") or "mixed"),
        url=str(payload.get("url") or ""),
        source=str(payload.get("source") or ""),
        image=str(payload.get("image") or ""),
        description=str(payload.get("description") or ""),
        episode_count=int(episode_count) if isinstance(episode_count, int) else None,
        playable=bool(payload.get("playable") or False),
        playable_checked=bool(payload.get("playable_checked") or False),
        playable_streams=int(payload.get("playable_streams") or 0),
        raw_titles=[str(title) for title in raw_titles] if isinstance(raw_titles, list) else [],
    )


def catalog_cache_key(
    catalog_id: str,
    pages: int = 1,
    search: str = "",
    fetch_details: bool = False,
    playable_only: bool = False,
    source_filter: str = "all",
    workers: object | None = None,
) -> tuple[str, int, str, bool, bool, str, int]:
    return (
        catalog_id,
        max(1, min(int(pages), 25)),
        normalize_search_text(search),
        bool(fetch_details),
        bool(playable_only),
        normalize_source_filter(source_filter),
        bounded_worker_count(workers),
    )


def trim_catalog_cache(limit: int | None = None) -> None:
    limit = CATALOG_CACHE_LIMIT if limit is None else limit
    while len(CATALOG_CACHE) > limit:
        CATALOG_CACHE.popitem(last=False)


def clear_catalog_cache() -> None:
    with CATALOG_CACHE_LOCK:
        CATALOG_CACHE.clear()


def cached_catalog_result(key: tuple[str, int, str, bool, bool, str, int]) -> dict[str, object] | None:
    with CATALOG_CACHE_LOCK:
        cached = CATALOG_CACHE.get(key)
        if cached is not None:
            CATALOG_CACHE.move_to_end(key)
    if cached is None:
        return None
    result = deepcopy(cached)
    result["cached"] = True
    return result


def store_catalog_result(key: tuple[str, int, str, bool, bool, str, int], result: dict[str, object]) -> dict[str, object]:
    stored = deepcopy(result)
    stored["cached"] = False
    with CATALOG_CACHE_LOCK:
        CATALOG_CACHE[key] = stored
        CATALOG_CACHE.move_to_end(key)
        trim_catalog_cache()
    return deepcopy(stored)


def scrape_catalog_group(
    catalog_id: str,
    pages: int = 1,
    search: str = "",
    fetch_details: bool = False,
    playable_only: bool = False,
    source_filter: str = "all",
    workers: object | None = None,
) -> dict[str, object]:
    child_catalogs = CATALOG_GROUPS.get(catalog_id)
    if not child_catalogs:
        raise ValueError(f"Unknown catalog id: {catalog_id}")
    source_filter = normalize_source_filter(source_filter)
    child_catalogs = tuple(child_id for child_id in child_catalogs if catalog_matches_source_filter(child_id, source_filter))
    pages = max(1, min(int(pages), 25))
    errors: list[str] = []
    fetched_urls: list[str] = []
    items: list[MediaItem] = []
    if not child_catalogs:
        requested_workers = worker_request_value(workers)
        worker_count = bounded_worker_count(workers)
        return {
            "catalog": catalog_id,
            "catalog_name": "المكتبة الكاملة",
            "source": "combined",
            "source_filter": source_filter,
            "urls": [],
            "count": 0,
            "playable_only": playable_only,
            "performance": performance_info(worker_count, requested_workers),
            "stats": media_stats([]),
            "errors": [],
            "items": [],
        }
    requested_workers = worker_request_value(workers)
    worker_count = min(len(child_catalogs), bounded_worker_count(workers))
    submit_delay = source_submit_delay()
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {}
        for index, child_id in enumerate(child_catalogs):
            if index and submit_delay:
                time.sleep(submit_delay)
            futures[
                executor.submit(
                    scrape_single_catalog,
                    child_id,
                    pages=pages,
                    search=search,
                    fetch_details=fetch_details,
                    fallback_to_site=False,
                )
            ] = child_id
        for future in as_completed(futures):
            child_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - one catalog should not hide the rest of the library.
                errors.append(f"{child_id}: {exc}")
                continue
            errors.extend(str(error) for error in result.get("errors", []))
            fetched_urls.extend(str(url) for url in result.get("urls", []))
            payload_items = result.get("items", [])
            if isinstance(payload_items, list):
                items.extend(media_item_from_payload(item) for item in payload_items if isinstance(item, dict))
    merged_items = merge_items(item for item in items if item.name and item.url)
    if playable_only:
        merged_items = filter_playable_items(merged_items, workers=workers)
    merged_items.sort(key=lambda item: (item.kind != "series", item.name, item.source))
    return {
        "catalog": catalog_id,
        "catalog_name": "المكتبة الكاملة",
        "source": "combined",
        "source_filter": source_filter,
        "urls": fetched_urls,
        "count": len(merged_items),
        "playable_only": playable_only,
        "performance": performance_info(worker_count, requested_workers, task_count=len(child_catalogs)),
        "stats": media_stats(merged_items),
        "errors": errors,
        "items": [item.to_dict() for item in merged_items],
    }


def scrape_single_catalog(
    catalog_id: str,
    pages: int = 1,
    search: str = "",
    fetch_details: bool = False,
    fallback_to_site: bool = True,
    playable_only: bool = False,
) -> dict[str, object]:
    route = CATALOG_ROUTES.get(catalog_id)
    if not route:
        raise ValueError(f"Unknown catalog id: {catalog_id}")
    pages = max(1, min(int(pages), 25))
    first_urls = route_urls(route)
    scraped_items, errors, fetched_urls = addon_catalog_items(catalog_id, route, pages)
    used_addon_catalog = bool(scraped_items)
    for page in range(1, pages + 1):
        if used_addon_catalog:
            break
        if not fallback_to_site:
            break
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
        items = [item for item in items if search_matches_item(item, search)]
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
    if playable_only:
        items = filter_playable_items(items)
    items.sort(key=lambda item: (item.kind != "series", item.name, item.source))
    return {
        "catalog": catalog_id,
        "catalog_name": route.name,
        "source": route.provider,
        "urls": fetched_urls,
        "count": len(items),
        "playable_only": playable_only,
        "stats": media_stats(items),
        "errors": errors,
        "items": [item.to_dict() for item in items],
    }


def scrape_catalog(
    catalog_id: str,
    pages: int = 1,
    search: str = "",
    fetch_details: bool = False,
    playable_only: bool = False,
    source_filter: str = "all",
    workers: object | None = None,
) -> dict[str, object]:
    key = catalog_cache_key(
        catalog_id,
        pages=pages,
        search=search,
        fetch_details=fetch_details,
        playable_only=playable_only,
        source_filter=source_filter,
        workers=workers,
    )
    cached = cached_catalog_result(key)
    if cached is not None:
        return cached

    catalog_id, pages, search, fetch_details, playable_only, source_filter, worker_count = key
    if catalog_id in CATALOG_GROUPS:
        result = scrape_catalog_group(
            catalog_id,
            pages=pages,
            search=search,
            fetch_details=fetch_details,
            playable_only=playable_only,
            source_filter=source_filter,
            workers=workers,
        )
    else:
        route = CATALOG_ROUTES.get(catalog_id)
        if route and not catalog_matches_source_filter(catalog_id, source_filter):
            result = {
                "catalog": catalog_id,
                "catalog_name": route.name,
                "source": route.provider,
                "source_filter": source_filter,
                "urls": [],
                "count": 0,
                "playable_only": playable_only,
                "performance": performance_info(worker_count, worker_count),
                "stats": media_stats([]),
                "errors": [],
                "items": [],
            }
        else:
            result = scrape_single_catalog(
                catalog_id,
                pages=pages,
                search=search,
                fetch_details=fetch_details,
                playable_only=playable_only,
            )
            result["source_filter"] = source_filter
            result["performance"] = performance_info(worker_count, worker_request_value(workers), task_count=1)
    return store_catalog_result(key, result)


INDEX_HTML = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ArabCity Cinema</title>
  <script src="https://unpkg.com/lucide@latest"></script>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg:#070912;
      --bg-soft:#101321;
      --panel:rgba(18,21,36,.72);
      --panel-solid:#121524;
      --line:rgba(255,255,255,.09);
      --line-strong:rgba(255,255,255,.16);
      --ink:#f8fafc;
      --muted:#a6adbb;
      --faint:#6f7788;
      --brand:#7c3aed;
      --brand-2:#16b8a6;
      --gold:#f6b23c;
      --bad:#fb7185;
      --glow:rgba(124,58,237,.34);
      --accent:linear-gradient(135deg,#4f46e5 0%,#16b8a6 100%);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Tahoma, Arial, sans-serif;
      background:
        radial-gradient(circle at 78% 8%, rgba(79,70,229,.26), transparent 32%),
        radial-gradient(circle at 14% 18%, rgba(22,184,166,.16), transparent 28%),
        linear-gradient(180deg,#070912 0%,#0b0d17 46%,#080a12 100%);
      color: var(--ink);
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image: linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
      background-size: 52px 52px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,.75), transparent 80%);
    }
    a { color: inherit; text-decoration: none; }
    button, input, select { font: inherit; }
    svg { width: 18px; height: 18px; flex: 0 0 auto; }
    .navbar {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      min-height: 76px;
      padding: 0 clamp(14px,4vw,54px);
      background: rgba(7,9,18,.78);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(18px);
    }
    .brand {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-size: 1.35rem;
      font-weight: 800;
      letter-spacing: 0;
      white-space: nowrap;
    }
    .brand-mark {
      width: 38px;
      height: 38px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--accent);
      box-shadow: 0 12px 30px var(--glow);
    }
    .brand-mark svg { width: 21px; height: 21px; }
    .nav-pills {
      display: flex;
      gap: 8px;
      align-items: center;
      color: var(--muted);
      font-size: .92rem;
    }
    .nav-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 36px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,.035);
    }
    main { width: min(1440px,100%); margin: 0 auto; padding: 18px clamp(12px,3vw,32px) 42px; }
    .hero {
      position: relative;
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0,1fr) minmax(360px,.58fr);
      align-items: stretch;
      gap: 22px;
      overflow: hidden;
      border-bottom: 1px solid var(--line);
      padding: 22px 0 24px;
    }
    .hero::after {
      content: "";
      position: absolute;
      inset: 6px 0 auto;
      height: 220px;
      border-radius: 8px;
      background:
        linear-gradient(to top, rgba(7,9,18,.98), rgba(7,9,18,.52), rgba(7,9,18,.18)),
        url("https://h.top4top.io/p_3660ot8jj1.png") center/cover;
      opacity: .46;
      filter: saturate(1.08);
      z-index: -1;
    }
    .hero-content { min-width: 0; display: grid; align-content: center; }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 32px;
      padding: 0 12px;
      border-radius: 999px;
      background: rgba(22,184,166,.13);
      border: 1px solid rgba(22,184,166,.24);
      color: #85f4e8;
      font-size: .86rem;
      font-weight: 700;
      margin-bottom: 16px;
    }
    h1 { margin: 0; max-width: 760px; font-size: clamp(28px,3.8vw,46px); line-height: 1.12; letter-spacing: 0; }
    .hero p { margin: 14px 0 0; max-width: 720px; color: var(--muted); font-size: 1rem; line-height: 1.8; }
    .control-panel {
      display: grid;
      grid-template-columns: minmax(0,1fr) 118px 118px;
      gap: 12px;
      align-items: end;
      align-self: center;
      margin-top: 0;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(13,16,29,.78);
      backdrop-filter: blur(16px);
      box-shadow: 0 20px 46px rgba(0,0,0,.26);
    }
    .control-panel label:first-child,
    .control-panel .playable-toggle,
    .control-panel .search-field,
    .control-panel .primary-button { grid-column: 1 / -1; }
    label { display: grid; gap: 7px; color: var(--muted); font-size: .82rem; font-weight: 700; }
    select, input {
      min-height: 44px;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 12px;
      background: rgba(255,255,255,.055);
      color: var(--ink);
    }
    select:focus, input:focus { border-color: rgba(22,184,166,.72); box-shadow: 0 0 0 3px rgba(22,184,166,.12); }
    select option { background: #121524; color: var(--ink); }
    .toggle {
      min-height: 44px;
      display: flex;
      align-items: center;
      gap: 9px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,.035);
      color: var(--ink);
    }
    .toggle input { width: 18px; min-height: auto; accent-color: var(--brand-2); }
    .primary-button, .episodes-button, .watch-now, .player-controls button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      min-height: 44px;
      border: 0;
      border-radius: 8px;
      padding: 0 14px;
      background: var(--accent);
      color: white;
      cursor: pointer;
      font-weight: 800;
      box-shadow: 0 12px 28px rgba(79,70,229,.22);
      transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease, background .22s ease;
    }
    .primary-button:hover, .episodes-button:hover, .watch-now:hover { transform: translateY(-2px); box-shadow: 0 16px 32px rgba(22,184,166,.22); }
    .results-section { min-height: 520px; }
    .status-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin: 28px 0 18px;
    }
    .section-title {
      margin: 0;
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 1.35rem;
      font-weight: 800;
    }
    .section-title::before {
      content: "";
      width: 5px;
      height: 24px;
      border-radius: 99px;
      background: var(--accent);
      box-shadow: 0 0 18px var(--glow);
    }
    .status {
      min-height: 36px;
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,.035);
      color: var(--muted);
      font-size: .9rem;
      text-align: left;
    }
    .status.error { color: #fecdd3; border-color: rgba(251,113,133,.4); background: rgba(251,113,133,.1); }
    .result-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: -6px 0 16px;
    }
    .result-tab {
      min-height: 36px;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,.04);
      color: var(--muted);
      font-weight: 900;
      cursor: pointer;
      transition: background .2s ease, border-color .2s ease, color .2s ease, transform .2s ease;
    }
    .result-tab:hover { transform: translateY(-1px); border-color: var(--line-strong); color: var(--ink); }
    .result-tab.is-active { color: #99f6e4; border-color: rgba(22,184,166,.44); background: rgba(22,184,166,.11); }
    .result-tab small { color: var(--faint); font-size: .75rem; font-weight: 900; }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0,1fr));
      gap: 10px;
      margin: -4px 0 18px;
    }
    .stat-card {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 11px 12px;
      background: rgba(255,255,255,.035);
    }
    .stat-card strong { display: block; color: var(--ink); font-size: 1.24rem; line-height: 1.1; }
    .stat-card span { display: block; margin-top: 4px; color: var(--muted); font-size: .78rem; font-weight: 800; }
    .watch-layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(340px, 420px);
      gap: 18px;
      align-items: start;
    }
    .results-column { min-width: 0; }
    .media-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
      gap: 16px;
      align-items: start;
    }
    .load-more {
      width: 100%;
      min-height: 48px;
      margin-top: 16px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 9px;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      background: rgba(255,255,255,.055);
      color: var(--ink);
      font-weight: 900;
      cursor: pointer;
      transition: transform .2s ease, border-color .2s ease, background .2s ease;
    }
    .load-more:hover { transform: translateY(-2px); border-color: rgba(22,184,166,.5); background: rgba(22,184,166,.1); }
    .load-more[hidden] { display: none; }
    .load-more small { color: var(--muted); font-size: .78rem; font-weight: 800; }
    .media-card {
      position: relative;
      overflow: hidden;
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(20,23,39,.62);
      box-shadow: 0 18px 38px rgba(0,0,0,.24);
      transition: transform .24s ease, border-color .24s ease, box-shadow .24s ease;
    }
    .media-card:hover { transform: translateY(-6px); border-color: var(--line-strong); box-shadow: 0 24px 54px rgba(0,0,0,.34); }
    .poster-wrap { position: relative; aspect-ratio: 2 / 3; background: #151827; overflow: hidden; }
    .poster { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform .32s ease; }
    .media-card:hover .poster { transform: scale(1.05); }
    .poster-missing {
      width: 100%;
      height: 100%;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, rgba(79,70,229,.18), rgba(22,184,166,.13));
      color: var(--faint);
      font-weight: 800;
    }
    .poster-shade { position: absolute; inset: auto 0 0; height: 44%; background: linear-gradient(to top, rgba(7,9,18,.94), transparent); pointer-events: none; }
    .card-badge, .type-badge {
      position: absolute;
      top: 10px;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      min-height: 26px;
      padding: 0 8px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,.12);
      background: rgba(7,9,18,.68);
      color: var(--gold);
      font-size: .76rem;
      font-weight: 800;
      backdrop-filter: blur(10px);
    }
    .card-badge { right: 10px; }
    .type-badge { left: 10px; color: white; background: rgba(79,70,229,.72); }
    .card-info { padding: 13px; display: grid; gap: 9px; }
    .card-title {
      margin: 0;
      min-height: 46px;
      color: var(--ink);
      font-size: .98rem;
      line-height: 1.45;
      font-weight: 800;
      overflow-wrap: anywhere;
    }
    .raw { color: var(--muted); font-size: .78rem; line-height: 1.55; min-height: 18px; overflow-wrap: anywhere; }
    .card-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      color: var(--faint);
      font-size: .78rem;
    }
    .pill { display: inline-flex; align-items: center; gap: 5px; color: #a7f3d0; font-weight: 800; }
    .actions { display: grid; gap: 8px; margin-top: 2px; }
    .episodes-button {
      width: 100%;
      min-height: 38px;
      background: rgba(255,255,255,.065);
      border: 1px solid var(--line);
      box-shadow: none;
    }
    .direct-chip {
      min-height: 38px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--muted);
      background: rgba(255,255,255,.04);
      font-size: .82rem;
      font-weight: 800;
    }
    .direct-chip.is-direct { color: #99f6e4; border-color: rgba(22,184,166,.28); background: rgba(22,184,166,.08); }
    .direct-chip.is-uncertain { color: #fde68a; border-color: rgba(246,178,60,.34); background: rgba(246,178,60,.09); }
    .direct-chip.is-unavailable { color: #fecdd3; border-color: rgba(251,113,133,.34); background: rgba(251,113,133,.09); }
    .episode-list { display: grid; gap: 7px; max-height: 210px; overflow: auto; padding-top: 2px; }
    .episode-link {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-height: 36px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,.045);
      color: var(--ink);
      font-size: .82rem;
      font-weight: 700;
    }
    .episode-link:hover { border-color: rgba(22,184,166,.42); color: #99f6e4; }
    .episode-link small { color: var(--faint); font-size: .72rem; font-weight: 800; }
    .episode-link.is-direct small { color: #99f6e4; }
    .inline-error { color: #fecdd3; font-size: .82rem; line-height: 1.6; }
    .empty-state {
      grid-column: 1 / -1;
      min-height: 210px;
      display: grid;
      place-items: center;
      text-align: center;
      border: 1px dashed var(--line-strong);
      border-radius: 8px;
      color: var(--muted);
      background: rgba(255,255,255,.025);
      padding: 24px;
    }
    .skeleton-card {
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(20,23,39,.52);
    }
    .skeleton-poster, .skeleton-line {
      background: linear-gradient(90deg, rgba(255,255,255,.04), rgba(255,255,255,.1), rgba(255,255,255,.04));
      background-size: 220% 100%;
      animation: shimmer 1.25s infinite linear;
    }
    .skeleton-poster { aspect-ratio: 2 / 3; }
    .skeleton-body { display: grid; gap: 9px; padding: 13px; }
    .skeleton-line { height: 13px; border-radius: 8px; }
    .skeleton-line.short { width: 58%; }
    @keyframes shimmer { to { background-position: -220% 0; } }
    .player-panel {
      display: block;
      position: sticky;
      top: 96px;
      z-index: 18;
      min-width: 0;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      background: rgba(3,5,12,.94);
      box-shadow: 0 22px 58px rgba(0,0,0,.36);
      overflow: hidden;
      backdrop-filter: blur(18px);
    }
    .player-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px; color: white; border-bottom: 1px solid var(--line); }
    .player-heading { min-width: 0; display: grid; gap: 6px; }
    .player-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 800; }
    .player-meta { display: flex; flex-wrap: wrap; gap: 6px; color: var(--muted); font-size: .76rem; font-weight: 800; }
    .player-meta span { min-height: 24px; display: inline-flex; align-items: center; padding: 0 8px; border: 1px solid var(--line); border-radius: 999px; background: rgba(255,255,255,.045); }
    .player-controls { display: flex; gap: 8px; flex: 0 0 auto; }
    .player-controls button { min-height: 36px; background: rgba(255,255,255,.075); border: 1px solid var(--line); box-shadow: none; }
    .player-controls button:hover { background: var(--accent); }
    .player-body { min-height: 260px; display: grid; background: #000; }
    .player-state {
      min-height: 260px;
      display: grid;
      place-items: center;
      padding: 24px;
      text-align: center;
      color: var(--muted);
      background:
        linear-gradient(135deg, rgba(79,70,229,.16), rgba(22,184,166,.08)),
        #050710;
    }
    .player-state strong { display: block; margin-bottom: 8px; color: var(--ink); font-size: 1rem; }
    .player-state p { margin: 0; line-height: 1.7; }
    .player-state.error strong { color: #fecdd3; }
    .player-state svg { width: 34px; height: 34px; margin-bottom: 12px; color: #99f6e4; }
    .player-video { display: block; width: 100%; aspect-ratio: 16 / 9; max-height: min(62vh, 640px); background: #000; }
    .player-video[hidden], .player-state[hidden] { display: none; }
    footer { margin-top: 44px; padding: 24px 0 0; border-top: 1px solid var(--line); color: var(--faint); text-align: center; font-size: .86rem; }
    @media (max-width: 960px) {
      .nav-pills { display: none; }
      .hero { grid-template-columns: 1fr; }
      .control-panel { grid-template-columns: 1fr 1fr; }
      .control-panel .primary-button { grid-column: 1 / -1; }
      .watch-layout { grid-template-columns: 1fr; }
      .player-panel { position: sticky; top: auto; bottom: 0; order: -1; }
    }
    @media (max-width: 620px) {
      .navbar { min-height: 66px; }
      .brand { font-size: 1.08rem; }
      .brand-mark { width: 34px; height: 34px; }
      main { padding-inline: 12px; }
      .hero { min-height: auto; padding-top: 20px; }
      .hero::after { height: 230px; }
      .control-panel { grid-template-columns: 1fr; }
      .status-row { align-items: stretch; flex-direction: column; }
      .status { justify-content: center; text-align: center; }
      .stats-grid { grid-template-columns: repeat(2, minmax(0,1fr)); }
      .media-grid { grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
      .card-info { padding: 10px; }
      .card-title { font-size: .88rem; min-height: 42px; }
      .player-body, .player-state { min-height: 210px; }
      .player-video { max-height: 56vh; }
    }
  </style>
</head>
<body>
  <svg style="width:0;height:0;position:absolute;" aria-hidden="true" focusable="false">
    <linearGradient id="brand-gradient-id" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#4f46e5"></stop>
      <stop offset="100%" stop-color="#16b8a6"></stop>
    </linearGradient>
  </svg>
  <header class="navbar">
    <a class="brand" href="/">
      <span class="brand-mark"><i data-lucide="clapperboard"></i></span>
      <span>ArabCity Cinema</span>
    </a>
    <nav class="nav-pills" aria-label="أقسام الواجهة">
      <span class="nav-pill"><i data-lucide="film"></i> أفلام</span>
      <span class="nav-pill"><i data-lucide="tv"></i> مسلسلات</span>
      <span class="nav-pill"><i data-lucide="play-circle"></i> مشاهدة</span>
    </nav>
  </header>
  <main>
    <section class="hero">
      <div class="hero-content">
        <div class="eyebrow"><i data-lucide="sparkles"></i> المكتبة تُجهّز تلقائيا</div>
        <h1>كل الكتالوج أمامك مباشرة، نظيف وجاهز للمشاهدة.</h1>
        <p>تفتح الصفحة فتبدأ المكتبة بالتحميل وحدها. يمكنك فقط تغيير الكتالوج أو البحث لاحقا، بينما تبقى مساحة العرض مخصصة للبوسترات والحلقات والمشغل.</p>
        <form id="scrapeForm" class="control-panel">
          <label>الكتالوج
            <select id="catalog"></select>
          </label>
          <label>المصادر
            <select id="sourceFilter">
              <option value="all">الكل</option>
              <option value="akwam">Akwam فقط</option>
              <option value="alooytv">AlooyTV فقط</option>
            </select>
          </label>
          <label>عدد الصفحات
            <input id="pages" type="number" min="1" max="25" value="1">
          </label>
          <label>التوازي
            <input id="workers" type="number" min="1" max="8" value="6">
          </label>
          <label class="toggle">
            <input id="details" type="checkbox">
            تفاصيل أعمق
          </label>
          <label class="toggle playable-toggle">
            <input id="playableOnly" type="checkbox">
            جاهز للتشغيل فقط
          </label>
          <label class="search-field">بحث داخل النتائج
            <input id="search" type="search" placeholder="اختياري">
          </label>
          <button class="primary-button" type="submit"><i data-lucide="refresh-cw"></i><span>تحديث المكتبة</span></button>
        </form>
      </div>
    </section>
    <section class="results-section">
      <div class="status-row">
        <h2 class="section-title">النتائج</h2>
        <div id="status" class="status">جاهز.</div>
      </div>
      <div id="resultTabs" class="result-tabs" aria-label="تصفية النتائج">
        <button class="result-tab is-active" type="button" data-tab="all">الكل</button>
        <button class="result-tab" type="button" data-tab="movies">أفلام</button>
        <button class="result-tab" type="button" data-tab="series">مسلسلات</button>
        <button class="result-tab" type="button" data-tab="ready">جاهز للتشغيل</button>
      </div>
      <div id="statsGrid" class="stats-grid" aria-live="polite"></div>
      <div class="watch-layout">
        <div class="results-column">
          <div id="rows" class="media-grid"></div>
          <button id="loadMore" class="load-more" type="button" hidden><i data-lucide="chevrons-down"></i><span>عرض المزيد</span></button>
        </div>
        <section id="playerPanel" class="player-panel" aria-live="polite">
          <div class="player-bar">
            <div class="player-heading">
              <div id="playerTitle" class="player-title">المشغل المباشر</div>
              <div id="playerMeta" class="player-meta" aria-live="polite"></div>
            </div>
            <div class="player-controls">
              <button id="playerClose" type="button"><i data-lucide="x"></i><span>إغلاق</span></button>
            </div>
          </div>
          <div class="player-body">
            <div id="playerState" class="player-state">
              <div><i data-lucide="play-circle"></i><strong>اختر حلقة أو فيلما</strong><p>أي رابط قابل للتشغيل سيعمل هنا مباشرة داخل الصفحة.</p></div>
            </div>
            <video id="episodeVideo" class="player-video" controls playsinline hidden></video>
          </div>
        </section>
      </div>
    </section>
    <footer>ArabCity Cinema - واجهة مشاهدة محلية مستوحاة من الواجهات السينمائية الحديثة.</footer>
  </main>
  <script>
    const catalog = document.querySelector("#catalog");
    const rows = document.querySelector("#rows");
    const loadMoreButton = document.querySelector("#loadMore");
    const resultTabs = document.querySelector("#resultTabs");
    const statsGrid = document.querySelector("#statsGrid");
    const statusBox = document.querySelector("#status");
    const playerPanel = document.querySelector("#playerPanel");
    const episodeVideo = document.querySelector("#episodeVideo");
    const playerState = document.querySelector("#playerState");
    const playerTitle = document.querySelector("#playerTitle");
    const playerMeta = document.querySelector("#playerMeta");
    const playerClose = document.querySelector("#playerClose");
    let autoLoadController = null;
    let hlsInstance = null;
    let searchTimer = null;
    let renderBatch = 0;
    let extractedItems = [];
    let filteredItems = [];
    let visibleItemCount = 0;
    let activeResultTab = "all";
    let currentPlayerContext = {};
    const RESULTS_PAGE_SIZE = 40;
    const HLS_NETWORK_RETRY_LIMIT = 3;
    const episodeMetaCache = new Map();
    const episodeMetaRequests = new Map();
    const playerCheckCache = new Map();
    const playerCheckRequests = new Map();

    function refreshIcons() {
      if (window.lucide) window.lucide.createIcons();
    }

    function setStatus(text, isError = false) {
      statusBox.textContent = text;
      statusBox.className = isError ? "status error" : "status";
    }

    function renderStats(stats = {}) {
      const values = [
        ["الإجمالي", stats.total || 0],
        ["الأفلام", stats.movies || 0],
        ["المسلسلات", stats.series || 0],
        ["لديها حلقات", stats.with_episodes || 0],
        ["جاهزة للتشغيل", stats.playable || 0],
      ];
      statsGrid.innerHTML = values.map(([label, value]) => `<div class="stat-card"><strong>${value}</strong><span>${label}</span></div>`).join("");
    }

    function renderLoadingCards(count = 12) {
      renderStats();
      extractedItems = [];
      filteredItems = [];
      visibleItemCount = 0;
      loadMoreButton.hidden = true;
      rows.innerHTML = Array.from({ length: count }, () => `
        <div class="skeleton-card">
          <div class="skeleton-poster"></div>
          <div class="skeleton-body">
            <div class="skeleton-line"></div>
            <div class="skeleton-line short"></div>
            <div class="skeleton-line"></div>
          </div>
        </div>
      `).join("");
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
      refreshIcons();
      const defaultOption = catalog.querySelector('option[value="arabcity-complete-library"]');
      if (defaultOption) catalog.value = defaultOption.value;
      await loadItems({ initial: true });
    }

    async function clearEpisodeCaches({ server = false } = {}) {
      episodeMetaCache.clear();
      episodeMetaRequests.clear();
      playerCheckCache.clear();
      playerCheckRequests.clear();
      if (server) {
        try {
          await fetch("/api/episode-cache/clear");
        } catch (_error) {}
      }
    }

    async function loadItems({ initial = false } = {}) {
      if (autoLoadController) autoLoadController.abort();
      autoLoadController = new AbortController();
      renderLoadingCards(initial ? 14 : 10);
      const playableOnly = document.querySelector("#playableOnly").checked;
      setStatus(playableOnly ? "جاري فحص روابط التشغيل المباشر..." : (initial ? "جاري تجهيز المكتبة تلقائيا..." : "جاري تحديث المكتبة..."));
      const params = new URLSearchParams({
        catalog: catalog.value,
        source_filter: document.querySelector("#sourceFilter").value || "all",
        pages: document.querySelector("#pages").value || "1",
        workers: document.querySelector("#workers").value || "6",
        search: document.querySelector("#search").value || "",
        details: document.querySelector("#details").checked ? "1" : "0",
        playable_only: playableOnly ? "1" : "0",
      });
      try {
        const response = await fetch(`/api/scrape?${params}`, { signal: autoLoadController.signal });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "تعذر تحميل المكتبة");
        renderStats(data.stats || { total: data.count || 0 });
        renderItems(data.items);
        const suffix = data.errors.length ? ` مع ${data.errors.length} أخطاء` : "";
        const stats = data.stats || {};
        const detail = `(${stats.movies || 0} فيلم، ${stats.series || 0} مسلسل)`;
        const prefix = data.playable_only ? "جاهز للتشغيل فقط" : "المكتبة جاهزة";
        const performance = data.performance && data.performance.workers ? `، توازي ${data.performance.workers}` : "";
        setStatus(`${prefix}: ${data.count} نتيجة ${detail} من ${data.catalog_name}${performance}${suffix}.`);
      } catch (error) {
        if (error.name === "AbortError") return;
        rows.innerHTML = `<div class="empty-state"><div><i data-lucide="wifi-off"></i><h3>تعذر تجهيز المكتبة</h3><p>${escapeHtml(error.message)}</p></div></div>`;
        refreshIcons();
        setStatus(error.message, true);
      }
    }

    function renderItems(items) {
      extractedItems = Array.isArray(items) ? items : [];
      applyResultTab(activeResultTab, { resetVisible: true });
    }

    function itemPlayerStatus(item) {
      const cached = playerCheckCache.get(playerCheckKey(item));
      if (cached && cached.status) return cached.status;
      return playerStatusFromItem(item);
    }

    function itemMatchesResultTab(item, tab = activeResultTab) {
      if (tab === "movies") return item.kind === "movie";
      if (tab === "series") return item.kind === "series";
      if (tab === "ready") return item.playable || itemPlayerStatus(item) === "direct";
      return true;
    }

    function applyResultTab(tab = "all", { resetVisible = true } = {}) {
      activeResultTab = tab;
      filteredItems = extractedItems.filter(item => itemMatchesResultTab(item, activeResultTab));
      if (resetVisible) {
        visibleItemCount = Math.min(RESULTS_PAGE_SIZE, filteredItems.length);
      } else {
        visibleItemCount = Math.min(Math.max(visibleItemCount, Math.min(RESULTS_PAGE_SIZE, filteredItems.length)), filteredItems.length);
      }
      updateResultTabs();
      renderVisibleItems();
    }

    function tabCount(tab) {
      return extractedItems.filter(item => itemMatchesResultTab(item, tab)).length;
    }

    function updateResultTabs() {
      for (const button of resultTabs.querySelectorAll(".result-tab")) {
        const tab = button.dataset.tab || "all";
        button.classList.toggle("is-active", tab === activeResultTab);
        const label = button.dataset.label || button.textContent.trim().replace(/\\s+\\d+$/, "");
        button.dataset.label = label;
        button.innerHTML = `${escapeHtml(label)} <small>${tabCount(tab)}</small>`;
      }
    }

    function updateLoadMoreButton() {
      const remaining = Math.max(0, filteredItems.length - visibleItemCount);
      loadMoreButton.hidden = remaining <= 0;
      if (remaining > 0) {
        const nextCount = Math.min(RESULTS_PAGE_SIZE, remaining);
        loadMoreButton.innerHTML = `<i data-lucide="chevrons-down"></i><span>عرض المزيد</span><small>${nextCount} من ${remaining}</small>`;
      }
    }

    function renderVisibleItems() {
      renderBatch += 1;
      const batch = renderBatch;
      rows.innerHTML = "";
      if (!filteredItems.length) {
        const message = extractedItems.length ? "لا توجد نتائج في هذا التبويب." : "جرّب كتالوجا آخر أو غيّر عبارة البحث.";
        rows.innerHTML = `<div class="empty-state"><div><i data-lucide="search-x"></i><h3>لا توجد نتائج</h3><p>${message}</p></div></div>`;
        loadMoreButton.hidden = true;
        refreshIcons();
        return;
      }
      const visibleItems = filteredItems.slice(0, visibleItemCount);
      for (const item of visibleItems) {
        const card = document.createElement("article");
        card.className = "media-card";
        const raw = item.raw_titles && item.raw_titles.length ? `<div class="raw">${escapeHtml(item.raw_titles[0])}</div>` : `<div class="raw">&nbsp;</div>`;
        const kindLabel = item.kind === "series" ? "مسلسل" : item.kind === "movie" ? "فيلم" : "مختلط";
        const countLabel = episodeCountLabel(item);
        card.innerHTML = `
          <div class="poster-wrap">
            ${posterMarkup(item)}
            <div class="poster-shade"></div>
            <span class="card-badge"><i data-lucide="star"></i>${escapeHtml(item.source)}</span>
            <span class="type-badge">${kindLabel}</span>
          </div>
          <div class="card-info">
            <h3 class="card-title">${escapeHtml(item.name)}</h3>
            ${raw}
            <div class="card-meta">
              <span class="pill"><i data-lucide="layers"></i>${kindLabel}</span>
              <span class="episode-count" data-url="${escapeHtml(item.url)}" data-source="${escapeHtml(item.source)}" data-name="${escapeHtml(item.name)}">${countLabel}</span>
            </div>
            ${actionsMarkup(item)}
          </div>
        `;
        rows.appendChild(card);
      }
      updateLoadMoreButton();
      refreshIcons();
      prefetchPlayerChecks(visibleItems, batch);
      prefetchSeriesEpisodeMeta(visibleItems, batch);
      autoloadInitialEpisodeLists(visibleItems, batch);
    }

    function episodeCountLabel(item) {
      if (item.kind !== "series") return "فيلم";
      if (item.episode_count) return `${item.episode_count} حلقة`;
      return "قيد فحص الحلقات";
    }

    function playerStatusFromItem(item) {
      if (item.playable_checked && item.playable) return "direct";
      if (item.playable_checked) return "unavailable";
      return "uncertain";
    }

    function playerStatusLabel(status) {
      if (status === "direct") return "مباشر";
      if (status === "unavailable") return "غير متاح";
      return "غير مؤكد";
    }

    function playerStatusIcon(status) {
      if (status === "direct") return "badge-check";
      if (status === "unavailable") return "circle-x";
      return "circle-help";
    }

    function playerCheckKey(item) {
      return `${item.url || ""}|${item.kind || "mixed"}|${item.source || "akwam"}|${item.name || ""}`;
    }

    function availabilityBadgeMarkup(item) {
      const status = playerStatusFromItem(item);
      return `<span class="direct-chip is-${status}" data-url="${escapeHtml(item.url)}" data-kind="${escapeHtml(item.kind)}" data-source="${escapeHtml(item.source)}" data-name="${escapeHtml(item.name)}"><i data-lucide="${playerStatusIcon(status)}"></i><span>${playerStatusLabel(status)}</span></span>`;
    }

    function actionsMarkup(item) {
      const title = escapeHtml(item.name);
      const watchLink = `<a class="watch-now episode-play" href="${escapeHtml(item.url)}" data-title="${title}" data-work-title="${title}" data-source="${escapeHtml(item.source)}" data-kind="${escapeHtml(item.kind)}"><i data-lucide="play"></i><span>تشغيل داخل الصفحة</span></a>`;
      const availabilityBadge = availabilityBadgeMarkup(item);
      if (item.kind !== "series") return `<div class="actions">${watchLink}${availabilityBadge}</div>`;
      return `
        <div class="actions">
          <button class="watch-now episodes-button" type="button" data-url="${escapeHtml(item.url)}" data-source="${escapeHtml(item.source)}" data-name="${escapeHtml(item.name)}"><i data-lucide="list-video"></i><span>الحلقات والمشاهدة</span></button>
          ${availabilityBadge}
          <div class="episode-list"></div>
        </div>
      `;
    }

    function episodeMetaKey(url, source, name) {
      return `${url || ""}|${source || "akwam"}|${name || ""}`;
    }

    function findEpisodeElement(selector, item) {
      return Array.from(rows.querySelectorAll(selector)).find(element =>
        element.dataset.url === item.url &&
        element.dataset.source === item.source &&
        element.dataset.name === item.name
      );
    }

    function findPlayerChip(item) {
      return Array.from(rows.querySelectorAll(".direct-chip")).find(element =>
        element.dataset.url === item.url &&
        element.dataset.kind === item.kind &&
        element.dataset.source === item.source &&
        element.dataset.name === item.name
      );
    }

    function applyPlayerCheck(item, data, batch) {
      if (batch !== renderBatch) return;
      const chip = findPlayerChip(item);
      if (!chip) return;
      const status = data.status || "uncertain";
      chip.className = `direct-chip is-${status}`;
      chip.innerHTML = `<i data-lucide="${playerStatusIcon(status)}"></i><span>${playerStatusLabel(status)}</span>`;
      updateResultTabs();
      refreshIcons();
    }

    async function checkPlayerStatus(item, batch) {
      const key = playerCheckKey(item);
      let data = playerCheckCache.get(key);
      if (!data) {
        let request = playerCheckRequests.get(key);
        if (!request) {
          request = (async () => {
            const params = new URLSearchParams({
              url: item.url,
              kind: item.kind || "mixed",
              source: item.source || "akwam",
              name: item.name || "",
            });
            const response = await fetch(`/api/check-player?${params}`);
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "تعذر فحص التشغيل");
            playerCheckCache.set(key, payload);
            return payload;
          })().finally(() => playerCheckRequests.delete(key));
          playerCheckRequests.set(key, request);
        }
        data = await request;
      }
      applyPlayerCheck(item, data, batch);
      return data;
    }

    async function prefetchPlayerChecks(items, batch) {
      const visibleItems = items.filter(item => item && item.url);
      let index = 0;
      const workerCount = Math.min(5, visibleItems.length);
      const workers = Array.from({ length: workerCount }, async () => {
        while (index < visibleItems.length && batch === renderBatch) {
          const item = visibleItems[index++];
          try {
            await checkPlayerStatus(item, batch);
          } catch (_error) {
            applyPlayerCheck(item, { status: "uncertain" }, batch);
          }
        }
      });
      await Promise.all(workers);
    }

    function isDirectVideoUrl(url) {
      try {
        return /\\.(mp4|m3u8|mpd|webm|ogg|mov)(?:$|[?#])/.test(new URL(url, window.location.href).pathname.toLowerCase());
      } catch (_error) {
        return false;
      }
    }

    function episodeLinksMarkup(episodes, context = {}) {
      const playableEpisodes = (episodes || []).filter(episode => episode.stream_id || isDirectVideoUrl(episode.url));
      if (!playableEpisodes.length) {
        return `<span class="inline-error">لا توجد روابط مشاهدة مباشرة مؤكدة لهذه الحلقات.</span>`;
      }
      return playableEpisodes.map(episode => {
        const label = episode.title || (episode.number ? `Episode ${episode.number}` : "Watch");
        const directClass = episode.stream_id || isDirectVideoUrl(episode.url) ? " is-direct" : "";
        const directLabel = episode.stream_id ? "مباشر" : "فيديو مباشر";
        return `<a class="episode-link episode-play${directClass}" href="${escapeHtml(episode.url)}" data-title="${escapeHtml(label)}" data-work-title="${escapeHtml(context.name || "")}" data-source="${escapeHtml(context.source || "")}" data-kind="series" data-episode-number="${escapeHtml(episode.number || "")}" data-stream-id="${escapeHtml(episode.stream_id || "")}"><span>${escapeHtml(label)}</span><small>${directLabel}</small><i data-lucide="play"></i></a>`;
      }).join("");
    }

    function applyEpisodeMeta(item, data, batch) {
      if (batch !== renderBatch) return;
      const countElement = findEpisodeElement(".episode-count", item);
      const button = findEpisodeElement(".episodes-button", item);
      if (countElement) {
        if (data.count > 0) {
          countElement.textContent = `${data.count} حلقة`;
        } else if (!item.episode_count) {
          countElement.textContent = data.errors && data.errors.length ? "غير مؤكد" : "لا توجد حلقات مؤكدة";
        }
      }
      if (button) {
        button.dataset.episodeChecked = "1";
        button.dataset.episodeCount = String(data.count || 0);
      }
    }

    async function fetchEpisodeMeta(item, batch) {
      const key = episodeMetaKey(item.url, item.source, item.name);
      let data = episodeMetaCache.get(key);
      if (!data) {
        let request = episodeMetaRequests.get(key);
        if (!request) {
          request = (async () => {
            const params = new URLSearchParams({ url: item.url, source: item.source || "akwam", name: item.name || "" });
            const response = await fetch(`/api/episode-meta?${params}`);
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "تعذر فحص الحلقات");
            episodeMetaCache.set(key, payload);
            return payload;
          })().finally(() => episodeMetaRequests.delete(key));
          episodeMetaRequests.set(key, request);
        }
        data = await request;
      }
      applyEpisodeMeta(item, data, batch);
      return data;
    }

    function applyAutoloadedEpisodeList(item, data, batch) {
      if (batch !== renderBatch) return;
      const button = findEpisodeElement(".episodes-button", item);
      if (!button) return;
      const list = button.closest(".actions").querySelector(".episode-list");
      if (!list) return;
      list.innerHTML = episodeLinksMarkup(data.episodes || [], item);
      list.hidden = true;
      button.dataset.loaded = "1";
      button.dataset.autoloaded = "1";
      button.dataset.episodeChecked = "1";
      button.dataset.episodeCount = String(data.count || 0);
      if (data.count > 0) {
        button.innerHTML = `<i data-lucide="list-video"></i><span>الحلقات (${data.count})</span>`;
      }
      refreshIcons();
    }

    async function autoloadInitialEpisodeLists(items, batch) {
      const seriesItems = items.filter(item => item.kind === "series").slice(0, 10);
      let index = 0;
      const workerCount = Math.min(3, seriesItems.length);
      const workers = Array.from({ length: workerCount }, async () => {
        while (index < seriesItems.length && batch === renderBatch) {
          const item = seriesItems[index++];
          try {
            const data = await fetchEpisodeMeta(item, batch);
            applyAutoloadedEpisodeList(item, data, batch);
          } catch (_error) {
            applyAutoloadedEpisodeList(item, { count: 0, episodes: [], errors: ["تعذر تحميل الحلقات"] }, batch);
          }
        }
      });
      await Promise.all(workers);
    }

    async function prefetchSeriesEpisodeMeta(items, batch) {
      const seriesItems = items.filter(item => item.kind === "series");
      let index = 0;
      const workerCount = Math.min(4, seriesItems.length);
      const workers = Array.from({ length: workerCount }, async () => {
        while (index < seriesItems.length && batch === renderBatch) {
          const item = seriesItems[index++];
          try {
            await fetchEpisodeMeta(item, batch);
          } catch (_error) {
            applyEpisodeMeta(item, { count: 0, errors: ["تعذر فحص الحلقات"] }, batch);
          }
        }
      });
      await Promise.all(workers);
    }

    function posterMarkup(item) {
      if (!item.image) return `<div class="poster-missing">N/A</div>`;
      return `<img class="poster" src="${escapeHtml(item.image)}" alt="${escapeHtml(item.name)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('div'), { className: 'poster-missing', textContent: 'N/A' }))">`;
    }

    function escapeHtml(value) {
      return String(value || "").replace(/[&<>"']/g, ch => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[ch]));
    }

    function destroyHls() {
      if (hlsInstance) {
        hlsInstance.destroy();
        hlsInstance = null;
      }
    }

    function playerContextFromLink(link) {
      return {
        title: link.dataset.title || link.textContent || "",
        workTitle: link.dataset.workTitle || link.dataset.title || link.textContent || "",
        episodeNumber: link.dataset.episodeNumber || "",
        source: link.dataset.source || "",
        kind: link.dataset.kind || "",
      };
    }

    function updatePlayerMeta(context = currentPlayerContext, loadingState = "", replaceContext = false) {
      currentPlayerContext = replaceContext ? { ...context } : { ...currentPlayerContext, ...context };
      const chips = [];
      if (currentPlayerContext.workTitle) chips.push(["العمل", currentPlayerContext.workTitle]);
      if (currentPlayerContext.episodeNumber) chips.push(["الحلقة", currentPlayerContext.episodeNumber]);
      if (currentPlayerContext.source) chips.push(["المصدر", currentPlayerContext.source]);
      if (loadingState) chips.push(["الحالة", loadingState]);
      playerMeta.innerHTML = chips.map(([label, value]) => `<span>${escapeHtml(label)}: ${escapeHtml(value)}</span>`).join("");
    }

    function playbackFailureMessage(reason) {
      const detail = cleanClientText(reason || "");
      return detail ? `فشل تشغيل الرابط داخل الصفحة: ${detail}` : "فشل تشغيل الرابط داخل الصفحة بدون فتح أي موقع خارجي.";
    }

    function cleanClientText(value) {
      return String(value || "").replace(/\\s+/g, " ").trim();
    }

    function showPlayerState(title, message, isError = false, context = currentPlayerContext, loadingState = isError ? "فشل التشغيل" : "بانتظار الاختيار", replaceContext = false) {
      destroyHls();
      playerTitle.textContent = title || "المشغل المباشر";
      updatePlayerMeta(context, loadingState, replaceContext);
      episodeVideo.pause();
      episodeVideo.removeAttribute("src");
      episodeVideo.load();
      episodeVideo.hidden = true;
      playerState.hidden = false;
      playerState.className = isError ? "player-state error" : "player-state";
      playerState.innerHTML = `<div><i data-lucide="${isError ? "circle-alert" : "play-circle"}"></i><strong>${escapeHtml(title || "المشغل المباشر")}</strong><p>${escapeHtml(message)}</p></div>`;
      refreshIcons();
    }

    function isHlsUrl(url) {
      return new URL(url, window.location.href).pathname.toLowerCase().includes(".m3u8");
    }

    function canPlayNativeHls() {
      return Boolean(episodeVideo.canPlayType("application/vnd.apple.mpegurl") || episodeVideo.canPlayType("application/x-mpegURL"));
    }

    function hlsErrorReason(data = {}) {
      const hlsTypes = window.Hls && window.Hls.ErrorTypes ? window.Hls.ErrorTypes : {};
      if (data.type === hlsTypes.NETWORK_ERROR) {
        return "تعذر الاتصال بسيرفر البث أو انقطع تحميل قائمة HLS.";
      }
      if (data.type === hlsTypes.MEDIA_ERROR) {
        return "تعذر فك ترميز البث أو حدث خطأ في مقاطع الفيديو.";
      }
      if (data.details) return `خطأ HLS: ${data.details}`;
      return "تعذر تشغيل رابط HLS داخل المتصفح.";
    }

    function openPlayer(url, title, context = {}) {
      destroyHls();
      playerTitle.textContent = title || "المشغل المباشر";
      updatePlayerMeta(context, "جاري تحميل الفيديو", true);
      playerState.hidden = true;
      episodeVideo.hidden = false;
      episodeVideo.pause();
      episodeVideo.removeAttribute("src");
      episodeVideo.load();
      if (isHlsUrl(url) && window.Hls && window.Hls.isSupported()) {
        let networkRetryCount = 0;
        let mediaRecoverAttempted = false;
        try {
          hlsInstance = new window.Hls({
            enableWorker: true,
            manifestLoadingMaxRetry: 1,
            levelLoadingMaxRetry: 1,
            fragLoadingMaxRetry: 1,
          });
          const currentHls = hlsInstance;
          hlsInstance.on(window.Hls.Events.ERROR, (_event, data) => {
            if (!data || !data.fatal) return;
            const hlsTypes = window.Hls.ErrorTypes || {};
            if (data.type === hlsTypes.NETWORK_ERROR && networkRetryCount < HLS_NETWORK_RETRY_LIMIT) {
              networkRetryCount += 1;
              const retryText = `إعادة محاولة HLS ${networkRetryCount}/${HLS_NETWORK_RETRY_LIMIT}`;
              updatePlayerMeta(context, retryText);
              setStatus(retryText);
              setTimeout(() => {
                if (hlsInstance === currentHls) currentHls.startLoad();
              }, 800 * networkRetryCount);
              return;
            }
            if (data.type === hlsTypes.MEDIA_ERROR && !mediaRecoverAttempted) {
              mediaRecoverAttempted = true;
              updatePlayerMeta(context, "محاولة إصلاح خطأ HLS");
              setStatus("محاولة إصلاح خطأ HLS داخل المشغل...");
              currentHls.recoverMediaError();
              return;
            }
            const message = playbackFailureMessage(hlsErrorReason(data));
            showPlayerState(title, message, true, context);
            setStatus(message, true);
          });
          hlsInstance.loadSource(url);
          hlsInstance.attachMedia(episodeVideo);
        } catch (error) {
          const message = playbackFailureMessage(cleanClientText(error && error.message) || "تعذر تهيئة HLS.js لهذا الرابط.");
          showPlayerState(title, message, true, context);
          setStatus(message, true);
          return;
        }
      } else if (isHlsUrl(url) && !canPlayNativeHls()) {
        const message = playbackFailureMessage("المتصفح لا يدعم تشغيل HLS لهذا الرابط، و HLS.js غير متاح أو غير مدعوم.");
        showPlayerState(title, message, true, context);
        setStatus(message, true);
        return;
      } else {
        episodeVideo.src = url;
        episodeVideo.load();
      }
      const playPromise = episodeVideo.play();
      if (playPromise) {
        playPromise.catch(error => {
          updatePlayerMeta(context, "جاهز، اضغط تشغيل");
          setStatus(cleanClientText(error && error.message) || "الفيديو جاهز، اضغط تشغيل داخل المشغل.");
        });
      }
      playerPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    playerClose.addEventListener("click", () => {
      showPlayerState("المشغل المباشر", "اختر حلقة أو فيلما وسيعمل هنا مباشرة داخل الصفحة.", false, {}, "بانتظار الاختيار", true);
    });

    episodeVideo.addEventListener("loadstart", () => updatePlayerMeta(currentPlayerContext, "جاري تحميل الفيديو"));
    episodeVideo.addEventListener("waiting", () => updatePlayerMeta(currentPlayerContext, "جاري التخزين المؤقت"));
    episodeVideo.addEventListener("canplay", () => updatePlayerMeta(currentPlayerContext, "جاهز للتشغيل"));
    episodeVideo.addEventListener("playing", () => updatePlayerMeta(currentPlayerContext, "يعمل الآن"));

    episodeVideo.addEventListener("error", () => {
      if (!episodeVideo.hidden && episodeVideo.currentSrc) {
        const reason = episodeVideo.error ? `رمز الخطأ ${episodeVideo.error.code}` : "تعذر تحميل الفيديو.";
        const message = playbackFailureMessage(reason);
        showPlayerState(playerTitle.textContent, message, true, currentPlayerContext);
        setStatus(message, true);
      }
    });

    document.querySelector("#scrapeForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      loadItems();
    });

    catalog.addEventListener("change", async () => {
      await clearEpisodeCaches({ server: true });
      loadItems();
    });
    document.querySelector("#pages").addEventListener("change", () => loadItems());
    document.querySelector("#workers").addEventListener("change", () => loadItems());
    document.querySelector("#sourceFilter").addEventListener("change", () => loadItems());
    document.querySelector("#details").addEventListener("change", () => loadItems());
    document.querySelector("#playableOnly").addEventListener("change", () => loadItems());
    document.querySelector("#search").addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadItems(), 420);
    });
    loadMoreButton.addEventListener("click", () => {
      visibleItemCount = Math.min(filteredItems.length, visibleItemCount + RESULTS_PAGE_SIZE);
      renderVisibleItems();
    });
    resultTabs.addEventListener("click", event => {
      const button = event.target.closest(".result-tab");
      if (!button) return;
      applyResultTab(button.dataset.tab || "all", { resetVisible: true });
    });

    rows.addEventListener("click", async (event) => {
      const button = event.target.closest(".episodes-button");
      if (!button) return;
      const list = button.closest(".actions").querySelector(".episode-list");
      if (button.dataset.loaded === "1") {
        list.hidden = !list.hidden;
        return;
      }
      button.disabled = true;
      button.innerHTML = `<i data-lucide="loader"></i><span>...</span>`;
      refreshIcons();
      list.innerHTML = "";
      try {
        const key = episodeMetaKey(button.dataset.url, button.dataset.source, button.dataset.name);
        let data = episodeMetaCache.get(key);
        if (!data) {
          const params = new URLSearchParams({
            url: button.dataset.url,
            source: button.dataset.source || "akwam",
            name: button.dataset.name || "",
          });
          const response = await fetch(`/api/episodes?${params}`);
          data = await response.json();
          if (!response.ok) throw new Error(data.error || "تعذر تحميل الحلقات");
          episodeMetaCache.set(key, data);
        }
        list.innerHTML = episodeLinksMarkup(data.episodes || [], {
          name: button.dataset.name || "",
          source: button.dataset.source || "",
        });
        button.dataset.loaded = "1";
      } catch (error) {
        list.innerHTML = `<span class="inline-error">${escapeHtml(error.message)}</span>`;
      } finally {
        button.disabled = false;
        button.innerHTML = `<i data-lucide="list-video"></i><span>الحلقات والمشاهدة</span>`;
        refreshIcons();
      }
    });

    rows.addEventListener("click", async (event) => {
      const link = event.target.closest(".episode-play");
      if (!link) return;
      event.preventDefault();
      const context = playerContextFromLink(link);
      const title = context.title || link.dataset.title || link.textContent;
      showPlayerState(title, "جاري تجهيز رابط الفيديو المباشر داخل الصفحة.", false, context, "جاري تجهيز الرابط", true);
      setStatus("جاري تجهيز المشغل...");
      try {
        const params = new URLSearchParams({ url: link.href, stream_id: link.dataset.streamId || "" });
        const response = await fetch(`/api/player?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "تعذر تجهيز المشغل");
        const selected = data.selected;
        if (!selected || selected.kind !== "video") throw new Error("لا يوجد رابط فيديو مباشر قابل للتشغيل داخل الصفحة.");
        openPlayer(selected.url, title, context);
        setStatus("تم تشغيل الفيديو داخل الصفحة.");
      } catch (error) {
        const message = playbackFailureMessage(error.message || "تعذر تجهيز المشغل.");
        showPlayerState(title, message, true, context);
        setStatus(message, true);
      }
    });

    renderLoadingCards(14);
    setStatus("جاري تجهيز المكتبة تلقائيا...");
    loadCatalogs().catch(error => {
      rows.innerHTML = `<div class="empty-state"><div><i data-lucide="wifi-off"></i><h3>تعذر تجهيز الكتالوجات</h3><p>${escapeHtml(error.message)}</p></div></div>`;
      refreshIcons();
      setStatus(error.message, true);
    });
    refreshIcons();
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
            self.send_json({"manifest": MANIFEST, "catalogs": available_catalogs()})
            return
        if parsed.path == "/api/scrape":
            params = parse_qs(parsed.query)
            catalog = params.get("catalog", [COMPLETE_LIBRARY_CATALOG_ID])[0]
            pages = int(params.get("pages", ["1"])[0] or "1")
            search = params.get("search", [""])[0]
            details = params.get("details", ["0"])[0] in {"1", "true", "yes"}
            playable_only = params.get("playable_only", ["0"])[0] in {"1", "true", "yes"}
            source_filter = params.get("source_filter", ["all"])[0]
            workers = params.get("workers", [""])[0]
            try:
                self.send_json(
                    scrape_catalog(
                        catalog,
                        pages=pages,
                        search=search,
                        fetch_details=details,
                        playable_only=playable_only,
                        source_filter=source_filter,
                        workers=workers,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - API must return user-readable errors.
                self.send_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/episode-cache/clear":
            clear_episode_caches()
            self.send_json({"cleared": True})
            return
        if parsed.path == "/api/episodes":
            params = parse_qs(parsed.query)
            media_url = params.get("url", [""])[0]
            source = params.get("source", ["akwam"])[0]
            name = params.get("name", [""])[0]
            try:
                self.send_json(scrape_episodes(media_url, source=source, name=name))
            except Exception as exc:  # noqa: BLE001 - API must return user-readable errors.
                self.send_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/episode-meta":
            params = parse_qs(parsed.query)
            media_url = params.get("url", [""])[0]
            source = params.get("source", ["akwam"])[0]
            name = params.get("name", [""])[0]
            try:
                self.send_json(scrape_episode_meta(media_url, source=source, name=name))
            except Exception as exc:  # noqa: BLE001 - API must return user-readable errors.
                self.send_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/check-player":
            params = parse_qs(parsed.query)
            media_url = params.get("url", [""])[0]
            kind = params.get("kind", ["mixed"])[0]
            source = params.get("source", ["akwam"])[0]
            name = params.get("name", [""])[0]
            stream_id = params.get("stream_id", [""])[0]
            try:
                self.send_json(
                    check_player_availability(
                        media_url,
                        kind=kind,
                        source=source,
                        name=name,
                        stream_id=stream_id,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - API must return user-readable errors.
                self.send_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/player":
            params = parse_qs(parsed.query)
            media_url = params.get("url", [""])[0]
            stream_id = params.get("stream_id", [""])[0]
            try:
                self.send_json(scrape_player(media_url, stream_id=stream_id))
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
    scrape_parser.add_argument("--catalog", default=COMPLETE_LIBRARY_CATALOG_ID, choices=sorted(all_catalog_ids()))
    scrape_parser.add_argument("--pages", type=int, default=1)
    scrape_parser.add_argument("--search", default="")
    scrape_parser.add_argument("--details", action="store_true", help="Fetch detail pages to improve episode counts.")
    scrape_parser.add_argument("--playable-only", action="store_true", help="Only keep items with a verified direct video stream.")
    scrape_parser.add_argument("--workers", type=int, default=None, help="Limit parallel catalog and stream checks.")
    scrape_parser.add_argument("--json", action="store_true", help="Print JSON instead of a table.")

    episodes_parser = subparsers.add_parser("episodes", help="Extract episode watch links from a media page.")
    episodes_parser.add_argument("--url", required=True)
    episodes_parser.add_argument("--source", default="akwam")
    episodes_parser.add_argument("--name", default="")
    episodes_parser.add_argument("--json", action="store_true", help="Print JSON instead of a table.")

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
    if args.command == "episodes":
        result = scrape_episodes(args.url, source=args.source, name=args.name)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"{result['count']} episodes")
            for episode in result["episodes"]:
                print(f"{episode['number'] or '-':>4} | {episode['title']} | {episode['url']}")
        return 0
    result = scrape_catalog(
        args.catalog,
        pages=args.pages,
        search=args.search,
        fetch_details=args.details,
        playable_only=args.playable_only,
        workers=args.workers,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_table(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
