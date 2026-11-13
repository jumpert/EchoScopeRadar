"""Bounded exports of the same filtered records shown by the database browser."""

import csv
from collections import Counter
from html import escape
from io import BytesIO, StringIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .render import safe

COLUMNS = {
    "id": "Registro",
    "source": "Fuente",
    "kind": "Tipo",
    "title": "Publicación",
    "author": "Autor",
    "captured": "Capturado (UTC)",
    "published": "Publicado (UTC)",
    "text": "Contenido",
    "terms": "Palabras detectadas",
    "approximate_terms": "Aproximaciones para revisar",
    "severity": "Prioridad",
    "review": "Revisión",
    "tone": "Tono estimado",
    "url": "Enlace",
    "resource": "Recurso",
}
LABELS = {
    "all": "Todos",
    "open": "Sin verificar",
    "verified": "Verificada",
    "threat": "Amenaza",
    "dismissed": "Descartada",
    "none": "Sin alerta",
    "critical": "Crítica",
    "important": "Importante",
    "info": "Informativa",
    "negative": "Negativo",
    "positive": "Positivo",
    "mixed": "Mixto",
    "neutral": "Neutro",
    "COMMENT": "Comentario",
    "PRESS_COMMENT": "Comentario de prensa",
    "REVIEW": "Reseña",
    "NEWS_ARTICLE": "Noticia",
    "FEED_ENTRY": "Publicación",
    "YOUTUBE_VIDEO": "Video",
    "YOUTUBE_LIVE": "Directo",
    "LIVE_CHAT": "Chat en vivo",
    "FORUM_POST": "Foro",
    "SOCIAL_COMMENT": "Comentario social",
}


def values(row):
    result = []
    for key in COLUMNS:
        value = row.get(key, "")
        if isinstance(value, list):
            value = " · ".join(value)
        if key in {"review", "severity", "tone", "kind"}:
            value = LABELS.get(value, value)
        result.append(safe(str(value)))
    return result


def export_data(rows, format, *, summary=""):
    if format == "csv":
        output = StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow(COLUMNS.values())
        for row in rows:
            # A quoted CSV cell alone does not prevent spreadsheet formula execution.
            writer.writerow(
                [
                    "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
                    for value in values(row)
                ]
            )
        return output.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"
    output = BytesIO()
    if format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Consulta"
        sheet.append(list(COLUMNS.values()))
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="075443")
        for row_number, row in enumerate(rows, start=2):
            for column, value in enumerate(values(row), start=1):
                cell = sheet.cell(row_number, column, value)
                cell.data_type = "s"  # External text is never a formula.
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 26
        sheet.column_dimensions["H"].width = 75
        info = workbook.create_sheet("Información")
        for value in [
            "EchoScope Radar · Consulta de datos almacenados",
            summary,
            f"Registros: {len(rows)}",
            "Fechas UTC. El tono es una estimación por reglas.",
            "Excel admite hasta 32.767 caracteres por celda; CSV conserva textos más largos.",
        ]:
            info.append([value])
            info.cell(info.max_row, 1).data_type = "s"
        info.column_dimensions["A"].width = 110
        workbook.save(output)
        return (
            output.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if len(rows) > 1000:
        raise ValueError(
            "Para un PDF legible, acotá la consulta a 1.000 registros. Excel y CSV admiten 5.000."
        )
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 10.5
    styles["BodyText"].leading = 15
    story = []

    def paragraph(text, style="BodyText"):
        return Paragraph(escape(safe(str(text))).replace("\n", "<br/>"), styles[style])

    story.extend(
        [
            paragraph("EchoScope Radar · Datos almacenados", "Title"),
            paragraph(summary),
            paragraph(f"Registros: {len(rows)} · Fuentes: {len({row['source'] for row in rows})}"),
            paragraph(
                "Revisión: "
                + " · ".join(
                    f"{LABELS.get(key, key)}: {count}"
                    for key, count in Counter(row["review"] for row in rows).items()
                )
            ),
            paragraph("Fechas UTC. El tono es una estimación por reglas."),
            Spacer(1, 14),
        ]
    )
    groups = {}
    for row in rows:
        groups.setdefault((row["source"], row["resource"], row["title"]), []).append(row)
    for (source, resource, title), items in groups.items():
        story.extend(
            [paragraph(f"{source} · {title}", "Heading2"), paragraph(items[0]["url"] or resource)]
        )
        for row in items:
            story.extend(
                [
                    paragraph(f"#{row['id']} · {row['captured']} · {row['author']}", "Heading3"),
                    paragraph(
                        f"{LABELS.get(row['review'], '')} · {LABELS.get(row['tone'], '')} · "
                        + (
                            LABELS.get(row.get("severity"), "") + " · "
                            if row.get("severity")
                            else ""
                        )
                        + " · ".join(row["terms"])
                    ),
                    paragraph(row["text"]),
                    paragraph(row["url"]),
                    Spacer(1, 8),
                ]
            )

    def page(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#475569"))
        canvas.drawString(36, 20, f"EchoScope Radar · Página {doc.page}")

    SimpleDocTemplate(
        output, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    ).build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue(), "application/pdf"
