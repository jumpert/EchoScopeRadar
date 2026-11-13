import csv
from dataclasses import replace
from io import BytesIO, StringIO

import pytest
from aiohttp.test_utils import TestClient, TestServer
from conftest import demo_config
from openpyxl import load_workbook

from echoscope.domain.models import Kind, Message, Observation, utcnow
from echoscope.domain.rules import evaluate
from echoscope.presentation.data_exports import export_data
from echoscope.presentation.web import KEY, create_app


async def test_account_history_query_pagination_filters_and_exports(tmp_path):
    app = create_app(tmp_path / "data.sqlite", practice=True, auto_start=False)
    async with TestClient(TestServer(app)) as client:
        app[KEY].authority = client.make_url("/").authority
        state = app[KEY]
        config = demo_config()
        await state.service.store.configure(config)
        state.config = config
        snapshot = (await state.service.store.snapshots())["comentarios"]
        snapshot = replace(snapshot, last_at=utcnow())
        execution = await state.service.store.start(snapshot)
        observations = tuple(
            Observation(
                message := Message(
                    Kind.COMMENT,
                    "test:comments",
                    str(index),
                    "https://example.org/nota",
                    "El Ejército tiene una demora",
                    "=1+1" if index == 0 else "Lector",
                    resource_title="Nota Defensa",
                    url="https://example.org/nota#comment",
                ),
                evaluate(
                    message.text, tuple(rule.compile() for rule in config.rule_sets["avisos"])
                ),
            )
            for index in range(55)
        )
        await state.service.store.apply(snapshot, execution, observations, True)
        bootstrap = await (await client.get("/api/bootstrap")).json()
        assert bootstrap["jobs"][0]["source_id"] == snapshot.source.id
        headers = {
            "Origin": str(client.make_url("/")).rstrip("/"),
            "X-EchoScope-Token": bootstrap["token"],
        }
        assert (await client.post("/api/data-query", json={})).status == 403
        assert (
            await client.post(
                "/api/data-query", json={"sql": "DROP TABLE messages"}, headers=headers
            )
        ).status == 400
        query = {"text": "Ejército", "kind": "COMMENT", "tone": "negative"}
        response = await client.post("/api/data-query", json=query, headers=headers)
        assert response.status == 200
        page = await response.json()
        assert len(page["rows"]) == 50 and page["has_more"]
        query["snapshot"] = page["snapshot"]
        late = replace(observations[0].message, external_id="after-snapshot", captured_at=utcnow())
        await state.service.store.apply(
            snapshot, execution, (Observation(late, observations[0].matches),), True
        )
        other = await (
            await client.post(
                "/api/data-query", json=query | {"before": page["next_before"]}, headers=headers
            )
        ).json()
        assert len(other["rows"]) == 5 and not other["has_more"]
        assert not ({row["id"] for row in page["rows"]} & {row["id"] for row in other["rows"]})
        empty = await (
            await client.post(
                "/api/data-query", json={"source": "other-user-source"}, headers=headers
            )
        ).json()
        assert empty["rows"] == []
        for format in ("csv", "xlsx", "pdf"):
            export = await client.post(
                "/api/data-export", json=query | {"format": format}, headers=headers
            )
            assert export.status == 200
            body = await export.read()
            if format == "csv":
                records = list(csv.reader(StringIO(body.decode("utf-8-sig")), delimiter=";"))
                assert len(records) == 56 and records[-1][4] == "'=1+1"
            elif format == "xlsx":
                workbook = load_workbook(BytesIO(body))
                assert workbook["Consulta"].max_row == 56
                assert workbook["Consulta"]["E56"].data_type == "s"
                assert workbook["Consulta"]["E56"].value == "=1+1"
            else:
                assert body.startswith(b"%PDF")


def test_csv_and_excel_never_execute_external_formulas():
    row = {
        "id": 1,
        "author": '\t=HYPERLINK("https://bad.example")',
        "text": "<script>Ejército</script>",
        "terms": [],
        "review": "none",
        "tone": "neutral",
        "source": "Medio",
        "resource": "url",
        "title": "Nota",
    }
    csv_body, _ = export_data([row], "csv")
    assert "'\t=HYPERLINK" in csv_body.decode("utf-8-sig")
    excel, _ = export_data([row], "xlsx")
    assert load_workbook(BytesIO(excel)).active["E2"].data_type == "s"
    with pytest.raises(ValueError, match="1.000"):
        export_data([row] * 1001, "pdf")
