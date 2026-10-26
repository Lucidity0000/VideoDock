"""Conservative retry classification; permanent failures require an explicit retry."""

import re


def transient_failure(message):
    text = message.lower()
    if any(value in text for value in ("output repetition", "repeated its output", "out of memory",
                                        "no space", "disk full", "permission denied", "unsupported",
                                        "private video", "unavailable video", "sign in", "unauthorized")):
        return ""
    if re.search(r"\b(400|401|403|404|410)\b", text):
        return ""
    if re.search(r"\b429\b", text) or "too many requests" in text:
        return "rate_limit"
    if re.search(r"\b(500|502|503|504)\b", text):
        return "server"
    if any(value in text for value in ("timed out", "timeout", "connection reset", "connection aborted",
                                       "connection refused", "temporary failure in name resolution",
                                       "getaddrinfo failed", "network is unreachable", "remote end closed")):
        return "network"
    return ""
