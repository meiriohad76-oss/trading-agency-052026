from __future__ import annotations

import hashlib
import imaplib
import re
import os
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Protocol

from subscription_email.config import SubscriptionEmailConfig
from subscription_email.parser import parse_email_message
from subscription_email.types import EmailRecord


class ImapClient(Protocol):
    def login(self, user: str, password: str) -> object: ...

    def select(self, mailbox: str) -> object: ...

    def uid(self, command: str, *args: str) -> tuple[str, list[bytes | tuple[bytes, bytes]]]: ...

    def logout(self) -> object: ...


ImapFactory = Callable[[SubscriptionEmailConfig], ImapClient]


@dataclass(frozen=True)
class MailboxSyncResult:
    mode: str
    attempted: int
    saved: int
    skipped: int
    failed: int
    output_path: Path
    reason: str
    matched: int = 0
    limited: bool = False
    saved_paths: tuple[Path, ...] = ()
    selected_paths: tuple[Path, ...] = ()
    selected_uids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MailboxPreviewResult:
    mode: str
    matched: int
    sampled: int
    skipped: int
    failed: int
    output_path: Path
    reason: str
    messages: list[dict[str, object]]
    limited: bool = False


def sync_mailbox_emails(
    config: SubscriptionEmailConfig,
    *,
    env: Mapping[str, str] | None = None,
    imap_factory: ImapFactory | None = None,
) -> MailboxSyncResult:
    if config.mode == "local_eml":
        return MailboxSyncResult("local_eml", 0, 0, 0, 0, config.input_path, "local folder mode")
    if config.mode not in {"imap", "gmail", "outlook"}:
        raise ValueError(f"unsupported mailbox sync mode: {config.mode}")
    environment = env if env is not None else os.environ
    username = _env_value(environment, config.mailbox_username_env)
    password = _env_value(environment, config.mailbox_password_env)
    if username is None or password is None:
        raise RuntimeError(
            f"missing {config.mailbox_username_env} or {config.mailbox_password_env}"
        )
    config.input_path.mkdir(parents=True, exist_ok=True)
    client = (imap_factory or _default_imap_factory)(config)
    try:
        client.login(username, password)
        client.select(config.mailbox_label or "INBOX")
        matched_uids = _search_uids(client, config)
        uids = _limited_uids(matched_uids, config.mailbox_max_messages)
        attempted = saved = skipped = failed = 0
        saved_paths: list[Path] = []
        selected_paths: list[Path] = []
        selected_uids: list[str] = []
        for uid in uids:
            attempted += 1
            try:
                raw = _fetch_message(client, uid)
                if not _allowed_sender(raw, config):
                    skipped += 1
                    continue
                message_path = _message_path(raw, config.input_path)
                selected_paths.append(message_path)
                selected_uids.append(uid)
                if _write_message(raw, message_path):
                    saved += 1
                    saved_paths.append(message_path)
                else:
                    skipped += 1
            except Exception:
                failed += 1
        return MailboxSyncResult(
            config.mode,
            attempted,
            saved,
            skipped,
            failed,
            config.input_path,
            "mailbox sync completed",
            matched=len(matched_uids),
            limited=len(uids) < len(matched_uids),
            saved_paths=tuple(saved_paths),
            selected_paths=tuple(selected_paths),
            selected_uids=tuple(selected_uids),
        )
    finally:
        with suppress(Exception):
            client.logout()


def mark_mailbox_emails_seen(
    config: SubscriptionEmailConfig,
    uids: tuple[str, ...],
    *,
    env: Mapping[str, str] | None = None,
    imap_factory: ImapFactory | None = None,
) -> int:
    if not uids or config.mode == "local_eml":
        return 0
    environment = env if env is not None else os.environ
    username = _env_value(environment, config.mailbox_username_env)
    password = _env_value(environment, config.mailbox_password_env)
    if username is None or password is None:
        raise RuntimeError(
            f"missing {config.mailbox_username_env} or {config.mailbox_password_env}"
        )
    client = (imap_factory or _default_imap_factory)(config)
    try:
        client.login(username, password)
        client.select(config.mailbox_label or "INBOX")
        marked = 0
        for uid in uids:
            status, _payload = client.uid("STORE", uid, "+FLAGS", r"(\Seen)")
            if str(status).upper() != "OK":
                raise RuntimeError(f"failed to mark mailbox UID {uid} as seen")
            marked += 1
        return marked
    finally:
        with suppress(Exception):
            client.logout()


def preview_mailbox_emails(
    config: SubscriptionEmailConfig,
    *,
    env: Mapping[str, str] | None = None,
    imap_factory: ImapFactory | None = None,
) -> MailboxPreviewResult:
    if config.mode == "local_eml":
        files = sorted(config.input_path.rglob("*.eml")) if config.input_path.exists() else []
        sampled = files[-config.mailbox_max_messages :]
        return MailboxPreviewResult(
            "local_eml",
            len(files),
            len(sampled),
            0,
            0,
            config.input_path,
            "local folder preview completed; no email or article content was opened",
            [
                {
                    "source": "local_eml",
                    "path": path.relative_to(config.input_path).as_posix(),
                }
                for path in sampled
            ],
            limited=len(sampled) < len(files),
        )
    environment = env if env is not None else os.environ
    username = _env_value(environment, config.mailbox_username_env)
    password = _env_value(environment, config.mailbox_password_env)
    if username is None or password is None:
        raise RuntimeError(
            f"missing {config.mailbox_username_env} or {config.mailbox_password_env}"
        )
    client = (imap_factory or _default_imap_factory)(config)
    try:
        client.login(username, password)
        client.select(config.mailbox_label or "INBOX")
        matched_uids = _search_uids(client, config)
        uids = _limited_uids(matched_uids, config.mailbox_max_messages)
        messages: list[dict[str, object]] = []
        skipped = failed = 0
        for uid in uids:
            try:
                raw = _fetch_message_headers(client, uid)
                message = BytesParser(policy=policy.default).parsebytes(raw)
                record = parse_email_message(message)
                allowed = _allowed_record_sender(record, config)
                skipped += 0 if allowed else 1
                messages.append(
                    {
                        "uid": uid,
                        "allowed_sender": allowed,
                        "sender_domain": record.sender_domain,
                        "subject": record.subject,
                        "received_at": record.received_at.isoformat(),
                        "message_id_hash": _hash(record.message_id),
                    }
                )
            except Exception:
                failed += 1
        return MailboxPreviewResult(
            config.mode,
            len(matched_uids),
            len(messages),
            skipped,
            failed,
            config.input_path,
            (
                "mailbox dry-run preview completed; no emails were saved and "
                "no article links were opened"
            ),
            messages,
            limited=len(uids) < len(matched_uids),
        )
    finally:
        with suppress(Exception):
            client.logout()


def _default_imap_factory(config: SubscriptionEmailConfig) -> ImapClient:
    host = config.mailbox_host or _default_host(config.mode)
    if host == "":
        raise ValueError("mailbox_host is required when mode is imap")
    return imaplib.IMAP4_SSL(host, config.mailbox_port)


def _default_host(mode: str) -> str:
    return {
        "gmail": "imap.gmail.com",
        "outlook": "outlook.office365.com",
        "imap": "",
    }[mode]


def _search_uids(client: ImapClient, config: SubscriptionEmailConfig) -> list[str]:
    query = _search_query(config)
    status, data = client.uid("SEARCH", query)
    if status.upper() != "OK" or not data:
        return []
    first = data[0]
    if not isinstance(first, bytes):
        return []
    return [item.decode("ascii") for item in first.split() if item]


def _search_query(config: SubscriptionEmailConfig) -> str:
    query = config.mailbox_search.strip()
    if not config.mailbox_unseen_only:
        return _without_unseen(query)
    tokens = query.upper().replace("(", " ").replace(")", " ").split()
    if "UNSEEN" in tokens:
        return query
    return f"UNSEEN {query}"


def _without_unseen(query: str) -> str:
    stripped = re.sub(r"(?i)\bUNSEEN\b", " ", query)
    stripped = re.sub(r"(?i)\bis:unread\b", " ", stripped)
    stripped = re.sub(r"\(\s+", "(", stripped)
    stripped = re.sub(r"\s+\)", ")", stripped)
    stripped = re.sub(r"\(\s*\)", " ", stripped)
    stripped = " ".join(stripped.split())
    return stripped if stripped else "ALL"


def _limited_uids(uids: list[str], limit: int) -> list[str]:
    ordered = sorted(uids, key=_uid_sort_key)
    return ordered[-limit:]


def _uid_sort_key(uid: str) -> tuple[int, str]:
    try:
        return (int(uid), uid)
    except ValueError:
        return (0, uid)


def _fetch_message(client: ImapClient, uid: str) -> bytes:
    status, data = client.uid("FETCH", uid, "(BODY.PEEK[])")
    if status.upper() != "OK":
        raise RuntimeError(f"could not fetch uid {uid}")
    for item in data:
        if isinstance(item, tuple) and isinstance(item[1], bytes):
            return item[1]
    raise RuntimeError(f"empty fetch response for uid {uid}")


def _fetch_message_headers(client: ImapClient, uid: str) -> bytes:
    status, data = client.uid(
        "FETCH",
        uid,
        "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])",
    )
    if status.upper() != "OK":
        raise RuntimeError(f"could not fetch headers for uid {uid}")
    for item in data:
        if isinstance(item, tuple) and isinstance(item[1], bytes):
            return item[1]
    raise RuntimeError(f"empty header fetch response for uid {uid}")


def _allowed_sender(raw: bytes, config: SubscriptionEmailConfig) -> bool:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    record = parse_email_message(message)
    return _allowed_record_sender(record, config)


def _allowed_record_sender(record: EmailRecord, config: SubscriptionEmailConfig) -> bool:
    if not config.allowed_sender_domains:
        return True
    domain = record.sender_domain.lower()
    return any(
        domain == item or domain.endswith(f".{item}")
        for item in config.allowed_sender_domains
    )


def _message_path(raw: bytes, output_path: Path) -> Path:
    digest = hashlib.sha256(raw).hexdigest()
    return output_path / f"{digest[:24]}.eml"


def _write_message(raw: bytes, path: Path) -> bool:
    if path.exists():
        return False
    path.write_bytes(raw)
    return True


def _env_value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None or value.strip() == "":
        return None
    return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
