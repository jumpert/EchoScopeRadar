from echoscope.presentation.report import report_groups, report_link, report_selection


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


def test_print_selection_prioritizes_human_marked_threats_then_critical_pending():
    def row(source, state, severity):
        return {
            "kind": "PRESS_COMMENT",
            "resource_url": f"https://example.com/{source}",
            "resource_id": None,
            "source": source,
            "provider": None,
            "title": None,
            "resource_title": source,
            "review_state": state,
            "severity": severity,
            "tone": "negative",
        }

    discarded = row("descartada", "dismissed", "critical")
    critical = row("crítica", "open", "critical")
    threat = row("amenaza", "threat", "info")
    others = [row(str(index), "verified", "info") for index in range(7)]
    rows = [discarded, critical, threat, threat.copy(), threat.copy(), *others]
    brief = report_selection(rows, brief=True)
    assert len(brief) == 5
    assert brief[0][3] == [threat, threat]
    assert brief[1][3] == [critical]
    assert discarded not in [record for *_, records in brief for record in records]
    assert report_selection(rows, brief=False)[0][3] == [discarded]
