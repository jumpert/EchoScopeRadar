"""Read-only, reproducible checks of each outlet; never uses private credentials."""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from echoscope.application.administration import _example
from echoscope.application.ports import Request
from echoscope.connectors.discussion import discover_mechanisms, public_get, read_mechanism
from echoscope.connectors.html_discussion import Document
from echoscope.connectors.press_page import listing_articles
from echoscope.connectors.syndication import Feed

EXTRA = {
    "El País": "https://www.elpais.com.uy/",
    "Medios Públicos": "https://mediospublicos.uy/",
    "M24": "https://www.m24.com.uy/",
    "La República": "https://www.larepublica.com.uy/",
    "970 Universal": "https://970universal.com/",
    "Radio Monte Carlo": "https://www.radiomontecarlo.com.uy/",
    "CW33 Florida": "https://www.cw33florida.com.uy/",
    "LaRed21": "https://www.lr21.com.uy/",
}


async def main():
    rows = []
    for source in _example("defensa-uruguay.yaml").sources:
        if source.type != "press_feed":
            continue
        row = {"id": source.id, "outlet": source.label, "feed": source.params["url"]}
        try:
            items = []
            async for batch in Feed().poll(Request(source, None, 20)):
                items.extend(batch.messages)
            row["news_count"] = len(items)
            for item in items[:2]:
                sample = {"article": item.url}
                try:
                    mechanisms = await discover_mechanisms(item.url)
                    sample["mechanisms"] = mechanisms
                    sample["checks"] = []
                    for mechanism in mechanisms:
                        if mechanism["type"] == "unsupported":
                            sample["checks"].append(
                                {"type": "unsupported", "provider": mechanism["provider"]}
                            )
                            continue
                        if mechanism["type"] == "disqus":
                            sample["checks"].append({"type": "disqus", "status": "requires_key"})
                            continue
                        page = await read_mechanism(mechanism, article=item.url)
                        sample["checks"].append(
                            {
                                "type": mechanism["type"],
                                "partial": page.partial,
                                "kinds": {
                                    kind: sum(m.kind == kind for m in page.messages)
                                    for kind in {m.kind for m in page.messages}
                                },
                            }
                        )
                except Exception as exc:
                    sample["error"] = type(exc).__name__
                row.setdefault("samples", []).append(sample)
        except Exception as exc:
            row["error"] = type(exc).__name__
        rows.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)
    for name, url in EXTRA.items():
        row = {"outlet": name, "home": url}
        try:
            body = await public_get(url, json_body=False)
            doc = Document(body)
            row["feeds"] = [
                n.attrs.get("href")
                for n in doc.elements
                if n.tag == "link"
                and n.attrs.get("type") in {"application/rss+xml", "application/atom+xml"}
            ]
            row["home_status"] = "read"
            articles = listing_articles(body, url)
            row["news_count"] = len(articles)
            for item in articles[:2]:
                sample = {"article": item.url}
                try:
                    mechanisms = await discover_mechanisms(item.url)
                    sample["mechanisms"] = mechanisms
                    sample["checks"] = []
                    for mechanism in mechanisms:
                        if mechanism["type"] == "unsupported":
                            sample["checks"].append(
                                {"type": "unsupported", "provider": mechanism["provider"]}
                            )
                            continue
                        if mechanism["type"] == "disqus":
                            sample["checks"].append({"type": "disqus", "status": "requires_key"})
                            continue
                        page = await read_mechanism(mechanism, article=item.url)
                        sample["checks"].append(
                            {
                                "type": mechanism["type"],
                                "partial": page.partial,
                                "kinds": {
                                    kind: sum(m.kind == kind for m in page.messages)
                                    for kind in {m.kind for m in page.messages}
                                },
                            }
                        )
                except Exception as exc:
                    sample["error"] = type(exc).__name__
                row.setdefault("samples", []).append(sample)
        except Exception as exc:
            row["error"] = type(exc).__name__
        rows.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)
    Path(sys.argv[1]).write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "outlets": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
