"""
email_service.py
=================
Send and read email via standard SMTP (sending) and IMAP (reading),
using only Python's standard library (`smtplib`, `imaplib`, `email`) —
no third-party email SDK required.

Credentials and server settings come from environment variables:
    EMAIL_ADDRESS       — the account's email address
    EMAIL_APP_PASSWORD   — an app-specific password (NOT the account's
                            normal login password — see note below)
    EMAIL_PROVIDER       — optional shortcut: 'gmail', 'outlook', or
                            'yahoo', auto-filling SMTP/IMAP host+port
    SMTP_HOST/SMTP_PORT   — explicit override (required if
                            EMAIL_PROVIDER isn't one of the presets)
    IMAP_HOST/IMAP_PORT   — explicit override for reading mail

IMPORTANT SECURITY NOTE: Most providers (Gmail, Outlook, Yahoo) require
an "app password" for third-party SMTP/IMAP access rather than the
account's normal login password, especially with 2FA enabled. This
service never stores or logs the password itself; it's read fresh from
the environment on each connection.
"""

from __future__ import annotations

import email
import imaplib
import smtplib
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

from config.env_loader import get_env
from core.logger import get_logger

logger = get_logger(__name__)


class EmailServiceError(RuntimeError):
    """Raised when email sending/reading fails or credentials are missing."""


@dataclass(frozen=True)
class ProviderPreset:
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "gmail": ProviderPreset("smtp.gmail.com", 587, "imap.gmail.com", 993),
    "outlook": ProviderPreset("smtp.office365.com", 587, "outlook.office365.com", 993),
    "yahoo": ProviderPreset("smtp.mail.yahoo.com", 587, "imap.mail.yahoo.com", 993),
}


@dataclass
class EmailMessage:
    uid: str
    subject: str
    sender: str
    date: datetime | None
    snippet: str
    is_unread: bool


@dataclass
class EmailCredentials:
    address: str
    app_password: str
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int


def _decode_mime_words(raw: str | None) -> str:
    """Decode MIME-encoded email headers (e.g. '=?UTF-8?B?...?=') into plain text."""
    if not raw:
        return ""
    decoded_parts = decode_header(raw)
    result = []
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _load_credentials() -> EmailCredentials:
    """
    Resolve email credentials and server settings from the environment,
    applying a provider preset (if EMAIL_PROVIDER is set) as defaults
    that explicit SMTP_HOST/IMAP_HOST env vars can still override.

    Raises:
        EmailServiceError: if the address/password are missing, or the
            SMTP/IMAP hosts can't be determined from either a known
            preset or explicit env vars.
    """
    address = get_env("EMAIL_ADDRESS")
    app_password = get_env("EMAIL_APP_PASSWORD")

    if not address or not app_password:
        raise EmailServiceError(
            "Email requires EMAIL_ADDRESS and EMAIL_APP_PASSWORD in your .env file. "
            "Most providers require a generated 'app password', not your normal login password."
        )

    provider_key = (get_env("EMAIL_PROVIDER") or "").strip().lower()
    preset = PROVIDER_PRESETS.get(provider_key)

    smtp_host = get_env("SMTP_HOST") or (preset.smtp_host if preset else None)
    smtp_port = int(get_env("SMTP_PORT") or (preset.smtp_port if preset else 0) or 587)
    imap_host = get_env("IMAP_HOST") or (preset.imap_host if preset else None)
    imap_port = int(get_env("IMAP_PORT") or (preset.imap_port if preset else 0) or 993)

    if not smtp_host or not imap_host:
        raise EmailServiceError(
            "Could not determine mail server settings. Set EMAIL_PROVIDER to "
            f"one of {list(PROVIDER_PRESETS)}, or set SMTP_HOST/IMAP_HOST explicitly."
        )

    return EmailCredentials(
        address=address,
        app_password=app_password,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        imap_host=imap_host,
        imap_port=imap_port,
    )


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #

def send_email(
    to: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html: bool = False,
) -> bool:
    """
    Send an email via SMTP.

    Args:
        to: Recipient address (or comma-separated addresses).
        subject: Email subject line.
        body: Email body content.
        cc: Optional list of CC recipient addresses.
        bcc: Optional list of BCC recipient addresses (not included in
            the visible headers sent to `to`/`cc`, added only to the
            actual SMTP envelope recipient list).
        html: If True, sends `body` as HTML content; otherwise plain text.

    Raises:
        EmailServiceError: on missing credentials, connection failure,
            authentication failure, or send failure.
    """
    creds = _load_credentials()

    message = MIMEMultipart()
    message["From"] = creds.address
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = ", ".join(cc)

    message.attach(MIMEText(body, "html" if html else "plain"))

    all_recipients = [addr.strip() for addr in to.split(",")]
    if cc:
        all_recipients.extend(cc)
    if bcc:
        all_recipients.extend(bcc)

    try:
        with smtplib.SMTP(creds.smtp_host, creds.smtp_port, timeout=15) as server:
            server.starttls()
            server.login(creds.address, creds.app_password)
            server.sendmail(creds.address, all_recipients, message.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailServiceError(
            "Email authentication failed. Check EMAIL_APP_PASSWORD "
            "(most providers require a generated app password, not your normal password)."
        ) from exc
    except smtplib.SMTPException as exc:
        raise EmailServiceError(f"Failed to send email: {exc}") from exc
    except OSError as exc:
        raise EmailServiceError(f"Could not connect to mail server '{creds.smtp_host}': {exc}") from exc

    logger.info("Email sent to %s (subject: %r).", to, subject)
    return True


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

def _connect_imap(creds: EmailCredentials) -> imaplib.IMAP4_SSL:
    try:
        connection = imaplib.IMAP4_SSL(creds.imap_host, creds.imap_port, timeout=15)
        connection.login(creds.address, creds.app_password)
        return connection
    except imaplib.IMAP4.error as exc:
        raise EmailServiceError(
            "Email authentication failed. Check EMAIL_APP_PASSWORD "
            "(most providers require a generated app password, not your normal password)."
        ) from exc
    except OSError as exc:
        raise EmailServiceError(f"Could not connect to mail server '{creds.imap_host}': {exc}") from exc


def list_recent_emails(
    folder: str = "INBOX",
    limit: int = 10,
    unread_only: bool = False,
) -> list[EmailMessage]:
    """
    Fetch the most recent emails from a folder.

    Args:
        folder: IMAP folder/mailbox name (default 'INBOX').
        limit: Maximum number of messages to return, most recent first.
        unread_only: If True, only fetches unread messages.

    Raises:
        EmailServiceError: on missing credentials or a connection/protocol failure.
    """
    creds = _load_credentials()
    connection = _connect_imap(creds)

    try:
        status, _ = connection.select(folder, readonly=True)
        if status != "OK":
            raise EmailServiceError(f"Could not open mail folder '{folder}'.")

        search_criteria = "UNSEEN" if unread_only else "ALL"
        status, data = connection.search(None, search_criteria)
        if status != "OK":
            raise EmailServiceError("IMAP search failed.")

        message_ids = data[0].split()
        message_ids = message_ids[-limit:] if len(message_ids) > limit else message_ids
        message_ids.reverse()  # most recent first

        results: list[EmailMessage] = []
        for msg_id in message_ids:
            status, msg_data = connection.fetch(msg_id, "(RFC822 FLAGS)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue

            raw_email = msg_data[0][1]
            parsed = email.message_from_bytes(raw_email)

            flags_entry = msg_data[0][0].decode(errors="replace") if isinstance(msg_data[0][0], bytes) else str(msg_data[0][0])
            is_unread = "\\Seen" not in flags_entry

            date_header = parsed.get("Date")
            parsed_date = None
            if date_header:
                try:
                    parsed_date = parsedate_to_datetime(date_header)
                except (TypeError, ValueError):
                    parsed_date = None

            snippet = _extract_snippet(parsed)

            results.append(
                EmailMessage(
                    uid=msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                    subject=_decode_mime_words(parsed.get("Subject")),
                    sender=_decode_mime_words(parsed.get("From")),
                    date=parsed_date,
                    snippet=snippet,
                    is_unread=is_unread,
                )
            )

        logger.info("Fetched %d email(s) from '%s' (unread_only=%s).", len(results), folder, unread_only)
        return results

    finally:
        with suppress(imaplib.IMAP4.error):
            connection.close()
        connection.logout()


def _extract_snippet(parsed_email, max_chars: int = 200) -> str:
    """Extract a short plain-text preview from a parsed email.message.Message."""
    body = ""
    if parsed_email.is_multipart():
        for part in parsed_email.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to decode plain-text email part: %s", exc)
                    continue
                break
    else:
        try:
            body = parsed_email.get_payload(decode=True).decode(
                parsed_email.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception:  # noqa: BLE001
            body = ""

    body = " ".join(body.split())  # collapse whitespace/newlines
    return body[:max_chars] + ("..." if len(body) > max_chars else "")


def get_unread_count(folder: str = "INBOX") -> int:
    """Return the number of unread messages in a folder."""
    creds = _load_credentials()
    connection = _connect_imap(creds)
    try:
        connection.select(folder, readonly=True)
        status, data = connection.search(None, "UNSEEN")
        if status != "OK":
            raise EmailServiceError("IMAP search failed while counting unread messages.")
        return len(data[0].split())
    finally:
        with suppress(imaplib.IMAP4.error):
            connection.close()
        connection.logout()


def mark_as_read(uid: str, folder: str = "INBOX") -> bool:
    """Mark a specific message (by its IMAP sequence id from list_recent_emails) as read."""
    creds = _load_credentials()
    connection = _connect_imap(creds)
    try:
        connection.select(folder, readonly=False)
        status, _ = connection.store(uid, "+FLAGS", "\\Seen")
        return status == "OK"
    finally:
        with suppress(imaplib.IMAP4.error):
            connection.close()
        connection.logout()


def is_available() -> bool:
    """Check whether email credentials are configured (does not verify
    they're actually valid — that requires a live connection attempt)."""
    try:
        _load_credentials()
        return True
    except EmailServiceError:
        return False
