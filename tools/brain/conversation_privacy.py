"""Local placeholder redaction before conversation excerpts leave this machine."""

import re

try:
    from . import memory, observer
except ImportError:
    import memory
    import observer

CODE_BLOCK = re.compile(r"```[^\n]*\n.*?(?:```|\Z)|~~~[^\n]*\n.*?(?:~~~|\Z)", re.S)
CONTACT = re.compile(r"https?://[^\s<>]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
                     r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b1[3-9]\d{9}\b|\b\d{15,19}[Xx]?\b")
PATH = re.compile(r"\b[A-Za-z]:[\\/][^\s<>，。；]+|(?<!\w)(?:~/|/Users/|/home/|/mnt/)[^\s<>，。；]+")
TOKEN = re.compile(r"\b(?:Bearer\s+\S+|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
                   r"AKIA[A-Z0-9]{16})", re.I)
LABEL = re.compile(r"(?:姓名|我叫|我的名字|手机号|电话号码|住址|身份证|护照|密码|密钥|令牌|"
                   r"password|api[_ -]?key|access[_ -]?token)\s*(?:是|为|[:=：])?\s*[^\s，。；;]+", re.I)
SEGMENTS = re.compile(r"[^。！？!?\n；;]+[。！？!?\n；;]*")


def redact(text):
    if not isinstance(text, str):
        return ""
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)",
                  "[REDACTED_VALUE]", text, flags=re.S)
    text = CODE_BLOCK.sub("[CODE]", text)
    text = re.sub(r"`[^`\n]+`", "[INLINE_CODE]", text)
    # Replace assignments before the generic detector: its \\S+ would eat Chinese punctuation.
    text = LABEL.sub("[REDACTED_VALUE]", text)
    text = memory.SECRET.sub("[REDACTED_VALUE]", text)
    text = TOKEN.sub("[REDACTED_VALUE]", text)
    text = CONTACT.sub("[CONTACT_OR_URL]", text)
    text = PATH.sub("[LOCAL_PATH]", text)
    parts = []
    for match in SEGMENTS.finditer(text):
        segment = match.group()
        # Replace only the risky segment, not the entire user turn.
        if observer.PRIVATE.search(segment):
            parts.append("[SENSITIVE_SEGMENT]\n")
        elif (observer.CODE_OR_LINK.search(segment)
              or re.search(r"(?:^|\n)\s*(?:[{}]|[\w.]+\s*\([^\n]*\)\s*;|\w+\s*=)", segment)):
            parts.append("[CODE_OR_IDENTIFIER]\n")
        else:
            parts.append(segment)
    return "".join(parts).strip()


def chunks(text, maximum=3000):
    """Bound every excerpt without silently discarding the rest of the query."""
    return [text[i:i + maximum] for i in range(0, len(text), maximum)] or [""]
