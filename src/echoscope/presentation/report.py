from collections import Counter
from html import escape
from io import BytesIO
from urllib.parse import urlsplit

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

DISCUSSIONS = {"COMMENT", "PRESS_COMMENT", "REVIEW", "LIVE_CHAT", "FORUM_POST", "SOCIAL_COMMENT"}
KINDS = {
    "NEWS_ARTICLE": "Noticia",
    "YOUTUBE_VIDEO": "Video",
    "YOUTUBE_LIVE": "Directo",
    "PRESS_COMMENT": "Comentario de prensa",
    "COMMENT": "Comentario",
    "REVIEW": "Reseña",
    "LIVE_CHAT": "Mensaje de chat",
    "FEED_ENTRY": "Publicación",
    "FORUM_POST": "Foro",
    "SOCIAL_COMMENT": "Respuesta en red social",
}
LEVELS = {"critical": "Crítica", "important": "Importante", "info": "Informativa"}
REVIEWS = {
    "open": "Sin verificar",
    "verified": "Verificada",
    "threat": "Marcada como amenaza",
    "dismissed": "Descartada",
}
PUBLICATIONS = {
    "NEWS_ARTICLE": "Nota",
    "YOUTUBE_VIDEO": "Video",
    "YOUTUBE_LIVE": "Directo",
    "LIVE_CHAT": "Chat en vivo",
    "PRESS_COMMENT": "Nota",
    "REVIEW": "Reseñas",
    "FORUM_POST": "Foro",
    "SOCIAL_COMMENT": "Publicación en red social",
    "COMMENT": "Comentarios",
}
BRIEF_GROUP_LIMIT = 5
BRIEF_ROWS_PER_GROUP = 2


def report_groups(rows):
    grouped = {}
    for item in rows:
        parent = item["resource_url"]
        key = ("url", parent) if parent else ("source", item["source"], item["kind"])
        grouped.setdefault(key, []).append(item)
    for (_, parent, *_), records in grouped.items():
        kinds = {item["kind"] for item in records}
        group_kind = next(
            (
                key
                for key in ("YOUTUBE_LIVE", "LIVE_CHAT", "YOUTUBE_VIDEO", "NEWS_ARTICLE")
                if key in kinds
            ),
            records[0]["kind"],
        )
        label = (
            "Video"
            if group_kind == "COMMENT" and records[0]["provider"] == "YouTube"
            else PUBLICATIONS.get(group_kind, "Publicación")
        )
        title = next(
            (
                item["resource_title"]
                or (item["title"] if item["kind"] not in DISCUSSIONS else None)
                for item in records
                if item["resource_title"] or (item["title"] and item["kind"] not in DISCUSSIONS)
            ),
            None,
        )
        has_origin = records[0]["resource_url"] is not None
        if not title:
            host = urlsplit(parent).hostname if has_origin else None
            title = (host or records[0]["source"]) + (
                f" · {records[0]['resource_id']}" if records[0]["resource_id"] else ""
            )
        yield label, title, parent if has_origin else None, records


def report_link(address, label, style):
    try:
        parsed = urlsplit(address)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username:
            return None
    except ValueError:
        return None
    return Paragraph(
        f'<link href="{escape(address, quote=True)}" color="#087684"><u>{escape(label)}</u></link>',
        style,
    )


def report_priority(row):
    state = row["review_state"]
    severity = {"critical": 0, "important": 1, "info": 2}[row["severity"]]
    return (
        0 if state == "threat" else 1 if state == "open" else 2 if state == "verified" else 3,
        severity,
        row["tone"] != "negative",
    )


def report_selection(rows, *, brief):
    groups = list(report_groups(rows))
    if not brief:
        return groups
    ranked = []
    for label, title, parent, items in groups:
        relevant = [row for row in items if row["review_state"] != "dismissed"]
        if relevant:
            ranked.append((label, title, parent, sorted(relevant, key=report_priority)))
    ranked.sort(key=lambda group: report_priority(group[3][0]))
    return [
        (label, title, parent, items[:BRIEF_ROWS_PER_GROUP])
        for label, title, parent, items in ranked[:BRIEF_GROUP_LIMIT]
    ]


def report_pdf(rows, start, end, practice, *, layout="brief"):
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=43,
        leftMargin=43,
        topMargin=38,
        bottomMargin=39,
        title="EchoScope Radar - Reporte de alertas",
        author="EchoScope Radar",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "Meta",
            fontName="Helvetica",
            fontSize=10,
            leading=12,
            textColor=colors.HexColor("#313131"),
        )
    )
    styles["Title"].alignment = 0
    styles["Title"].fontSize = 24
    styles["Title"].leading = 28
    styles["Heading2"].fontSize = 13
    styles["Heading2"].leading = 15
    styles["Heading3"].fontName = "Helvetica-Bold"
    styles["Heading3"].fontSize = 11
    styles["Heading3"].leading = 13
    styles["BodyText"].fontSize = 11
    styles["BodyText"].leading = 14
    styles.add(ParagraphStyle("Figure", fontName="Helvetica-Bold", fontSize=16, leading=18))
    brief = layout == "brief"
    subtitle = "Resumen para imprimir" if brief else "Detalle completo"
    period = f"Capturas: {start:%d/%m/%Y} al {end:%d/%m/%Y} (UTC)"
    story = [
        Paragraph(f"ECHOSCOPE RADAR  /  {subtitle.upper()}", styles["Meta"]),
        Paragraph("Reporte de alertas", styles["Title"]),
        Paragraph(f"{period}{' · Datos simulados' if practice else ''}", styles["Meta"]),
    ]

    if rows:
        eligible = [row for row in rows if row["provider"] != "YouTube"]
        counts = Counter(row["review_state"] for row in eligible)
        if eligible:
            story.append(Paragraph("Estado del período", styles["Heading2"]))
            summary = [
                ("Con alerta", len(eligible)),
                ("Sin verificar", counts["open"]),
                ("Verificadas", counts["verified"]),
                ("Amenazas marcadas", counts["threat"]),
                ("Descartadas", counts["dismissed"]),
            ]
            table = Table(
                [
                    [Paragraph(label, styles["Meta"]) for label, _ in summary],
                    [Paragraph(str(total), styles["Figure"]) for _, total in summary],
                ],
                colWidths=[(doc.width - 12) / 5] * 5,
                hAlign="LEFT",
                style=TableStyle(
                    [
                        ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.black),
                        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.black),
                        ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
                    ]
                ),
            )
            story.append(table)
            critical_pending = sum(
                row["severity"] == "critical" and row["review_state"] == "open" for row in eligible
            )
            story.append(Spacer(1, 7))
            story.append(
                Paragraph(
                    f"<b>Atención:</b> {critical_pending} alertas críticas sin verificar. "
                    "Las amenazas marcadas reflejan decisiones del operador.",
                    styles["BodyText"],
                )
            )
            terms = Counter(term for row in eligible for term in set(row["confirmed_terms"]))
            top = ", ".join(f"{term[:45]} ({count})" for term, count in terms.most_common(3))
            if top:
                story.append(Paragraph(f"Términos frecuentes: {escape(top)}.", styles["Meta"]))
        if len(eligible) != len(rows):
            story.append(Spacer(1, 7))
            story.append(
                Paragraph(
                    "YouTube: referencias al original, sin transcribir el chat ni incluirlo en las cifras.",
                    styles["Meta"],
                )
            )
        selected = report_selection(rows, brief=brief)
        story.append(
            Paragraph(
                "Publicaciones prioritarias" if brief else "Detalle por publicación",
                styles["Heading2"],
            )
        )
        if brief:
            displayed = sum(row["provider"] != "YouTube" for *_, items in selected for row in items)
            story.append(
                Paragraph(
                    f"Fuera del detalle breve: {len(eligible) - displayed} registros del resumen. "
                    "Para consultar todos los registros, elegí Detalle completo.",
                    styles["Meta"],
                )
            )
        if not selected:
            story.append(Paragraph("No hay publicaciones para priorizar.", styles["BodyText"]))
        for label, title, parent, records in selected:
            limit = 140 if brief else 240
            headline = title if len(title) <= limit else title[: limit - 1] + "…"
            header = [
                Spacer(1, 5),
                Paragraph(f"{escape(label)} · {escape(headline)}", styles["Heading3"]),
            ]
            short_link = (
                parent
                if parent and len(parent) <= 104
                else (
                    f"{urlsplit(parent).hostname} / Abrir publicación original" if parent else None
                )
            )
            link = report_link(parent, short_link, styles["Meta"]) if parent else None
            header.append(link or Paragraph("Enlace original no disponible.", styles["Meta"]))
            ordered = (
                records
                if brief
                else sorted(records, key=lambda row: (row["kind"] in DISCUSSIONS, row["date"]))
            )
            for index, item in enumerate(ordered):
                story.append(
                    KeepTogether(
                        (header if index == 0 else [])
                        + record_lines(
                            item, styles, excerpt=item["provider"] != "YouTube", brief=brief
                        )
                    )
                )
    if not rows:
        story.append(
            Paragraph("Sin alertas confirmadas en el intervalo seleccionado.", styles["Heading2"])
        )

    def footer(canvas, document):
        canvas.setStrokeColor(colors.HexColor("#999999"))
        canvas.line(43, 32, A4[0] - 43, 32)
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.black)
        canvas.drawString(43, 19, "EchoScope Radar · " + period)
        canvas.drawRightString(A4[0] - 43, 19, f"Página {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def record_lines(item, styles, *, excerpt, brief):
    when = f"{item['date'][8:10]}/{item['date'][5:7]} {item['date'][11:16]}"
    kind = KINDS.get(item["kind"], "Resultado")
    level = LEVELS[item["severity"]]
    identity = f"{when} · {kind} · {level} · {REVIEWS[item['review_state']]}"
    if item["job"] == "preview":
        identity += " · Vista previa"
    if excerpt and item["author"]:
        identity += f" · {item['author'][:80]}"
    fields = [Spacer(1, 5), Paragraph(f"<b>{escape(identity)}</b>", styles["Meta"])]
    terms = " · ".join(item["confirmed_terms"][: 3 if brief else 12])[:170]
    if excerpt:
        limit = 145 if brief else 340
        body = "".join(fragment[0] for fragment in item["fragments"])
        original_length = len(body)
        offset = next(
            (
                body.casefold().find(term.casefold())
                for term in item["confirmed_terms"]
                if term.casefold() in body.casefold()
            ),
            0,
        )
        start = max(0, offset - 34) if len(body) > limit else 0
        body = " ".join(body[start : start + limit].split())
        body = ("…" if start else "") + body + ("…" if original_length > start + limit else "")
        fields.append(
            Paragraph(
                f"<b>{escape(terms)}</b> · {escape(body)}" if body else escape(terms),
                styles["BodyText"],
            )
        )
    else:
        fields.append(Paragraph(escape(terms), styles["Meta"]))
    if item["url"] and item["url"] != item["resource_url"]:
        link = report_link(item["url"], "Abrir registro individual", styles["Meta"])
        if link:
            fields.append(link)
    return fields
