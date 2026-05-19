from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape
from pathlib import Path

from subscription_email.types import EmailRecord

HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_HREF_RE = re.compile(r"""href\s*=\s*["'](?P<url>[^"']+)["']""", re.IGNORECASE)


def read_local_emails(path: Path) -> list[EmailRecord]:
    files = _email_files(path)
    return [parse_email_file(file) for file in files]


def parse_email_file(path: Path) -> EmailRecord:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    return parse_email_message(message, source_path=path.as_posix())


def parse_email_message(message: Message, *, source_path: str | None = None) -> EmailRecord:
    subject = str(message.get("subject", "")).strip()
    sender = _sender(message)
    received_at = _received_at(message)
    message_id = str(message.get("message-id", "")).strip() or _fallback_message_id(
        sender,
        subject,
        received_at,
    )
    return EmailRecord(
        message_id=message_id.strip("<>"),
        sender=sender,
        sender_domain=_sender_domain(sender),
        subject=subject,
        received_at=received_at,
        body_text=_body_text(message),
        source_path=source_path,
    )


def _email_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(file for file in path.rglob("*.eml") if file.is_file())


def _sender(message: Message) -> str:
    parsed = getaddresses([str(message.get("from", ""))])
    if not parsed:
        return ""
    name, address = parsed[0]
    return address or name


def _sender_domain(sender: str) -> str:
    return sender.rsplit("@", 1)[-1].lower() if "@" in sender else sender.lower()


def _received_at(message: Message) -> datetime:
    value = str(message.get("date", "")).strip()
    if value:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            parsed = datetime.now(UTC)
    else:
        parsed = datetime.now(UTC)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _body_text(message: Message) -> str:
    parts = list(_text_parts(message))
    if not parts:
        return ""
    return "\n".join(parts)


def _text_parts(message: Message) -> Iterable[str]:
    if isinstance(message, EmailMessage) and not message.is_multipart():
        body = message.get_body(preferencelist=("plain", "html"))
        if body is not None:
            yield _payload_text(body)
            return
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type in {"text/plain", "text/html"}:
                yield _payload_text(part)
    elif message.get_content_type() in {"text/plain", "text/html"}:
        yield _payload_text(message)


def _payload_text(message: Message) -> str:
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        text = payload.decode(message.get_content_charset() or "utf-8", errors="replace")
    else:
        text = str(message.get_payload())
    if message.get_content_type() == "text/html":
        hrefs = [unescape(match.group("url")) for match in HTML_HREF_RE.finditer(text)]
        text = HTML_TAG_RE.sub(" ", text)
        if hrefs:
            text = f"{text} {' '.join(hrefs)}"
    return " ".join(text.split())


def _fallback_message_id(sender: str, subject: str, received_at: datetime) -> str:
    digest = hashlib.sha256()
    digest.update(sender.encode("utf-8"))
    digest.update(subject.encode("utf-8"))
    digest.update(received_at.isoformat().encode("utf-8"))
    return digest.hexdigest()[:24]
