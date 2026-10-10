"""Unattended first-run setup of the pinned sandbox apps, the wizard's own form posts and REST."""

import base64
from dataclasses import dataclass, field
import html.parser
import http.cookiejar
import json
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ADMIN = "admin"
USER = "sandbox"
KEY = "SBX"
WAIT_SECONDS = 900
POLL_SECONDS = 5
REQUEST_SECONDS = 600
REDIRECTS = (301, 302, 303)
MAX_REDIRECTS = 10


class SetupError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class _Form(html.parser.HTMLParser):
    """The named form's submitted fields with their defaults, as a browser would send them."""

    def __init__(self, action: str):
        super().__init__()
        self.action, self.target, self.fields, self.inside = action, None, {}, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.inside = (attrs.get("action") or "").split("?")[0].endswith(self.action)
            self.target = attrs.get("action") if self.inside else self.target
        elif self.inside and tag in ("input", "textarea") and attrs.get("name"):
            unchecked = attrs.get("type") in ("radio", "checkbox") and "checked" not in attrs
            if not unchecked and attrs.get("type") not in ("submit", "button"):
                self.fields[attrs["name"]] = attrs.get("value") or ""

    def handle_endtag(self, tag):
        self.inside = self.inside and tag != "form"


@dataclass
class App:
    origin: str
    context: ssl.SSLContext
    jar: http.cookiejar.CookieJar = field(default_factory=http.cookiejar.CookieJar)

    def send(self, path: str, body: bytes | None = None, headers: dict | None = None):
        https = urllib.request.HTTPSHandler(context=self.context)
        cookies = urllib.request.HTTPCookieProcessor(self.jar)
        opener = urllib.request.build_opener(https, cookies, _NoRedirect)
        url = urllib.parse.urljoin(self.origin, path)
        request = urllib.request.Request(url, body, headers or {})
        try:
            with opener.open(request, timeout=REQUEST_SECONDS) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def follow(self, url: str, body: bytes | None = None) -> tuple[str, str]:
        """Follow the wizard's redirects as a browser would, some setup steps run on these GETs."""
        url = urllib.parse.urljoin(self.origin, url)
        for _ in range(MAX_REDIRECTS):
            status, headers, content = self.send(url, body, {"X-Atlassian-Token": "no-check"})
            if status not in REDIRECTS:
                break
            url, body = urllib.parse.urljoin(url, headers["Location"]), None
        if status != 200:
            raise SetupError(f"{urllib.parse.urlsplit(url).path} returned {status}")
        return url, content.decode(errors="replace")

    def step(self, page: tuple[str, str], action: str, overrides: dict) -> tuple[str, str]:
        """Post the current page's form, a rejected step shows up as the next form missing."""
        url, html = page
        parser = _Form(action)
        parser.feed(html)
        if parser.target is None:
            raise SetupError(f"{urllib.parse.urlsplit(url).path} has no {action} form")
        data = urllib.parse.urlencode(parser.fields | overrides).encode()
        return self.follow(urllib.parse.urljoin(url, parser.target), data)

    def rest(self, path: str, data: dict, auth: str) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers |= {"X-Atlassian-Token": "no-check", "Authorization": auth}
        # A fresh cookie jar, Confluence would otherwise act as the wizard's admin session.
        fresh = App(self.origin, self.context)
        status, _, body = fresh.send(path, json.dumps(data).encode(), headers)
        if status not in (200, 201):
            raise SetupError(f"{path} returned {status}")
        return json.loads(body)


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def state(app: App) -> str:
    try:
        status, _, body = app.send("/status")
        return json.loads(body).get("state", "DOWN") if status == 200 else "DOWN"
    except OSError, ValueError:
        return "DOWN"


def wait(app: App) -> str:
    deadline = time.monotonic() + WAIT_SECONDS
    while (current := state(app)) not in ("RUNNING", "FIRST_RUN"):
        if time.monotonic() > deadline:
            raise SetupError(f"{app.origin} is still {current} after {WAIT_SECONDS} s")
        time.sleep(POLL_SECONDS)
    return current


def _jira_wizard(app: App, licence: str, password: str) -> None:
    url = app.origin
    admin = {"username": ADMIN, "password": password, "confirm": password}
    admin |= {"fullname": "Sandbox Admin", "email": f"{ADMIN}@example.com"}
    steps = [
        ("SetupApplicationProperties", {"title": "Sandbox", "mode": "private", "baseURL": url}),
        ("SetupLicense", {"setupLicenseKey": licence}),
        ("SetupAdminAccount", admin),
        ("SetupMailNotifications", {"noemail": "true"}),
    ]
    page = app.follow("/")
    for name, overrides in steps:
        page = app.step(page, f"{name}.jspa", overrides)


def jira(app: App, licence: str) -> str:
    """Set Jira up and return the test user's PAT, both passwords die with this call."""
    admin_password, user_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    _jira_wizard(app, licence, admin_password)
    admin = basic(ADMIN, admin_password)
    user = {"name": USER, "password": user_password, "emailAddress": f"{USER}@example.com"}
    app.rest("/rest/api/2/user", user | {"displayName": "Sandbox Tester"}, admin)
    project = {"key": KEY, "name": "Sandbox", "projectTypeKey": "software", "lead": ADMIN}
    app.rest("/rest/api/2/project", project, admin)
    issue = {"project": {"key": KEY}, "summary": "Sandbox issue", "issuetype": {"name": "Task"}}
    app.rest("/rest/api/2/issue", {"fields": issue}, admin)
    token = {"name": "slopmeister-sandbox"}
    return app.rest("/rest/pat/latest/tokens", token, basic(USER, user_password))["rawToken"]


def _confluence_wizard(app: App, password: str) -> None:
    admin = {"username": ADMIN, "password": password, "confirm": password}
    admin |= {"fullName": "Sandbox Admin", "email": f"{ADMIN}@example.com"}
    steps = [
        ("setupcluster", {"newCluster": "skipCluster"}),
        ("setupdata", {"contentChoice": "blank"}),
        ("setupusermanagementchoice", {"userManagementChoice": "internal", "internal": "internal"}),
        ("setupadministrator", admin),
    ]
    page = app.follow("/")
    for name, overrides in steps:
        page = app.step(page, f"{name}.action", overrides)


def confluence(app: App) -> tuple[str, str]:
    """Set Confluence up and return the test user's PAT and the test page ID."""
    admin_password, user_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    _confluence_wizard(app, admin_password)
    admin = basic(ADMIN, admin_password)
    user = {"userName": USER, "password": user_password, "email": f"{USER}@example.com"}
    app.rest("/rest/api/admin/user", user | {"fullName": "Sandbox Tester"}, admin)
    app.rest("/rest/api/space", {"key": KEY, "name": "Sandbox"}, admin)
    body = {"storage": {"value": "<p>Sandbox page</p>", "representation": "storage"}}
    page = {"type": "page", "title": "Sandbox page", "space": {"key": KEY}, "body": body}
    page_id = app.rest("/rest/api/content", page, admin)["id"]
    token = {"name": "slopmeister-sandbox"}
    pat = app.rest("/rest/pat/latest/tokens", token, basic(USER, user_password))["rawToken"]
    return pat, page_id
