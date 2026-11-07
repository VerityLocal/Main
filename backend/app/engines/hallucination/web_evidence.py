"""Optional asynchronous Wikipedia evidence; explicit policy + request consent."""

import asyncio
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from backend.app.schemas.analysis import Source


async def search_wikipedia(query, *, consent, enabled):
    if not consent or not enabled:
        raise PermissionError("External evidence requires explicit user consent and local policy")
    async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False) as client:
        for attempt in range(2):
            try:
                result = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "format": "json",
                        "list": "search",
                        "srsearch": query[:256],
                        "srlimit": 2,
                    },
                )
                result.raise_for_status()
                titles = [
                    item["title"] for item in result.json().get("query", {}).get("search", [])
                ][:2]
                if not titles:
                    return []
                response = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "format": "json",
                        "prop": "extracts",
                        "explaintext": 1,
                        "exintro": 1,
                        "titles": "|".join(titles),
                    },
                )
                response.raise_for_status()
                sources = []
                for page in response.json().get("query", {}).get("pages", {}).values():
                    text = page.get("extract", "")[:6000]
                    if not text:
                        continue
                    sources.append(
                        Source(
                            source_id=f"wikipedia_{page['pageid']}",
                            title=page["title"],
                            text=text,
                            url="https://en.wikipedia.org/wiki/"
                            + quote(page["title"].replace(" ", "_")),
                            retrieved_at=datetime.now(UTC),
                            reliability="unrated",
                        )
                    )
                return sources
            except (httpx.HTTPError, ValueError, KeyError):
                if attempt:
                    return []
                await asyncio.sleep(0.1)
    return []
