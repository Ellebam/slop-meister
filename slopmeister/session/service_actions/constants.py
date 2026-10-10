"""Service-action constants shared by admission and the delivered consumer."""

from pathlib import Path
import sys

# Fixed absolute programs, never a PATH search. The Mac values are Homebrew's.
PYTHON = Path("/opt/homebrew/bin/python3")
CURL = Path("/usr/bin/curl")
OPENSSL = Path("/usr/bin/openssl")
OPENSSL_CONFIG = Path(__file__).with_name("openssl.cnf")
OP = Path("/opt/homebrew/bin/op")
PYTHON_FLAGS = ("-E", "-s", "-S")
BASE_PATH = "/opt/homebrew/bin:/usr/bin:/bin"
if sys.platform == "linux":
    PYTHON, OP, BASE_PATH = Path("/usr/bin/python3"), Path("/usr/bin/op"), "/usr/bin:/bin"
LIMIT = 2 * 1024 * 1024
RESPONSE_LIMIT = 1024 * 1024
REQUEST_TIMEOUT = 25
SUCCESS = {
    "jira-read": "JIRA_CONTEXT_PASS",
    "confluence-read": "CONFLUENCE_FETCH_PASS",
    "jira-write": "JIRA_WRITE_PASS",
    "confluence-write": "CONFLUENCE_WRITE_PASS",
}
# A write that failed after an earlier write succeeded, reported with the writes made.
INCOMPLETE = "WRITE_INCOMPLETE"
KNOWN_FAILURES = {
    "ACTION_FAILED",
    "ACTION_OUTPUT_LIMIT",
    "ACTION_TIMEOUT",
    "CERTIFICATE_INVALID",
    "CONFIG_INVALID",
    "CONTENT_CHANGED",
    "CREDENTIAL_INPUT_INVALID",
    "IDENTITY_MISMATCH",
    "INPUT_INVALID",
    "LOCAL_PREREQUISITE_MISSING",
    "NETWORK_OR_TLS_FAILED",
    "NO_EDITED_PAGES",
    "RELATED_LIMIT",
    "REQUEST_INVALID",
    "REQUEST_TIMEOUT",
    "RESPONSE_INVALID",
    "RESPONSE_TOO_LARGE",
    "SEARCH_LIMIT",
    "SELECTOR_UNAVAILABLE",
}
ORIGIN = r"https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/[A-Za-z0-9_-]+)*/?"
ISSUE_KEY = r"[A-Z][A-Z0-9_]{0,106}-[1-9][0-9]{0,15}"
