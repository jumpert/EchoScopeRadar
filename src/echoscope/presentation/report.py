from collections import Counter, defaultdict
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


def site_of(item):
    host = urlsplit(item["url"] or item["resource_url"] or "").hostname
    return host.removeprefix("www.") if host else item["source"]


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
            "Registros con coincidencias confirmadas. Las cifras describen la cobertura de EchoScope; dependen de los datos que entregó cada fuente.",
            styles["BodyText"],
        ),
    ]
    if practice:
        story.append(Paragraph("MODO DE PRÁCTICA · Datos simulados", styles["Heading2"]))

    groups = defaultdict(list)
    youtube = []
    for item in rows:
        if item["provider"] == "YouTube":
            youtube.append(item)
        else:
            groups[site_of(item)].append(item)
    if groups:
        story.append(Paragraph("Resumen de sitios y feeds", styles["Heading2"]))
        summary = [["Sitio o fuente", "Registros", "Conversación", "Críticas"]]
        for name, records in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0])):
            summary.append(
                [
                    Paragraph(escape(name), styles["SmallCell"]),
                    str(len(records)),
                    str(sum(row["kind"] in DISCUSSIONS for row in records)),
                    str(sum(row["severity"] == "critical" for row in records)),
                ]
            )
        table = LongTable(summary, colWidths=[258, 75, 90, 75], repeatRows=1, hAlign="LEFT")
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
        for site, records in sorted(groups.items()):
            story.append(Paragraph(escape(site), styles["Heading2"]))
            terms = Counter(term for item in records for term in set(item["confirmed_terms"]))
            top = ", ".join(
                f"{term} ({count})"
                for term, count in sorted(terms.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
            )
            story.append(
                Paragraph(f"Términos por cantidad de registros: {escape(top)}", styles["Meta"])
            )
            for item in records:
                story.append(KeepTogether(record_lines(item, styles, excerpt=True)))
    if youtube:
        story.append(Paragraph("YouTube · Enlaces de alertas individuales", styles["Heading2"]))
        story.append(
            Paragraph(
                "Se indican las reglas locales y el enlace de cada alerta. Las cifras del resumen corresponden a los demás sitios y feeds.",
                styles["Meta"],
            )
        )
        for item in youtube:
            story.append(KeepTogether(record_lines(item, styles, excerpt=False)))
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
    identity = f"{when} UTC · {kind} · {item['source']} · {level}"
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
    if item["url"]:
        address = escape(item["url"], quote=True)
        fields.append(
            Paragraph(
                f'<link href="{address}" color="#087684"><u>Abrir origen</u></link>', styles["Meta"]
            )
        )
    if item["resource_url"] and item["resource_url"] != item["url"]:
        address = escape(item["resource_url"], quote=True)
        fields.append(
            Paragraph(
                f'<link href="{address}" color="#087684"><u>Abrir publicación relacionada</u></link>',
                styles["Meta"],
            )
        )
    return fields
