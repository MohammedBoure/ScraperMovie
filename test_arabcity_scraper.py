import unittest

from arabcity_scraper import (
    CATALOG_ROUTES,
    count_episodes_from_html,
    detect_episode_number,
    extract_media_items,
    normalize_media_name,
)


class ArabCityScraperTests(unittest.TestCase):
    def test_detect_episode_number_arabic(self):
        self.assertEqual(detect_episode_number("مسلسل المدينة الحلقة 12 مترجمة"), 12)
        self.assertEqual(detect_episode_number("مسلسل المدينة ح 7"), 7)

    def test_normalize_series_name(self):
        self.assertEqual(
            normalize_media_name("مشاهدة مسلسل المدينة البعيدة الموسم الاول الحلقة 3 مترجمة", "series"),
            "المدينة البعيدة",
        )

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


if __name__ == "__main__":
    unittest.main()
