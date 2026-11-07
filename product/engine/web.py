"""Internal headless source retrieval. Navigation is fulfilled via pinned public IPs.

No cookies, proxy environment, private targets, redirects to private addresses,
scripts or subresources. The browser never resolves or connects to source hosts.
"""
import asyncio
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit

MAX_SOURCE_BYTES = 3 * 1024 * 1024


def public_target(url, resolver=socket.getaddrinfo):
    value = urlsplit(url)
    if value.scheme not in {"http", "https"} or not value.hostname or value.username or value.password:
        raise ValueError("Unsupported source address")
    port = value.port or (443 if value.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("Unsupported source port")
    addresses = {result[4][0] for result in resolver(value.hostname, port, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("Private network sources are not permitted")
    return value, sorted(addresses)[0], port


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, address):
        super().__init__(host, port, timeout=8, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, self.port), timeout=self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def fetch_public(url, redirects=0):
    if redirects > 4:
        raise ValueError("Too many redirects")
    target, address, port = public_target(url)
    if target.scheme == "https":
        connection = PinnedHTTPS(target.hostname, port, address)
    else:
        connection = http.client.HTTPConnection(address, port, timeout=8)
    try:
        location = (target.path or "/") + ("?" + target.query if target.query else "")
        connection.request("GET", location, headers={"Host": target.netloc, "User-Agent": "Verity-Source-Review/0.2", "Accept": "text/html", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        if response.status in {301, 302, 303, 307, 308}:
            return fetch_public(urljoin(url, response.getheader("Location", "")), redirects + 1)
        if response.status != 200:
            raise ValueError("Source could not be retrieved")
        content_type = response.getheader("Content-Type", "")
        if not any(x in content_type.lower() for x in ["text/html", "application/xhtml+xml"]):
            raise ValueError("Source is not a webpage")
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise ValueError("Unsupported source encoding")
        body = response.read(MAX_SOURCE_BYTES + 1)
        if len(body) > MAX_SOURCE_BYTES:
            raise ValueError("Source exceeds the comparison limit")
        return body, content_type, url
    finally:
        connection.close()


def source_url(value):
    """Decode common search-result redirects; every returned URL is validated on fetch."""
    url = urlsplit(value)
    params = parse_qs(url.query)
    if url.hostname in {"www.bing.com", "bing.com"} and url.path.startswith("/ck/"):
        import base64
        encoded = params.get("u", [""])[0]
        if encoded.startswith("a1"):
            try:
                return base64.urlsafe_b64decode(encoded[2:] + "=" * (-len(encoded[2:]) % 4)).decode()
            except (ValueError, UnicodeError):
                return None
        return None
    if "uddg" in params:
        return unquote(params["uddg"][0])
    return value if url.scheme in {"http", "https"} else None


class WebSources:
    def __init__(self, top_n=3):
        self.top_n = max(1, min(5, top_n))
        self.runtime = self.browser = self.context = None
        self.allowed = {}

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self.runtime = await async_playwright().start()
        try:
            self.browser = await self.runtime.chromium.launch(headless=True, timeout=15_000)
            self.context = await self.browser.new_context(java_script_enabled=False, service_workers="block", accept_downloads=False)
            await self.context.route("**/*", self._route)
            return self
        except Exception:
            await self.__aexit__(None, None, None)
            raise

    async def _route(self, route):
        try:
            frame = route.request.frame
            if route.request.resource_type != "document" or route.request.method != "GET" or frame.parent_frame is not None or self.allowed.get(frame.page) != route.request.url:
                await route.abort()
                return
            body, content_type, _ = await asyncio.to_thread(fetch_public, route.request.url)
            await route.fulfill(status=200, body=body, headers={"content-type": content_type, "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'", "x-content-type-options": "nosniff"})
        except Exception:
            try:
                await route.abort()
            except Exception:
                pass

    async def _close_page(self, page):
        self.allowed.pop(page, None)
        try:
            await asyncio.wait_for(page.close(), timeout=5)
        except Exception:
            pass

    async def search(self, query):
        try:
            async with asyncio.timeout(90):
                return await self._search(query)
        except Exception:
            return [], False

    async def _search(self, query):
        page = await self.context.new_page()
        try:
            address = "https://www.bing.com/search?" + urlencode({"q": '"' + query[:220] + '"'})
            self.allowed[page] = address
            await page.goto(address, wait_until="domcontentloaded", timeout=20_000)
            links = await page.locator("li.b_algo h2 a").evaluate_all("nodes => nodes.map(a => a.href)")
            if not links:
                # A recognized no-results page counts as a completed query; challenge pages don't.
                content = (await page.locator("body").inner_text())[:10_000].lower()
                if not any(x in content for x in ["there are no results", "no results found", "did not match any documents"]):
                    return [], False
                return [], True
            candidates = list(dict.fromkeys(filter(None, (source_url(u) for u in links))))[:self.top_n]
            if not candidates:
                return [], False
            sources, failed = [], False
            for url in candidates:
                candidate = await self.context.new_page()
                try:
                    self.allowed[candidate] = url
                    await candidate.goto(url, wait_until="domcontentloaded", timeout=20_000)
                    # No snippets-only plagiarism: require a retrieved comparison page.
                    await candidate.locator("script,style,noscript,nav,footer,header,aside,form").evaluate_all("nodes => nodes.forEach(n => n.remove())")
                    text = (await candidate.locator("body").inner_text())[:60_000]
                    if len(text.split()) < 12:
                        failed = True
                        continue
                    sources.append({"url": url, "title": (await candidate.title())[:200], "text": text})
                except Exception:
                    failed = True
                finally:
                    await self._close_page(candidate)
            return sources, not failed
        finally:
            await self._close_page(page)

    async def __aexit__(self, *unused):
        self.allowed.clear()
        for owner, method in [(self.browser, "close"), (self.runtime, "stop")]:
            if owner:
                try:
                    await asyncio.wait_for(getattr(owner, method)(), timeout=5)
                except Exception:
                    pass
