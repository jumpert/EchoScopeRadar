from collections import Counter
from html import escape
from io import BytesIO
from urllib.parse import urlsplit

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    KeepTogether,
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
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
TONES = {"positive": "Positivo", "negative": "Negativo", "mixed": "Mixto", "neutral": "Neutro"}
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


def report_pdf(rows, start, end, practice):
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=42,
        leftMargin=42,
        topMargin=43,
        bottomMargin=43,
        title="EchoScope Radar - Reporte de alertas",
        author="EchoScope Radar",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "Meta",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#42546a"),
        )
    )
    styles.add(ParagraphStyle("SmallCell", fontName="Helvetica", fontSize=9, leading=11))
    styles["Title"].textColor = colors.HexColor("#102b44")
    styles["Heading2"].textColor = colors.HexColor("#087684")
    story = [
        Paragraph("ECHOSCOPE RADAR  /  MONITOREO", styles["Meta"]),
        Paragraph("Reporte de alertas", styles["Title"]),
        Paragraph(f"Fecha de captura (UTC): {start:%d/%m/%Y} al {end:%d/%m/%Y}", styles["Meta"]),
        Spacer(1, 8),
        Paragraph(
            "Incluye registros con coincidencias confirmadas por las reglas. "
            "El estado corresponde a la revisión actual de esos registros. "
            "Marcar una amenaza es una decisión del operador.",
            styles["BodyText"],
        ),
    ]
    if practice:
        story.append(Paragraph("MODO DE PRÁCTICA · Datos simulados", styles["Heading2"]))

    if rows:
        story.append(Paragraph("Resumen de alertas y revisión", styles["Heading2"]))
        eligible = [row for row in rows if row["provider"] != "YouTube"]
        counts = Counter(row["review_state"] for row in eligible)
        reviewed = len(eligible) - counts["open"]
        summary = [
            ["Indicador", "Registros"],
            ["Registros con alerta", str(len(eligible))],
            ["Sin verificar", str(counts["open"])],
            ["Verificadas", str(counts["verified"])],
            ["Marcadas como amenaza", str(counts["threat"])],
            ["Descartadas", str(counts["dismissed"])],
        ]
        table = LongTable(summary, colWidths=[doc.width - 90, 90], repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15344e")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.HexColor("#eef5f8"), colors.white],
                    ),
                    ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)
        if eligible:
            critical_pending = sum(
                row["severity"] == "critical" and row["review_state"] == "open" for row in eligible
            )
            story.append(Spacer(1, 7))
            story.append(
                Paragraph(
                    f"Revisadas: {reviewed} de {len(eligible)} ({100 * reviewed / len(eligible):.0f}%). "
                    f"Pendientes: {counts['open']}. Pendientes de severidad crítica: {critical_pending}.",
                    styles["BodyText"],
                )
            )
            terms = Counter(term for row in eligible for term in set(row["confirmed_terms"]))
            top = ", ".join(f"{term} ({count})" for term, count in terms.most_common(5))
            story.append(Paragraph(f"Términos más frecuentes: {escape(top)}.", styles["Meta"]))
            origins = Counter(
                (urlsplit(row["resource_url"]).hostname if row["resource_url"] else None)
                or row["source"]
                for row in eligible
            )
            top = ", ".join(f"{name} ({count})" for name, count in origins.most_common(5))
            story.append(Paragraph(f"Fuentes con más alertas: {escape(top)}.", styles["Meta"]))
        if len(eligible) != len(rows):
            story.append(Spacer(1, 7))
            story.append(
                Paragraph(
                    "YouTube se muestra como referencias agrupadas, fuera de las métricas. "
                    "Las etiquetas de revisión son de EchoScope Radar, no de YouTube.",
                    styles["Meta"],
                )
            )
        story.append(Paragraph("Detalle por publicación", styles["Heading2"]))
        for label, title, parent, records in report_groups(rows):
            header = [Paragraph(f"{escape(label)} · {escape(title[:300])}", styles["Heading3"])]
            link = (
                report_link(parent, "Abrir publicación original", styles["Meta"])
                if parent
                else None
            )
            header.append(link or Paragraph("Enlace original no disponible.", styles["Meta"]))
            ordered = sorted(records, key=lambda row: (row["kind"] in DISCUSSIONS, row["date"]))
            for index, item in enumerate(ordered):
                story.append(
                    KeepTogether(
                        (header if index == 0 else [])
                        + record_lines(item, styles, excerpt=item["provider"] != "YouTube")
                    )
                )
    if not rows:
        story.append(
            Paragraph("Sin alertas confirmadas en el intervalo seleccionado.", styles["Heading2"])
        )

    def footer(canvas, document):
        canvas.setStrokeColor(colors.HexColor("#c9d5e0"))
        canvas.line(42, 35, A4[0] - 42, 35)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#42546a"))
        canvas.drawString(42, 22, "EchoScope Radar  /  Reporte local")
        canvas.drawRightString(A4[0] - 42, 22, f"Página {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def record_lines(item, styles, *, excerpt):
    when = item["date"][:16].replace("T", " ")
    kind = KINDS.get(item["kind"], "Resultado")
    level = LEVELS[item["severity"]]
    identity = f"{when} UTC · {kind} · {item['source']} · {level} · {REVIEWS[item['review_state']]}"
    if item["job"] == "preview":
        identity += " · Vista previa"
    if excerpt and item["author"]:
        identity += f" · {item['author']}"
    fields = [Spacer(1, 8), Paragraph(f"<b>{escape(identity)}</b>", styles["Meta"])]
    terms = " · ".join(item["confirmed_terms"])
    tone = f" · Tono estimado: {TONES[item['tone']]}" if excerpt else ""
    fields.append(Paragraph(f"<b>{escape(terms)}</b>{escape(tone)}", styles["BodyText"]))
    if excerpt:
        body = "".join(fragment[0] for fragment in item["fragments"])
        if len(body) > 520:
            offset = next(
                (
                    body.casefold().find(term.casefold())
                    for term in item["confirmed_terms"]
                    if term.casefold() in body.casefold()
                ),
                0,
            )
            start = max(0, offset - 100)
            body = (
                ("…" if start else "")
                + body[start : start + 520]
                + ("…" if len(body) > start + 520 else "")
            )
        fields.append(Paragraph(escape(body), styles["Meta"]))
    if item["url"] and item["url"] != item["resource_url"]:
        link = report_link(item["url"], "Abrir registro individual", styles["Meta"])
        if link:
            fields.append(link)
    return fields
