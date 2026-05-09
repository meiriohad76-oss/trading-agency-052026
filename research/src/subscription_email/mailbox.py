from __future__ import annotations

import hashlib
import imaplib
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
        uids = _search_uids(client, config.mailbox_search)
        attempted = saved = skipped = failed = 0
        for uid in uids:
            attempted += 1
            try:
                raw = _fetch_message(client, uid)
                if not _allowed_sender(raw, config):
                    skipped += 1
                    continue
                if _write_message(raw, config.input_path):
                    saved += 1
                else:
                    skipped += 1
                if config.mailbox_mark_seen:
                    client.uid("STORE", uid, "+FLAGS", r"(\Seen)")
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


def _search_uids(client: ImapClient, query: str) -> list[str]:
    status, data = client.uid("SEARCH", query)
    if status.upper() != "OK" or not data:
        return []
    first = data[0]
    if not isinstance(first, bytes):
        return []
    return [item.decode("ascii") for item in first.split() if item]


def _fetch_message(client: ImapClient, uid: str) -> bytes:
    status, data = client.uid("FETCH", uid, "(BODY.PEEK[])")
    if status.upper() != "OK":
        raise RuntimeError(f"could not fetch uid {uid}")
    for item in data:
        if isinstance(item, tuple) and isinstance(item[1], bytes):
            return item[1]
    raise RuntimeError(f"empty fetch response for uid {uid}")


def _allowed_sender(raw: bytes, config: SubscriptionEmailConfig) -> bool:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    record = parse_email_message(message)
    if not config.allowed_sender_domains:
        return True
    domain = record.sender_domain.lower()
    return any(
        domain == item or domain.endswith(f".{item}")
        for item in config.allowed_sender_domains
    )


def _write_message(raw: bytes, output_path: Path) -> bool:
    digest = hashlib.sha256(raw).hexdigest()
    path = output_path / f"{digest[:24]}.eml"
    if path.exists():
        return False
    path.write_bytes(raw)
    return True


def _env_value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None or value.strip() == "":
        return None
    return value
