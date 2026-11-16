"""Semantic, static HTML discussions. Never treats a news post as a reader comment."""

import hashlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlsplit

from echoscope.domain.models import Kind, Message

from .syndication import parse_date

VOID = {
    "br",
    "hr",
    "img",
    "input",
    "meta",
    "link",
    "source",
    "wbr",
    "area",
    "base",
    "embed",
    "param",
    "track",
    "col",
}
HIDDEN = {"script", "style", "nav", "form", "button", "noscript"}
BODY = {
    "comment-content",
    "comment-text",
    "comment__text",
    "post-message",
    "post-content",
    "comment-body",
    "post-text",
    "comment-message",
    "content",
}
AUTHOR = {"comment-author", "author", "author-name", "username", "fn"}


@dataclass(eq=False)
class Element:
    tag: str
    attrs: dict
    parent: "Element | None" = None
    children: list = field(default_factory=list)

    @property
    def classes(self):
        return set(self.attrs.get("class", "").casefold().split())


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Element("document", {})
        self.stack = [self.root]
        self.elements = []
        self.partial = len(html.encode("utf-8")) >= 1024 * 1024
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if len(self.elements) >= 20000 or len(self.stack) >= 80:
            self.partial = True
            raise ValueError("HTML demasiado complejo para el lector estático.")
        item = Element(tag, {key: value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(item)
        self.elements.append(item)
        if tag not in VOID:
            self.stack.append(item)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def ancestors(item):
    while item.parent:
        item = item.parent
        yield item


def discussion_container(item):
    return item.attrs.get("id", "").casefold() in {
        "comments",
        "comentarios",
        "discussion",
        "disqus_thread",
    } or bool(
        item.classes & {"comments", "comment-list", "comments-list", "discussion", "comments-area"}
    )


def is_comment(item):
    schema = item.attrs.get("itemtype", "").rstrip("/").endswith(("/Comment", "/UserComments"))
    identifier = item.attrs.get("id", "").casefold()
    explicit = identifier.startswith(
        ("comment-", "comment_", "comentario-")
    ) and identifier not in {"comment-form", "comment-reply", "comment-list"}
    return (
        schema
        or explicit
        or bool(item.classes & {"comment", "comentario"})
        or (
            bool(item.classes & {"post", "post-item", "comment-item"})
            and any(discussion_container(parent) for parent in ancestors(item))
        )
    )


def descendants(item):
    for child in item.children:
        if isinstance(child, Element):
            yield child
            yield from descendants(child)


def plain(item, *, exclude_comments=False, exclude_metadata=False):
    if item.tag in HIDDEN or (exclude_comments and is_comment(item)):
        return ""
    if exclude_metadata and (
        item.tag == "time"
        or item.classes & AUTHOR
        or item.attrs.get("itemprop") in {"author", "datePublished"}
    ):
        return ""
    pieces = []
    for child in item.children:
        pieces.append(
            plain(child, exclude_comments=exclude_comments, exclude_metadata=exclude_metadata)
            if isinstance(child, Element)
            else child
        )
    return " ".join(" ".join(pieces).split())


def parse_discussion(html, article, title=None, *, include_comments=True):
    document = Document(html)
    if not title:
        heading = next((node for node in document.elements if node.tag == "h1"), None)
        title = plain(heading)[:300] if heading else None
    comments = [item for item in document.elements if is_comment(item)]
    comment_set = set(comments)

    def belongs(node, item):
        for parent in ancestors(node):
            if parent is item:
                return True
            if parent in comment_set:
                return False
        return False

    messages = []
    if include_comments:
        for item in comments[:200]:
            # A comment wrapper can contain another comment wrapper with the same ID.
            if item.attrs.get("id") and any(
                parent in comment_set and parent.attrs.get("id") == item.attrs.get("id")
                for parent in ancestors(item)
            ):
                continue
            nodes = [node for node in descendants(item) if belongs(node, item)]
            body = next(
                (
                    node
                    for node in nodes
                    if node.attrs.get("itemprop") == "text"
                    or node.classes & (BODY - {"comment-body"})
                ),
                None,
            )
            body = body or next((node for node in nodes if "comment-body" in node.classes), None)
            if not body:
                continue  # Require an identifiable reader text, never guess from an entire post.
            raw_text = plain(body, exclude_comments=True, exclude_metadata=True)
            document.partial |= len(raw_text) > 65536
            text = raw_text[:65536]
            if not text:
                continue
            author_node = next(
                (
                    node
                    for node in nodes
                    if node.classes & AUTHOR or node.attrs.get("itemprop") == "author"
                ),
                None,
            )
            author = plain(author_node)[:200] if author_node else None
            date_node = next((node for node in nodes if node.tag == "time"), None)
            identifier = item.attrs.get("data-comment-id") or item.attrs.get("id")
            identifier = (
                identifier or hashlib.sha256(f"{article}\0{author}\0{text}".encode()).hexdigest()
            )
            parent = next((node for node in ancestors(item) if node in comment_set), None)
            messages.append(
                Message(
                    Kind.PRESS_COMMENT,
                    "html:comment:"
                    + urlsplit(article).hostname
                    + ":"
                    + hashlib.sha256(article.encode()).hexdigest()[:16],
                    identifier,
                    article,
                    text,
                    author,
                    url=article.split("#", 1)[0] + "#" + identifier,
                    published_at=parse_date(date_node.attrs.get("datetime")) if date_node else None,
                    resource_title=title,
                    parent_id=(parent.attrs.get("data-comment-id") or parent.attrs.get("id"))
                    if parent
                    else None,
                )
            )
    body = next(
        (
            node
            for node in document.elements
            if (
                node.attrs.get("itemprop") == "articleBody"
                or node.classes & {"entry-content", "article-body", "post-content",
                                   "richtextarticlebody"}
                or (urlsplit(article).hostname == "www.montevideo.com.uy"
                    and "contenido" in node.classes
                    and any(parent.tag == "article" for parent in ancestors(node)))
            )
            and not any(
                is_comment(parent) or discussion_container(parent) for parent in ancestors(node)
            )
        ),
        None,
    )
    if body:
        raw_text = (title + "\n" if title else "") + plain(body, exclude_comments=True)
        document.partial |= len(raw_text) > 65536
        text = raw_text[:65536]
        if text:
            messages.insert(
                0,
                Message(
                    Kind.NEWS_ARTICLE,
                    "html:article:" + urlsplit(article).hostname,
                    article,
                    article,
                    text,
                    url=article,
                    title=title,
                ),
            )
    return tuple(messages), document.partial or len(comments) > 200
