from echoscope.presentation.report import report_groups, report_link


def test_groups_by_original_url_not_by_platform_or_individual_comment():
    video = "https://www.youtube.com/watch?v=abcdefghijk"
    article = "https://example.com/articulo"

    def row(kind, parent, *, provider=None, title=None, resource_title=None):
        return {
            "kind": kind,
            "resource_url": parent,
            "resource_id": None,
            "source": "Fuente",
            "provider": provider,
            "title": title,
            "resource_title": resource_title,
        }

    chat = row("LIVE_CHAT", video, provider="YouTube")
    live = row("YOUTUBE_LIVE", video, provider="YouTube", title="Rueda de prensa")
    comment = row("PRESS_COMMENT", article, resource_title="Comunicado")
    review = row("REVIEW", article)
    unrelated = row("PRESS_COMMENT", article + "-2")
    groups = list(report_groups([chat, comment, live, review, unrelated]))
    assert groups == [
        ("Directo", "Rueda de prensa", video, [chat, live]),
        ("Nota", "Comunicado", article, [comment, review]),
        ("Nota", "example.com", article + "-2", [unrelated]),
    ]
    assert report_link("javascript:alert(1)", "Abrir", None) is None
