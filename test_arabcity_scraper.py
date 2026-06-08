import unittest
from unittest.mock import patch

from arabcity_scraper import (
    COMPLETE_LIBRARY_CATALOG_ID,
    CATALOG_GROUPS,
    CATALOG_ROUTES,
    INDEX_HTML,
    MANIFEST,
    EpisodeLink,
    MediaItem,
    PlayerLink,
    available_catalogs,
    check_player_availability,
    clear_catalog_cache,
    clear_episode_cache,
    clear_episode_caches,
    count_episodes_from_html,
    detect_episode_number,
    direct_video_players,
    extract_episode_links,
    extract_media_items,
    extract_player_links,
    filter_playable_items,
    is_allowed_source_url,
    media_item_from_addon_meta,
    manifest_catalog_ids,
    normalize_media_name,
    search_matches_item,
    player_from_addon_stream,
    request_safe_url,
    scrape_catalog,
    scrape_episodes,
    scrape_episode_meta,
    scrape_player,
    stremio_url,
)


class ArabCityScraperTests(unittest.TestCase):
    def setUp(self):
        clear_catalog_cache()
        clear_episode_caches()

    def test_detect_episode_number_arabic(self):
        self.assertEqual(detect_episode_number("مسلسل المدينة الحلقة 12 مترجمة"), 12)
        self.assertEqual(detect_episode_number("مسلسل المدينة ح 7"), 7)
        self.assertEqual(detect_episode_number("Episode 3"), 3)
        self.assertEqual(detect_episode_number("مسلسل المدينة الحلقة ١٢ مترجمة"), 12)

    def test_normalize_series_name(self):
        self.assertEqual(
            normalize_media_name("مشاهدة مسلسل المدينة البعيدة الموسم الاول الحلقة 3 مترجمة", "series"),
            "المدينة البعيدة",
        )

    def test_search_matches_arabic_without_diacritic_or_space_sensitivity(self):
        item = MediaItem(
            "المدينة البعيدة",
            "series",
            "https://akwam.example/series/far-city",
            "akwam",
            raw_titles=["مشاهدة مُسَلْسَل المدينة   البعيدة الحلقة 3 مترجمة"],
        )
        self.assertTrue(search_matches_item(item, "المدينه البعيده"))
        self.assertTrue(search_matches_item(item, "المدينةالبعيدة"))

    def test_search_matches_kind_source_raw_title_and_description(self):
        item = MediaItem(
            "From",
            "series",
            "https://akwam.example/series/from",
            "akwam",
            description="رعب وغموض في مدينة محاصرة",
            raw_titles=["From الموسم الرابع"],
        )
        self.assertTrue(search_matches_item(item, "مسلسل"))
        self.assertTrue(search_matches_item(item, "akwam"))
        self.assertTrue(search_matches_item(item, "الموسم الرابع"))
        self.assertTrue(search_matches_item(item, "رعب غموض"))
        self.assertFalse(search_matches_item(item, "كوميديا"))

    def test_extract_items_groups_series_episodes(self):
        html = """
        <a href="/s1">مشاهدة مسلسل House of Guinness الموسم الاول الحلقة 8 مترجمة حصرى</a>
        <a href="/s2">مشاهدة مسلسل House of Guinness الموسم الاول الحلقة 7 مترجمة حصرى</a>
        <a href="/m1">مشاهدة فيلم Big Deal 2025 مترجم</a>
        """
        items = extract_media_items(html, "https://example.test/", CATALOG_ROUTES["akoam-recent"])
        by_name = {item.name: item for item in items}
        self.assertEqual(by_name["House of Guinness"].episode_count, 8)
        self.assertEqual(by_name["Big Deal"].kind, "movie")

    def test_extract_modern_series_card_episode_count(self):
        html = """
        <div>8.0 23 WEB-DL</div>
        <a href="/watch">watch</a>
        <span>favorite</span>
        <a href="/series/ghost-lawyer">Ghost Lawyer</a>
        """
        items = extract_media_items(html, "https://example.test/", CATALOG_ROUTES["akoam-series-all"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "Ghost Lawyer")
        self.assertEqual(items[0].episode_count, 23)

    def test_extract_image_from_matching_card_link(self):
        html = """
        <a href="/series/ghost-lawyer"><img src="/placeholder.png" data-src="/posters/ghost.jpg"></a>
        <div>8.0 23 WEB-DL</div>
        <a href="/series/ghost-lawyer">Ghost Lawyer</a>
        """
        items = extract_media_items(html, "https://example.test/", CATALOG_ROUTES["akoam-series-all"])
        self.assertEqual(items[0].image, "https://example.test/posters/ghost.jpg")

    def test_count_episodes_from_detail_links(self):
        detail_html = """
        <a href="/e1">مسلسل المؤسس عثمان الحلقة 1 مترجمة</a>
        <a href="/e12">مسلسل المؤسس عثمان الحلقة 12 مترجمة</a>
        <a href="/e3">مسلسل المؤسس عثمان الحلقة 3 مترجمة</a>
        """
        self.assertEqual(count_episodes_from_html(detail_html), 12)

    def test_extract_episode_links_orders_latest_first(self):
        detail_html = """
        <a href="/series/ghost-lawyer">Ghost Lawyer</a>
        <a href="/media/ghost-lawyer-1.mp4">مسلسل Ghost Lawyer الحلقة 1 مترجمة</a>
        <a href="/media/ghost-lawyer-12.mp4">مسلسل Ghost Lawyer الحلقة 12 مترجمة</a>
        <a href="/media/ghost-lawyer-3.mp4">مسلسل Ghost Lawyer الحلقة 3 مترجمة</a>
        """
        episodes = extract_episode_links(detail_html, "https://ak.sv/series/ghost-lawyer")
        self.assertEqual([episode.number for episode in episodes], [12, 3, 1])
        self.assertEqual(episodes[0].url, "https://ak.sv/media/ghost-lawyer-12.mp4")

    def test_extract_episode_links_orders_arabic_and_english_episode_numbers(self):
        detail_html = """
        <a href="/media/show-episode-3.mp4">Episode 3</a>
        <a href="/media/show-episode-12.mp4">الحلقة 12</a>
        <a href="/media/show-episode-7.mp4">ح 7</a>
        """
        episodes = extract_episode_links(detail_html, "https://ak.sv/series/show")
        self.assertEqual([episode.number for episode in episodes], [12, 7, 3])

    def test_extract_episode_links_rejects_page_only_watch_links(self):
        detail_html = """
        <a href="/watch/show-episode-1">الحلقة 1</a>
        <a href="/media/show-episode-2.mp4">الحلقة 2</a>
        """
        episodes = extract_episode_links(detail_html, "https://ak.sv/series/show")
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0].number, 2)
        self.assertTrue(episodes[0].to_dict()["playable_reference"])

    def test_scrape_episode_meta_counts_and_caches_addon_episodes(self):
        episodes = [
            EpisodeLink("الحلقة 2", "https://akwam.example/watch/from-2", number=2, stream_id="stream-2"),
            EpisodeLink("الحلقة 1", "https://akwam.example/watch/from-1", number=1, stream_id="stream-1"),
        ]
        with patch("arabcity_scraper.addon_episode_links", return_value=episodes) as mocked:
            first = scrape_episode_meta("https://akwam.example/series/from", source="akwam", name="From")
            second = scrape_episode_meta("https://akwam.example/series/from", source="akwam", name="From")

        mocked.assert_called_once_with("https://akwam.example/series/from", source="akwam", name="From")
        self.assertTrue(first["checked"])
        self.assertEqual(first["count"], 2)
        self.assertEqual(second["count"], 2)
        self.assertEqual(first["episodes"][0]["stream_id"], "stream-2")
        self.assertTrue(first["episodes"][0]["playable_reference"])

    def test_scrape_episode_meta_excludes_unplayable_episode_refs(self):
        episodes = [
            EpisodeLink("الحلقة 2", "https://akwam.example/watch/from-2", number=2),
            EpisodeLink("الحلقة 1", "https://akwam.example/media/from-1.mp4", number=1),
        ]
        with patch("arabcity_scraper.addon_episode_links", return_value=episodes):
            result = scrape_episode_meta("https://akwam.example/series/from", source="akwam", name="From")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["episodes"][0]["url"], "https://akwam.example/media/from-1.mp4")
        self.assertTrue(result["episodes"][0]["playable_reference"])

    def test_scrape_episodes_caches_final_links_by_series_url(self):
        detail_html = '<a href="/media/from-1.mp4">الحلقة 1</a>'
        with patch("arabcity_scraper.addon_episode_links", return_value=[]):
            with patch("arabcity_scraper.fetch_html", return_value=detail_html) as mocked_fetch_html:
                first = scrape_episodes("https://akwam.example/series/from", source="akwam", name="From")
                second = scrape_episodes("https://akwam.example/series/from", source="akwam", name="From")
        self.assertEqual(mocked_fetch_html.call_count, 1)
        self.assertEqual(first["episodes"], second["episodes"])
        self.assertEqual(first["count"], 1)

    def test_episode_cache_can_be_cleared(self):
        detail_html = '<a href="/media/from-1.mp4">الحلقة 1</a>'
        with patch("arabcity_scraper.addon_episode_links", return_value=[]):
            with patch("arabcity_scraper.fetch_html", return_value=detail_html) as mocked_fetch_html:
                scrape_episodes("https://akwam.example/series/from", source="akwam", name="From")
                clear_episode_cache()
                scrape_episodes("https://akwam.example/series/from", source="akwam", name="From")
        self.assertEqual(mocked_fetch_html.call_count, 2)

    def test_episode_cache_evicts_oldest_when_limited(self):
        pages = {
            "https://akwam.example/series/one": '<a href="/media/one-1.mp4">الحلقة 1</a>',
            "https://akwam.example/series/two": '<a href="/media/two-1.mp4">الحلقة 1</a>',
        }

        def fake_fetch_html(url):
            return pages[url]

        with patch("arabcity_scraper.EPISODE_CACHE_LIMIT", 1):
            with patch("arabcity_scraper.addon_episode_links", return_value=[]):
                with patch("arabcity_scraper.fetch_html", side_effect=fake_fetch_html) as mocked_fetch_html:
                    scrape_episodes("https://akwam.example/series/one", source="akwam", name="One")
                    scrape_episodes("https://akwam.example/series/two", source="akwam", name="Two")
                    scrape_episodes("https://akwam.example/series/one", source="akwam", name="One")
        self.assertEqual(mocked_fetch_html.call_count, 3)

    def test_scrape_episode_meta_returns_uncertain_on_meta_error(self):
        with patch("arabcity_scraper.addon_episode_links", side_effect=TimeoutError("slow meta")):
            result = scrape_episode_meta("https://akwam.example/series/from", source="akwam", name="From")
        self.assertTrue(result["checked"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["episodes"], [])
        self.assertTrue(result["errors"])

    def test_episode_source_url_accepts_current_public_domains(self):
        self.assertTrue(is_allowed_source_url("https://current-akwam.example/series/from"))
        self.assertFalse(is_allowed_source_url("http://127.0.0.1:8766/series/from"))
        self.assertFalse(is_allowed_source_url("http://localhost:8766/series/from"))

    def test_request_safe_url_quotes_arabic_paths(self):
        safe_url = request_safe_url("https://tv.akwam.tv/series/التربية?name=الحلقة 1")
        self.assertIn("%D8%A7%D9%84%D8%AA%D8%B1%D8%A8%D9%8A%D8%A9", safe_url)
        self.assertIn("name=%D8%A7%D9%84%D8%AD%D9%84%D9%82%D8%A9%201", safe_url)
        safe_url.encode("ascii")

    def test_extract_player_links_prefers_direct_video(self):
        html = """
        <iframe src="/embed/episode-1"></iframe>
        <video><source src="https://cdn.example.test/media/episode-1.mp4"></video>
        """
        players = extract_player_links(html, "https://tv.akwam.tv/watch/episode-1")
        self.assertEqual(players[0].kind, "video")
        self.assertEqual(players[0].url, "https://cdn.example.test/media/episode-1.mp4")
        self.assertEqual(players[1].url, "https://tv.akwam.tv/embed/episode-1")

    def test_direct_video_players_filters_embeds(self):
        players = direct_video_players(
            [
                PlayerLink("https://cdn.example.test/media/episode-1.mp4", "video"),
                PlayerLink("https://tv.akwam.tv/embed/episode-1", "iframe"),
            ]
        )
        self.assertEqual(len(players), 1)
        self.assertEqual(players[0].url, "https://cdn.example.test/media/episode-1.mp4")

    def test_addon_stream_url_is_direct_video_player(self):
        payload = {"streams": [{"url": "https://cdn.example.test/play?id=1", "title": "Main"}]}
        with patch("arabcity_scraper.fetch_json", return_value=payload):
            players = player_from_addon_stream("arabcity:episode:1")
        self.assertEqual(len(players), 1)
        self.assertEqual(players[0].kind, "video")
        self.assertEqual(players[0].url, "https://cdn.example.test/play?id=1")

    def test_scrape_player_rejects_page_only_fallback(self):
        with patch("arabcity_scraper.fetch_html", return_value='<iframe src="/embed/episode-1"></iframe>'):
            with self.assertRaises(ValueError) as context:
                scrape_player("https://tv.akwam.tv/watch/episode-1")
        self.assertIn("رابط فيديو مباشر", str(context.exception))

    def test_scrape_player_accepts_direct_video_url_without_page_fetch(self):
        with patch("arabcity_scraper.fetch_html") as mocked_fetch_html:
            result = scrape_player("https://cdn.example.test/media/episode-1.mp4")
        mocked_fetch_html.assert_not_called()
        self.assertEqual(result["selected"]["kind"], "video")
        self.assertEqual(result["selected"]["url"], "https://cdn.example.test/media/episode-1.mp4")

    def test_check_player_reports_direct_without_fetching_video(self):
        with patch("arabcity_scraper.fetch_html") as mocked_fetch_html:
            result = check_player_availability("https://cdn.example.test/media/episode-1.mp4", kind="movie")
        mocked_fetch_html.assert_not_called()
        self.assertEqual(result["status"], "direct")
        self.assertTrue(result["playable"])
        self.assertEqual(result["streams"], 1)

    def test_check_player_reports_movie_stream_statuses(self):
        with patch("arabcity_scraper.player_from_addon_stream", return_value=[PlayerLink("https://cdn.example.test/v.mp4", "video")]):
            direct = check_player_availability("https://akwam.example/movie/ready", kind="movie", source="akwam", name="Ready")
        with patch("arabcity_scraper.player_from_addon_stream", return_value=[]):
            unavailable = check_player_availability("https://akwam.example/movie/dead", kind="movie", source="akwam", name="Dead")
        with patch("arabcity_scraper.player_from_addon_stream", side_effect=RuntimeError("slow stream")):
            uncertain = check_player_availability("https://akwam.example/movie/slow", kind="movie", source="akwam", name="Slow")

        self.assertEqual(direct["status"], "direct")
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(uncertain["status"], "uncertain")
        self.assertTrue(uncertain["errors"])

    def test_check_player_reports_series_episode_stream(self):
        episodes = [EpisodeLink("الحلقة 1", "https://akwam.example/watch/from-1", number=1, stream_id="stream-1")]
        with patch("arabcity_scraper.addon_episode_links", return_value=episodes):
            with patch("arabcity_scraper.player_from_addon_stream", return_value=[PlayerLink("https://cdn.example.test/from-1.m3u8", "video")]):
                result = check_player_availability("https://akwam.example/series/from", kind="series", source="akwam", name="From")
        self.assertEqual(result["status"], "direct")
        self.assertEqual(result["streams"], 1)

    def test_filter_playable_items_keeps_verified_direct_streams(self):
        items = [
            MediaItem("Ready Movie", "movie", "https://akwam.example/movie/ready", "akwam"),
            MediaItem("Dead Movie", "movie", "https://akwam.example/movie/dead", "akwam"),
        ]

        def fake_stream_count(item):
            return 2 if item.name == "Ready Movie" else 0

        with patch("arabcity_scraper.playable_stream_count", side_effect=fake_stream_count):
            result = filter_playable_items(items)

        by_name = {item.name: item for item in result}
        self.assertEqual(set(by_name), {"Ready Movie"})
        self.assertTrue(by_name["Ready Movie"].playable)
        self.assertTrue(by_name["Ready Movie"].playable_checked)
        self.assertEqual(by_name["Ready Movie"].playable_streams, 2)

    def test_filter_playable_items_excludes_items_with_check_errors(self):
        items = [MediaItem("Broken Movie", "movie", "https://akwam.example/movie/broken", "akwam")]
        with patch("arabcity_scraper.playable_stream_count", side_effect=RuntimeError("bad stream")):
            result = filter_playable_items(items)
        self.assertEqual(result, [])
        self.assertTrue(items[0].playable_checked)
        self.assertFalse(items[0].playable)

    def test_stremio_url_encodes_full_id_segment(self):
        url = stremio_url(
            "stream",
            "ArabCity-Akwam",
            "arabcity:akoam:series:الشاهد:https%3A%2F%2Fakwam.it%2Fseries%2F1",
        )
        self.assertIn("arabcity%3Aakoam%3Aseries%3A", url)
        self.assertIn("https%253A%252F%252Fakwam.it", url)

    def test_media_item_from_addon_meta_uses_embedded_source_url(self):
        meta = {
            "id": "arabcity:akoam:series:from-4:https%3A%2F%2Fakwam.it%2Fseries%2F5597%2Ffrom-4",
            "name": "From 4",
            "poster": "https://img.example.test/poster.jpg",
            "description": "جودة: WEB-DL",
        }
        item = media_item_from_addon_meta(meta, CATALOG_ROUTES["akoam-series-all"])
        self.assertIsNotNone(item)
        self.assertEqual(item.url, "https://akwam.it/series/5597/from-4")
        self.assertEqual(item.kind, "series")
        self.assertEqual(item.image, "https://img.example.test/poster.jpg")
        self.assertEqual(item.description, "جودة: WEB-DL")

    def test_available_catalogs_starts_with_complete_library(self):
        catalogs = available_catalogs()
        self.assertEqual(catalogs[0]["id"], COMPLETE_LIBRARY_CATALOG_ID)

    def test_index_autoloads_first_ten_series_episode_lists(self):
        self.assertIn("autoloadInitialEpisodeLists(visibleItems, batch)", INDEX_HTML)
        self.assertIn('items.filter(item => item.kind === "series").slice(0, 10)', INDEX_HTML)
        self.assertIn('button.dataset.autoloaded = "1"', INDEX_HTML)
        self.assertIn("episodeMetaRequests", INDEX_HTML)

    def test_index_progressively_renders_results_in_memory(self):
        self.assertIn("const RESULTS_PAGE_SIZE = 40", INDEX_HTML)
        self.assertIn("let extractedItems = []", INDEX_HTML)
        self.assertIn("extractedItems.slice(0, visibleItemCount)", INDEX_HTML)
        self.assertIn('id="loadMore"', INDEX_HTML)
        self.assertIn("عرض المزيد", INDEX_HTML)

    def test_index_blocks_unverified_episode_watch_buttons(self):
        self.assertIn("isDirectVideoUrl", INDEX_HTML)
        self.assertIn("لا توجد روابط مشاهدة مباشرة مؤكدة", INDEX_HTML)

    def test_index_clears_episode_cache_on_catalog_change(self):
        self.assertIn("clearEpisodeCaches({ server: true })", INDEX_HTML)
        self.assertIn("/api/episode-cache/clear", INDEX_HTML)

    def test_index_quality_stats_bar_labels(self):
        self.assertIn("لديها حلقات", INDEX_HTML)
        self.assertIn("جاهزة للتشغيل", INDEX_HTML)
        self.assertIn("stats.with_episodes", INDEX_HTML)

    def test_index_uses_check_player_badges(self):
        self.assertIn("/api/check-player", INDEX_HTML)
        self.assertIn("playerCheckCache", INDEX_HTML)
        self.assertIn("مباشر", INDEX_HTML)
        self.assertIn("غير مؤكد", INDEX_HTML)
        self.assertIn("غير متاح", INDEX_HTML)

    def test_index_player_shows_context_and_inline_failures(self):
        self.assertIn('id="playerMeta"', INDEX_HTML)
        self.assertIn("playerContextFromLink", INDEX_HTML)
        self.assertIn("data-work-title", INDEX_HTML)
        self.assertIn("data-episode-number", INDEX_HTML)
        self.assertIn("جاري تحميل الفيديو", INDEX_HTML)
        self.assertIn("فشل تشغيل الرابط داخل الصفحة", INDEX_HTML)
        self.assertNotIn("window.open", INDEX_HTML)

    def test_index_hls_has_retry_recovery_and_clear_errors(self):
        self.assertIn("const HLS_NETWORK_RETRY_LIMIT = 3", INDEX_HTML)
        self.assertIn("currentHls.startLoad()", INDEX_HTML)
        self.assertIn("currentHls.recoverMediaError()", INDEX_HTML)
        self.assertIn("manifestLoadingMaxRetry", INDEX_HTML)
        self.assertIn("المتصفح لا يدعم تشغيل HLS", INDEX_HTML)
        self.assertIn("تعذر الاتصال بسيرفر البث", INDEX_HTML)

    def test_complete_library_group_uses_supported_manifest_catalogs(self):
        expected = tuple(str(catalog["id"]) for catalog in MANIFEST["catalogs"] if str(catalog["id"]) in CATALOG_ROUTES)
        self.assertEqual(manifest_catalog_ids(), expected)
        self.assertEqual(CATALOG_GROUPS[COMPLETE_LIBRARY_CATALOG_ID], expected)

    def test_scrape_catalog_caches_results_by_request_parameters(self):
        result_payload = {
            "catalog": "akoam-movies-all",
            "catalog_name": "Movies",
            "source": "akwam",
            "urls": ["https://example.test/movies"],
            "count": 1,
            "playable_only": False,
            "stats": {"total": 1},
            "errors": [],
            "items": [
                {
                    "name": "Ready Movie",
                    "kind": "movie",
                    "url": "https://akwam.example/movie/ready",
                    "source": "akwam",
                    "image": "",
                    "episode_count": None,
                    "raw_titles": ["Ready Movie"],
                }
            ],
        }

        with patch("arabcity_scraper.scrape_single_catalog", return_value=result_payload) as mocked:
            first = scrape_catalog("akoam-movies-all", pages=2, search=" ready ", fetch_details=True)
            first["items"][0]["name"] = "Mutated"
            second = scrape_catalog("akoam-movies-all", pages=2, search="ready", fetch_details=True)

        mocked.assert_called_once_with(
            "akoam-movies-all",
            pages=2,
            search="ready",
            fetch_details=True,
            playable_only=False,
        )
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["items"][0]["name"], "Ready Movie")

    def test_scrape_catalog_cache_separates_playable_only(self):
        def fake_scrape_single(catalog_id, pages=1, search="", fetch_details=False, playable_only=False):
            return {
                "catalog": catalog_id,
                "catalog_name": "Movies",
                "source": "akwam",
                "urls": [],
                "count": 1 if playable_only else 2,
                "playable_only": playable_only,
                "stats": {"total": 1 if playable_only else 2},
                "errors": [],
                "items": [],
            }

        with patch("arabcity_scraper.scrape_single_catalog", side_effect=fake_scrape_single) as mocked:
            normal = scrape_catalog("akoam-movies-all", playable_only=False)
            playable = scrape_catalog("akoam-movies-all", playable_only=True)
            normal_again = scrape_catalog("akoam-movies-all", playable_only=False)

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(normal["count"], 2)
        self.assertEqual(playable["count"], 1)
        self.assertTrue(normal_again["cached"])

    def test_scrape_catalog_filters_addon_items_with_normalized_search_fields(self):
        items = [
            MediaItem(
                "From",
                "series",
                "https://akwam.example/series/from",
                "akwam",
                description="رعب وغموض داخل مدينة محاصرة",
                raw_titles=["From الموسم الرابع"],
            ),
            MediaItem(
                "Comedy Night",
                "series",
                "https://akwam.example/series/comedy-night",
                "akwam",
                description="كوميديا اجتماعية",
                raw_titles=["Comedy Night"],
            ),
        ]
        with patch("arabcity_scraper.addon_catalog_items", return_value=(items, [], ["https://example.test/catalog"])) as mocked:
            result = scrape_catalog("akoam-series-all", search="رُعْب   غموض")

        mocked.assert_called_once_with("akoam-series-all", CATALOG_ROUTES["akoam-series-all"], 1)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "From")

    def test_complete_library_scrapes_all_catalogs_and_merges_duplicates(self):
        def fake_scrape_single(catalog_id, pages=1, search="", fetch_details=False, fallback_to_site=True):
            self.assertEqual(pages, 2)
            self.assertEqual(search, "from")
            self.assertFalse(fallback_to_site)
            if catalog_id == "akoam-series-all":
                return {
                    "urls": [f"https://example.test/{catalog_id}"],
                    "errors": [],
                    "items": [
                        {
                            "name": "From",
                            "kind": "series",
                            "url": "https://akwam.example/series/from",
                            "source": "akwam",
                            "image": "",
                            "episode_count": 7,
                            "raw_titles": ["From"],
                        }
                    ],
                }
            if catalog_id == "alooytv-arabic":
                return {
                    "urls": [f"https://example.test/{catalog_id}"],
                    "errors": [],
                    "items": [
                        {
                            "name": "From",
                            "kind": "series",
                            "url": "https://alooytv.example/series/from",
                            "source": "alooytv",
                            "image": "https://img.example/from.jpg",
                            "episode_count": 8,
                            "raw_titles": ["From Arabic"],
                        }
                    ],
                }
            if catalog_id == "akoam-movies-all":
                return {
                    "urls": [f"https://example.test/{catalog_id}"],
                    "errors": [],
                    "items": [
                        {
                            "name": "Inception",
                            "kind": "movie",
                            "url": "https://akwam.example/movie/inception",
                            "source": "akwam",
                            "image": "",
                            "episode_count": None,
                            "raw_titles": ["Inception"],
                        }
                    ],
                }
            return {"urls": [f"https://example.test/{catalog_id}"], "errors": [], "items": []}

        with patch("arabcity_scraper.scrape_single_catalog", side_effect=fake_scrape_single) as mocked:
            result = scrape_catalog(COMPLETE_LIBRARY_CATALOG_ID, pages=2, search="from")

        self.assertEqual(mocked.call_count, len(CATALOG_GROUPS[COMPLETE_LIBRARY_CATALOG_ID]))
        self.assertEqual(result["count"], 3)
        by_key = {(item["name"], item["source"]): item for item in result["items"]}
        self.assertEqual(by_key[("From", "akwam")]["episode_count"], 7)
        self.assertEqual(by_key[("From", "alooytv")]["episode_count"], 8)
        self.assertEqual(by_key[("From", "alooytv")]["image"], "https://img.example/from.jpg")
        self.assertEqual(by_key[("Inception", "akwam")]["kind"], "movie")
        self.assertEqual(result["stats"]["total"], 3)
        self.assertEqual(result["stats"]["movies"], 1)
        self.assertEqual(result["stats"]["series"], 2)
        self.assertEqual(result["stats"]["with_episodes"], 2)
        self.assertEqual(result["stats"]["sources"], 2)

    def test_complete_library_playable_only_filters_after_merge(self):
        def fake_scrape_single(catalog_id, pages=1, search="", fetch_details=False, fallback_to_site=True):
            if catalog_id == "akoam-movies-all":
                return {
                    "urls": [f"https://example.test/{catalog_id}"],
                    "errors": [],
                    "items": [
                        {
                            "name": "Ready Movie",
                            "kind": "movie",
                            "url": "https://akwam.example/movie/ready",
                            "source": "akwam",
                            "image": "",
                            "episode_count": None,
                            "raw_titles": ["Ready Movie"],
                        },
                        {
                            "name": "Dead Movie",
                            "kind": "movie",
                            "url": "https://akwam.example/movie/dead",
                            "source": "akwam",
                            "image": "",
                            "episode_count": None,
                            "raw_titles": ["Dead Movie"],
                        },
                    ],
                }
            return {"urls": [f"https://example.test/{catalog_id}"], "errors": [], "items": []}

        def fake_stream_count(item):
            return 1 if item.name == "Ready Movie" else 0

        with patch("arabcity_scraper.scrape_single_catalog", side_effect=fake_scrape_single):
            with patch("arabcity_scraper.playable_stream_count", side_effect=fake_stream_count):
                result = scrape_catalog(COMPLETE_LIBRARY_CATALOG_ID, playable_only=True)

        self.assertTrue(result["playable_only"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "Ready Movie")
        self.assertTrue(result["items"][0]["playable"])
        self.assertEqual(result["stats"]["with_episodes"], 0)
        self.assertEqual(result["stats"]["checked"], 1)
        self.assertEqual(result["stats"]["playable"], 1)


if __name__ == "__main__":
    unittest.main()
