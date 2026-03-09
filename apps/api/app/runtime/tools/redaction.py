import re

SECRET_PATTERNS = [
    r"OPENAI_API_KEY",
    r"DATABASE_URL",
    r"AWS_SECRET_ACCESS_KEY",
    r"-----BEGIN PRIVATE KEY-----",
    r"BEGIN RSA PRIVATE KEY",
    r"BEGIN DSA PRIVATE KEY",
    r"BEGIN EC PRIVATE KEY",
    r"api_key",
    r"token",
    r"authorization",
    r"bearer",
    r"secret",
    r"password",
]


def redact(text: str) -> str:
    redacted = text
    for pat in SECRET_PATTERNS:
        redacted = re.sub(pat, "[REDACTED]", redacted, flags=re.IGNORECASE)
    return redacted
