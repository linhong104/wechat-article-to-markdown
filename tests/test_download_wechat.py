from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import requests

from download_wechat import (
    choose_image_url,
    fetch_article,
    image_extension,
    slugify,
    validate_article_url,
)


ARTICLE_URL = "https://mp.weixin.qq.com/s/example-id"


class FakeResponse:
    def __init__(self, *, text="", content_type="", chunks=None):
        self.text = text
        self.headers = {"content-type": content_type} if content_type else {}
        self._chunks = chunks or []
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield from self._chunks

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = responses
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        try:
            return self.responses[url]
        except KeyError as error:
            raise requests.ConnectionError(url) from error

    def close(self):
        self.closed = True


class DownloaderTests(unittest.TestCase):
    def test_url_validation_accepts_only_wechat_article_links(self):
        self.assertEqual(validate_article_url(f" {ARTICLE_URL} "), ARTICLE_URL)
        for url in (
            "https://example.com/s/article",
            "ftp://mp.weixin.qq.com/s/article",
            "https://mp.weixin.qq.com/other/article",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_article_url(url)

    def test_slugify_preserves_chinese_and_removes_path_separators(self):
        self.assertEqual(slugify(" ../中文 标题:/测试 "), "中文-标题-测试")
        self.assertEqual(slugify("!!!"), "article")
        self.assertLessEqual(len(slugify("长" * 100)), 80)

    def test_choose_image_url_prefers_lazy_source(self):
        from bs4 import BeautifulSoup

        image = BeautifulSoup(
            '<img src="fallback.jpg" data-src="https://img.example/a.jpg">',
            "html.parser",
        ).img
        self.assertEqual(choose_image_url(image), "https://img.example/a.jpg")

    def test_image_extension_uses_mime_when_url_has_no_extension(self):
        self.assertEqual(image_extension("https://img.example/id", "image/webp; charset=binary"), ".webp")
        self.assertEqual(image_extension("https://img.example/photo.jpeg", None), ".jpg")

    def test_fetch_writes_markdown_and_local_image_without_network(self):
        image_url = "https://mmbiz.qpic.cn/example/image"
        html = f'''<!doctype html><html><head>
        <meta property="og:title" content="春日阅读：中文标题">
        </head><body><div id="js_content"><p>正文段落。</p>
        <img alt="封面" data-src="{image_url}"></div></body></html>'''
        article_response = FakeResponse(text=html)
        image_response = FakeResponse(content_type="image/png", chunks=[b"png", b"bytes"])
        session = FakeSession({ARTICLE_URL: article_response, image_url: image_response})

        with tempfile.TemporaryDirectory() as temp_dir:
            output = fetch_article(ARTICLE_URL, Path(temp_dir), session=session)
            text = output.read_text(encoding="utf-8")
            image_file = output.parent / "春日阅读-中文标题_images" / "img_001.png"

            self.assertEqual(output.name, "春日阅读-中文标题.md")
            self.assertIn("# 春日阅读：中文标题", text)
            self.assertIn("正文段落。", text)
            self.assertIn("春日阅读-中文标题_images/img_001.png", text)
            self.assertEqual(image_file.read_bytes(), b"pngbytes")
            self.assertEqual(len(session.calls), 2)
            self.assertTrue(image_response.closed)

    def test_same_title_does_not_overwrite_previous_article(self):
        html = '<meta property="og:title" content="同名文章"><div id="js_content"><p>正文</p></div>'
        session = FakeSession({ARTICLE_URL: FakeResponse(text=html)})
        with tempfile.TemporaryDirectory() as temp_dir:
            first = fetch_article(ARTICLE_URL, Path(temp_dir), session=session, download_images=False)
            second = fetch_article(ARTICLE_URL, Path(temp_dir), session=session, download_images=False)
            self.assertEqual(first.name, "同名文章.md")
            self.assertEqual(second.name, "同名文章-2.md")
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())

    def test_no_images_option_does_not_fetch_image_urls(self):
        image_url = "https://mmbiz.qpic.cn/example/image"
        html = f'<div id="js_content"><img src="{image_url}" alt="图"></div>'
        session = FakeSession({ARTICLE_URL: FakeResponse(text=html)})
        with tempfile.TemporaryDirectory() as temp_dir:
            output = fetch_article(
                ARTICLE_URL,
                Path(temp_dir),
                session=session,
                download_images=False,
            )
            self.assertIn(image_url, output.read_text(encoding="utf-8"))
            self.assertEqual(len(session.calls), 1)

    def test_missing_article_body_has_actionable_error(self):
        session = FakeSession({ARTICLE_URL: FakeResponse(text="<html><title>登录</title></html>")})
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "找不到文章正文"):
                fetch_article(ARTICLE_URL, Path(temp_dir), session=session)


if __name__ == "__main__":
    unittest.main()
