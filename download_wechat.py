#!/usr/bin/env python3
"""Download a public WeChat article into Markdown with optional local images."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify


DEFAULT_TIMEOUT = 20
ARTICLE_HOSTS = {"mp.weixin.qq.com"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".svg"}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def validate_article_url(url: str) -> str:
    """Validate and normalize a WeChat article URL before making a request."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in ARTICLE_HOSTS:
        raise ValueError("请输入 mp.weixin.qq.com 上的 http/https 文章链接。")
    if not parsed.path.startswith("/s/"):
        raise ValueError("链接路径不像微信公众号文章链接（预期 /s/...）。")
    return parsed.geturl()


def slugify(value: str, max_len: int = 80) -> str:
    """Create a filesystem-safe slug while preserving Chinese and other Unicode."""
    value = re.sub(r"[^\w.-]+", "-", value.strip(), flags=re.UNICODE)
    value = re.sub(r"-+", "-", value).strip("-._")
    return (value[:max_len].rstrip("-._") or "article")


def choose_image_url(img_tag) -> str | None:
    """Find the first usable lazy-loaded or regular image URL."""
    for attr in ("data-src", "data-wxsrc", "data-original-src", "data-original", "data-backsrc", "src"):
        value = img_tag.get(attr)
        if value:
            return value.strip()
    return None


def image_extension(url: str, content_type: str | None) -> str:
    """Choose a conservative image extension from the URL or response MIME type."""
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix

    mime = (content_type or "").split(";", 1)[0].strip().lower()
    by_mime = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/avif": ".avif",
        "image/svg+xml": ".svg",
    }
    return by_mime.get(mime, ".jpg")


def download_image(
    session: requests.Session,
    url: str,
    dest_folder: Path,
    sequence: int,
    timeout: int = DEFAULT_TIMEOUT,
) -> str | None:
    """Download one image; return its local filename, or None on a recoverable failure."""
    response = None
    output_path = None
    try:
        response = session.get(url, stream=True, timeout=timeout)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if content_type and not content_type.lower().startswith("image/"):
            return None

        extension = image_extension(url, content_type)
        filename = f"img_{sequence:03d}{extension}"
        dest_folder.mkdir(parents=True, exist_ok=True)
        output_path = dest_folder / filename
        with output_path.open("wb") as output:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    output.write(chunk)
        return filename
    except (requests.RequestException, OSError, ValueError):
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        return None
    finally:
        if response is not None:
            response.close()


def _article_title(soup: BeautifulSoup) -> str:
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content", "").strip():
        return og_title["content"].strip()
    for tag_name in ("h1", "h2", "title"):
        tag = soup.find(tag_name)
        if tag:
            text = tag.get_text(" ", strip=True)
            if text:
                return text
    return "wechat_article"


def _unique_slug(outdir: Path, title: str) -> str:
    base = slugify(title)
    slug = base
    suffix = 2
    while (outdir / f"{slug}.md").exists() or (outdir / f"{slug}_images").exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def fetch_article(
    url: str,
    outdir: Path,
    *,
    session: requests.Session | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    download_images: bool = True,
) -> Path:
    """Fetch an article and write Markdown plus images to ``outdir``."""
    article_url = validate_article_url(url)
    owns_session = session is None
    client = session or requests.Session()
    client.headers.update(HEADERS)

    try:
        response = client.get(article_url, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        content = soup.find(id="js_content")
        if content is None:
            content = soup.find("div", class_=re.compile(r"rich_media_content|article"))
        if content is None:
            raise RuntimeError("找不到文章正文（页面中没有 #js_content），可能链接不可访问或页面结构已变化。")

        title = _article_title(soup)
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        slug = _unique_slug(outdir, title)
        images_dir = outdir / f"{slug}_images"

        if download_images:
            for sequence, image in enumerate(content.find_all("img"), start=1):
                raw_url = choose_image_url(image)
                if not raw_url:
                    continue
                image_url = urljoin(article_url, raw_url)
                if urlparse(image_url).scheme not in {"http", "https"}:
                    continue
                filename = download_image(client, image_url, images_dir, sequence, timeout)
                if filename:
                    image["src"] = f"{images_dir.name}/{filename}"
                    for attr in list(image.attrs):
                        if attr != "src":
                            del image.attrs[attr]

        body = markdownify(str(content), heading_style="ATX").strip()
        markdown = f"# {title}\n\nSource: {article_url}\n\n{body}\n"
        output_file = outdir / f"{slug}.md"
        output_file.write_text(markdown, encoding="utf-8")
        return output_file
    finally:
        if owns_session:
            client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将可访问的微信公众号文章保存为 Markdown，并可下载正文图片。"
    )
    parser.add_argument("url", help="微信公众号文章链接，例如 https://mp.weixin.qq.com/s/...")
    parser.add_argument("--outdir", type=Path, default=Path("data"), help="输出目录（默认：./data）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单次请求超时秒数（默认：20）")
    parser.add_argument("--no-images", action="store_true", help="不下载图片，正文保留原图片链接")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout 必须是正整数。")
    try:
        output_file = fetch_article(
            args.url,
            args.outdir,
            timeout=args.timeout,
            download_images=not args.no_images,
        )
    except (requests.RequestException, RuntimeError, ValueError, OSError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1

    print(f"已保存 Markdown：{output_file}")
    print(f"输出目录：{output_file.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
