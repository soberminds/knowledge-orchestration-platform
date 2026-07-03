"""SMTP-backed email sender used by Agent confirmation tools."""

from __future__ import annotations

import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from typing import Any

from app.core.settings import Settings, settings
from app.core.time_utils import now_china_iso


EMAIL_BODY_MAX_CHARS = 20000
EMAIL_SUBJECT_MAX_CHARS = 200
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class EmailSendResult:
    """Structured result returned after SMTP accepts the message."""

    status: str
    message_id: str
    to: list[str]
    cc: list[str]
    subject: str
    from_email: str
    from_name: str
    smtp_host: str
    sent_at: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message_id": self.message_id,
            "to": self.to,
            "cc": self.cc,
            "subject": self.subject,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "smtp_host": self.smtp_host,
            "sent_at": self.sent_at,
        }


class EmailSender:
    """Validate and send plain-text emails through configured SMTP."""

    def __init__(self, runtime_settings: Settings = settings) -> None:
        self.settings = runtime_settings

    def is_configured(self) -> bool:
        return (
            self.settings.email_tool_enabled
            and bool(self.settings.smtp_host)
            and bool(self.settings.smtp_username)
            and bool(self.settings.smtp_password)
            and bool(self._from_email())
        )

    def configuration_summary(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.email_tool_enabled,
            "configured": self.is_configured(),
            "smtp_host": self.settings.smtp_host,
            "smtp_port": self.settings.smtp_port,
            "from_email": self._from_email(),
            "from_name": self.settings.smtp_from_name,
            "use_ssl": self.settings.smtp_use_ssl,
            "starttls": self.settings.smtp_starttls,
            "max_recipients": self.settings.email_tool_max_recipients,
            "allowed_domains": list(self.settings.email_tool_allowed_domains),
        }

    def send_email(
        self,
        *,
        to: Any,
        subject: str,
        body: str,
        cc: Any = None,
    ) -> dict[str, Any]:
        if not self.settings.email_tool_enabled:
            raise ValueError("邮件发送工具未启用，请先设置 EMAIL_TOOL_ENABLED=true。")
        if not self.is_configured():
            raise ValueError("SMTP 配置不完整，请检查 SMTP_HOST、SMTP_USERNAME、SMTP_PASSWORD 和发件人配置。")

        recipients = self._normalize_recipients(to, field_name="to")
        cc_recipients = self._normalize_recipients(cc, field_name="cc", required=False)
        total_recipients = len(recipients) + len(cc_recipients)
        if total_recipients <= 0:
            raise ValueError("至少需要一个收件人。")
        if total_recipients > self.settings.email_tool_max_recipients:
            raise ValueError(f"单次邮件最多允许 {self.settings.email_tool_max_recipients} 个收件人和抄送人。")

        clean_subject = str(subject or "").strip()
        clean_body = str(body or "").strip()
        if not clean_subject:
            raise ValueError("邮件主题不能为空。")
        if len(clean_subject) > EMAIL_SUBJECT_MAX_CHARS:
            raise ValueError(f"邮件主题不能超过 {EMAIL_SUBJECT_MAX_CHARS} 个字符。")
        if not clean_body:
            raise ValueError("邮件正文不能为空。")
        if len(clean_body) > EMAIL_BODY_MAX_CHARS:
            raise ValueError(f"邮件正文不能超过 {EMAIL_BODY_MAX_CHARS} 个字符。")

        from_email = self._from_email()
        message_id = make_msgid(domain=from_email.split("@", 1)[-1])
        message = EmailMessage()
        message["Subject"] = clean_subject
        message["From"] = formataddr((self.settings.smtp_from_name, from_email))
        message["To"] = ", ".join(recipients)
        if cc_recipients:
            message["Cc"] = ", ".join(cc_recipients)
        message["Message-ID"] = message_id
        message.set_content(clean_body)

        context = ssl.create_default_context()
        if self.settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_sec,
                context=context,
            ) as client:
                client.login(self.settings.smtp_username, self.settings.smtp_password)
                client.send_message(message)
        else:
            with smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_sec,
            ) as client:
                client.ehlo()
                if self.settings.smtp_starttls:
                    client.starttls(context=context)
                    client.ehlo()
                client.login(self.settings.smtp_username, self.settings.smtp_password)
                client.send_message(message)

        return EmailSendResult(
            status="sent",
            message_id=message_id,
            to=recipients,
            cc=cc_recipients,
            subject=clean_subject,
            from_email=from_email,
            from_name=self.settings.smtp_from_name,
            smtp_host=self.settings.smtp_host,
            sent_at=now_china_iso(),
        ).to_payload()

    def _from_email(self) -> str:
        return (self.settings.smtp_from_email or self.settings.smtp_username).strip()

    def _normalize_recipients(self, value: Any, *, field_name: str, required: bool = True) -> list[str]:
        if value is None or value == "":
            if required:
                raise ValueError(f"{field_name} 不能为空。")
            return []
        if isinstance(value, str):
            candidates = [item.strip() for item in re.split(r"[,;\n]", value) if item.strip()]
        elif isinstance(value, (list, tuple, set)):
            candidates = [str(item or "").strip() for item in value if str(item or "").strip()]
        else:
            raise ValueError(f"{field_name} 必须是邮箱字符串或邮箱数组。")

        normalized: list[str] = []
        for candidate in candidates:
            parsed_name, parsed_email = parseaddr(candidate)
            email = (parsed_email or parsed_name or candidate).strip().lower()
            if not _EMAIL_PATTERN.match(email):
                raise ValueError(f"邮箱地址格式不正确：{candidate}")
            self._assert_allowed_domain(email)
            if email not in normalized:
                normalized.append(email)
        if required and not normalized:
            raise ValueError(f"{field_name} 不能为空。")
        return normalized

    def _assert_allowed_domain(self, email: str) -> None:
        allowed_domains = self.settings.email_tool_allowed_domains
        if not allowed_domains:
            return
        domain = email.rsplit("@", 1)[-1].lower()
        if domain not in allowed_domains:
            allowed = ", ".join(allowed_domains)
            raise ValueError(f"收件人域名 {domain} 不在允许列表中：{allowed}")
