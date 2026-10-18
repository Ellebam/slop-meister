"""Secret redaction and safe one-line rendering."""

import json
import re

SENSITIVE_ENV_NAMES = frozenset(
    (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "OPENAI_BASE_URL",
    )
)
SENSITIVE_PROXY_NAMES = {"ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE),
    re.compile(r"secret_[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    re.compile(r"notion_[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    re.compile(r"op://[^\s|`]+"),
    re.compile(r"(?<=://)[^\s/@|`]+(?=@)"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),
)
_CREDENTIAL_VALUE = r"""(?:"(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*'|[^\s|`]+)"""
_CREDENTIAL_NAME = r"(?:TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|API[_-]?KEY|CREDENTIALS?)"
_CREDENTIAL_LABEL = rf"(?<![\w-])(?:(?:[A-Za-z][A-Za-z0-9_]*_)?{_CREDENTIAL_NAME}|"
_CREDENTIAL_LABEL += "|".join(sorted(SENSITIVE_ENV_NAMES | SENSITIVE_PROXY_NAMES)) + r")\b"
_CLOUD_ENV_NAME = r"(?:AWS|CLOUDSDK|GCLOUD|GCP|GOOGLE)_[A-Z0-9_]*"


def redact(text: str) -> str:
    # Native envelopes and finding strings can each contain another JSON layer.
    try:
        value = json.loads(text)
        masked = _redact_json(value)
    except json.JSONDecodeError:
        return _redact_text(text)
    except ValueError, RecursionError:
        return "[REDACTED: JSON exceeds decoding limits]"
    return text if masked == value else json.dumps(masked)


def _redact_json(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if re.fullmatch(f"{_CREDENTIAL_LABEL}|{_CLOUD_ENV_NAME}", key, re.IGNORECASE)
            else _redact_json(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    return redact(value) if isinstance(value, str) else value


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    redacted = re.sub(
        rf"""(({_CREDENTIAL_LABEL})(["']?)\s*[:=]\s*){_CREDENTIAL_VALUE}""",
        lambda match: f"{match[1]}{match[3]}[REDACTED]{match[3]}",
        redacted,
        flags=re.IGNORECASE,
    )
    # A long flag takes its value after "=" or whitespace.
    flag = rf"(?<![\w-])--(?:[\w-]*[_-])?(?:{_CREDENTIAL_NAME}|USER|AUTH)\b(?:=|\s+)(?!-)"
    redacted = re.sub(
        rf"({flag}){_CREDENTIAL_VALUE}", r"\1[REDACTED]", redacted, flags=re.IGNORECASE
    )
    for key in sorted(SENSITIVE_ENV_NAMES | SENSITIVE_PROXY_NAMES):
        redacted = re.sub(
            rf"{re.escape(key)}\s*[:=]\s*{_CREDENTIAL_VALUE}",
            f"{key}=[REDACTED]",
            redacted,
            flags=re.IGNORECASE,
        )
    return re.sub(
        rf"\b{_CLOUD_ENV_NAME}\s*=\s*[^\s|`]+",
        "[REDACTED_ENV]=[REDACTED]",
        redacted,
    )


def sanitize_text(value: str) -> str:
    value = redact(value)
    value = "".join(char if char.isprintable() else " " for char in value)
    value = value.replace("|", r"\|")
    value = re.sub(r"(?m)^#{1,6}\s+", r"\# ", value)
    return re.sub(r"\s+", " ", value).strip()
