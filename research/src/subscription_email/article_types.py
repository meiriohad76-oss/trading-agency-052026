from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

READABLE_ARTICLE_MIN_CHARS = 500
LOGIN_TITLE_MARKERS = (
    "access to this page has been denied",
    "before we continue",
    "checking if the site connection is secure",
    "confirm you are a human",
    "log in",
    "login",
    "press & hold",
    "press and hold",
    "sign in",
    "subscribe to continue",
    "verify you are human",
)


@dataclass(frozen=True)
class FetchedArticle:
    url: str
    status_code: int
    title: str | None
    text: str


def html_to_text(html: str) -> tuple[str | None, str]:
    parser = _ReadableHTMLParser()
    parser.feed(html)
    return parser.title, " ".join(" ".join(parser.parts).split())


def looks_like_readable_article(
    article: FetchedArticle,
    *,
    min_chars: int = READABLE_ARTICLE_MIN_CHARS,
) -> bool:
    if int(article.status_code) in {401, 403}:
        return False
    title = " ".join((article.title or "").split()).lower()
    if not title or any(marker in title for marker in LOGIN_TITLE_MARKERS):
        return False
    text = " ".join(article.text.split())
    return len(text) >= min_chars


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title: str | None = None
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or self._skip_depth > 0:
            return
        if self._in_title:
            self.title = text
        else:
            self.parts.append(text)
