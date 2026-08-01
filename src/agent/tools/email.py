from __future__ import annotations

import asyncio
import base64
import email
import imaplib
import json as _json
import mimetypes
import os
import re
import smtplib
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dt_time
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.utils import formataddr, parsedate_to_datetime
from pathlib import Path
from typing import Literal, Optional

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, field_validator, model_validator

from agent.core.config_manager import load_env_config
from agent.history.tool_call_recorder import (
    get_current_session,
    get_current_turn,
    session_tool_dir,
)

DEFAULT_READ_MAX_COUNT = 5
SEND_TIMEOUT = 30


# ---------- 邮箱提供商配置 ----------
@dataclass(frozen=True)
class _ProviderConfig:
    """邮箱提供商的 SMTP / IMAP 连接参数。"""
    name: str                # 显示名称，如 "QQ邮箱"
    smtp_host: str
    smtp_port: int           # SSL 端口
    imap_host: str
    imap_port: int           # SSL 端口


_PROVIDERS: dict[str, _ProviderConfig] = {
    "qq.com":     _ProviderConfig("QQ邮箱",       "smtp.qq.com",  465, "imap.qq.com",  993),
    "163.com":    _ProviderConfig("网易163邮箱",  "smtp.163.com", 465, "imap.163.com", 993),
    "126.com":    _ProviderConfig("网易126邮箱",  "smtp.126.com", 465, "imap.126.com", 993),
    "yeah.net":   _ProviderConfig("网易Yeah邮箱", "smtp.yeah.net", 465, "imap.yeah.net", 993),
}


def _detect_provider(email_address: str) -> _ProviderConfig:
    """根据邮箱地址自动检测提供商。

    输入:
        email_address: 如 "user@qq.com"、"user@163.com"。

    输出:
        _ProviderConfig 实例。

    异常:
        ValueError: 不支持的邮箱域名。
    """
    email_address = (email_address or "").strip().lower()
    if "@" not in email_address:
        raise ValueError(
            f"无法识别的邮箱地址格式: '{email_address}'，"
            f"请使用完整的邮箱地址（如 user@qq.com）。"
        )
    domain = email_address.split("@")[-1]
    provider = _PROVIDERS.get(domain)
    if provider is not None:
        return provider
    supported = ", ".join(_PROVIDERS.keys())
    raise ValueError(
        f"不支持的邮箱域名: @{domain}。"
        f"当前支持: {supported}。"
        f"请在环境配置中设置对应域名的邮箱地址。"
    )


def _decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "").strip()
    return cleaned or "attachment.bin"


def _parse_time_value(value: str | None, field_name: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    normalized = normalized.replace("/", "-")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(f"{field_name} format is invalid. Use YYYY-MM-DD or YYYY-MM-DD HH:MM[:SS]")


def _is_date_only(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().replace("/", "-")
    return bool(re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", normalized))


def _resolve_read_window(
    start_time: str | None,
    end_time: str | None,
) -> tuple[datetime | None, datetime | None, str]:
    start_dt = _parse_time_value(start_time, "start_time")
    end_dt = _parse_time_value(end_time, "end_time")
    mode = "explicit_range"
    if start_dt and not end_dt and _is_date_only(start_time):
        end_dt = start_dt + timedelta(days=1)
        mode = "single_day_from_start_time"
    elif start_dt and end_dt and _is_date_only(start_time) and _is_date_only(end_time) and start_dt == end_dt:
        # 同一天（如 start="2026-07-08", end="2026-07-08"）：视为查询该整天
        end_dt = start_dt + timedelta(days=1)
        mode = "single_day_explicit"
    elif not start_dt and not end_dt:
        mode = "default_window"
    if start_dt and end_dt and end_dt <= start_dt:
        raise ValueError("end_time must be later than start_time.")
    return start_dt, end_dt, mode


def _get_mail_config_value(name: str, default: str = "") -> str:
    env_value = os.getenv(name)
    if env_value is not None and str(env_value).strip():
        return str(env_value).strip()
    try:
        config = load_env_config()
        value = config.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass
    return default


def _ensure_mail_config() -> tuple[str, str, _ProviderConfig, Path]:
    address = _get_mail_config_value("EMAIL_ADDRESS")
    auth_code = _get_mail_config_value("EMAIL_AUTH_CODE")
    if not address:
        raise ValueError("EMAIL_ADDRESS 未配置，请在设置 → 环境变量中填写邮箱地址。")
    if not auth_code:
        raise ValueError("EMAIL_AUTH_CODE 未配置，请在设置 → 环境变量中填写邮箱授权码。")
    provider = _detect_provider(address)
    session_id = (get_current_session() or "").strip()
    turn_id = (get_current_turn() or "").strip()
    if session_id and turn_id:
        save_dir = session_tool_dir(session_id) / turn_id
    else:
        save_dir = Path(__file__).resolve().parents[1] / "history" / "tool_calling" / "mail_fallback"
    return address, auth_code, provider, save_dir


def _format_mail_date(msg: Message) -> str:
    raw_date = msg.get("Date")
    if not raw_date:
        return ""
    try:
        dt = parsedate_to_datetime(raw_date)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return raw_date


def _mail_datetime(msg: Message) -> datetime | None:
    raw_date = msg.get("Date")
    if not raw_date:
        return None
    try:
        dt = parsedate_to_datetime(raw_date)
        if dt.tzinfo is not None:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _extract_body_and_attachments(
    msg: Message,
    save_dir: Path,
) -> tuple[str, list[bytes], list[str]]:
    text_parts: list[str] = []
    image_bytes_list: list[bytes] = []
    saved_attachment_paths: list[str] = []

    for part in msg.walk():
        if part.is_multipart():
            continue

        content_type = part.get_content_type()
        disposition = (part.get_content_disposition() or "").lower()
        filename = _decode_mime_header(part.get_filename())
        payload = part.get_payload(decode=True) or b""

        if disposition in {"attachment", "inline"} and filename:
            safe_name = _sanitize_filename(filename)
            target = save_dir / safe_name
            stem = target.stem
            suffix = target.suffix
            counter = 1
            target.parent.mkdir(parents=True, exist_ok=True)
            while target.exists():
                target = save_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            target.write_bytes(payload)
            saved_attachment_paths.append(str(target))
            if content_type.startswith("image/"):
                image_bytes_list.append(payload)
            continue

        if content_type == "text/plain":
            charset = part.get_content_charset() or "utf-8"
            try:
                text_parts.append(payload.decode(charset, errors="replace").strip())
            except Exception:
                text_parts.append(payload.decode("utf-8", errors="replace").strip())
        elif content_type == "text/html" and not text_parts:
            charset = part.get_content_charset() or "utf-8"
            try:
                html = payload.decode(charset, errors="replace")
            except Exception:
                html = payload.decode("utf-8", errors="replace")
            html_text = re.sub(r"<[^>]+>", " ", html)
            html_text = re.sub(r"\s+", " ", html_text).strip()
            if html_text:
                text_parts.append(html_text)

    text = "\n".join(part for part in text_parts if part).strip()
    return text, image_bytes_list, saved_attachment_paths


def _build_read_summary(
    msg: Message,
    body_text: str,
    attachment_paths: list[str],
) -> str:
    subject = _decode_mime_header(msg.get("Subject"))
    sender = _decode_mime_header(msg.get("From"))
    recipient = _decode_mime_header(msg.get("To"))
    date_text = _format_mail_date(msg)
    lines = [
        f"Subject: {subject or '(no subject)'}",
        f"From: {sender or '(unknown)'}",
        f"To: {recipient or '(unknown)'}",
        f"Date: {date_text or '(unknown)'}",
    ]
    if body_text:
        lines.append("Body:")
        lines.append(body_text)
    if attachment_paths:
        lines.append("Attachments:")
        lines.extend(f"- {path}" for path in attachment_paths)
    return "\n".join(lines)


def _format_debug_block(lines: list[str]) -> str:
    return "Read Debug:\n" + "\n".join(f"- {line}" for line in lines)


def _send_mail(
    sender_address: str,
    auth_code: str,
    provider: _ProviderConfig,
    recipient: str,
    subject: str,
    content: str,
    attachments: list[str] | None = None,
) -> str:
    """通过提供商 SMTP 发送邮件，支持附件。

    输入:
        sender_address: 发件人邮箱。
        auth_code: 邮箱授权码（非登录密码）。
        provider: 提供商配置。
        recipient: 收件人。
        subject: 主题。
        content: 正文。
        attachments: 可选附件文件路径列表。

    输出:
        成功信息字符串。

    异常:
        ConnectionError: 网络连接失败（含 DNS 解析失败、超时等）。
        smtplib.SMTPAuthenticationError: 授权码错误。
        smtplib.SMTPException: 其他 SMTP 错误。
    """
    msg = EmailMessage()
    msg["From"] = formataddr(("Agent", sender_address))
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(content)

    # 添加附件
    attached_files: list[str] = []
    for file_path in (attachments or []):
        path = Path(file_path)
        if not path.is_file():
            return f"[ERROR] 附件不存在: {file_path}"
        ctype, _encoding = mimetypes.guess_type(str(path))
        if ctype is None:
            ctype = "application/octet-stream"
        main_type, sub_type = ctype.split("/", 1)
        with open(path, "rb") as f:
            file_data = f.read()
        msg.add_attachment(file_data, maintype=main_type, subtype=sub_type, filename=path.name)
        attached_files.append(path.name)

    try:
        with smtplib.SMTP_SSL(provider.smtp_host, provider.smtp_port, timeout=SEND_TIMEOUT) as server:
            server.login(sender_address, auth_code)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise smtplib.SMTPAuthenticationError(
            -1,
            f"[SMTP认证失败] {provider.name}（{sender_address}）授权码错误，"
            f"请在设置 → 环境变量中检查 EMAIL_AUTH_CODE。"
        )
    except (socket.gaierror, socket.timeout, ConnectionRefusedError, OSError) as e:
        raise ConnectionError(
            f"[网络连接失败] 无法连接到 {provider.name} SMTP 服务器 "
            f"（{provider.smtp_host}:{provider.smtp_port}）。\n"
            f"原始错误: {e}\n"
            f"请检查: 1) 网络是否正常 2) VPN/代理设置 3) 防火墙是否阻止连接。"
        ) from e

    result = f"[OK] 邮件发送成功（{provider.name}）\nTo: {recipient}\nSubject: {subject}"
    if attached_files:
        result += f"\n附件({len(attached_files)}): " + ", ".join(attached_files)
    return result


def _search_read_targets(
    mail: imaplib.IMAP4_SSL,
    contact: str | None,
    start_dt: datetime | None,
    end_dt: datetime | None,
) -> tuple[list[bytes], str, bool]:
    """搜索匹配的邮件 ID 列表。

    返回:
        (ids, search_query, has_time_filter): ids 列表、IMAP 查询字符串、是否指定了时间范围。
        当指定了时间范围时，不再限制 UNSEEN，以覆盖已读邮件。
    """
    criteria: list[str] = []
    has_time_filter = start_dt is not None or end_dt is not None
    if contact:
        criteria.extend(['FROM', f'"{contact}"'])
    elif not has_time_filter:
        # 仅在未指定时间范围时才限制 UNSEEN；指定了时间范围的查询应覆盖全部邮件（含已读）
        criteria.append("UNSEEN")
    if start_dt is not None:
        criteria.extend(["SINCE", start_dt.strftime("%d-%b-%Y")])
    if end_dt is not None:
        # IMAP BEFORE 是日期粒度的（不含当天 00:00），
        # 若 end_dt 带时间分量（非 00:00:00）则需 +1 天以覆盖 end 当天
        before_date = end_dt.date()
        if end_dt.time() != dt_time(0, 0, 0):
            before_date += timedelta(days=1)
        criteria.extend(["BEFORE", before_date.strftime("%d-%b-%Y")])
    search_query = " ".join(criteria) if criteria else "ALL"
    if criteria:
        status, data = mail.search(None, *criteria)
    else:
        status, data = mail.search(None, "ALL")
    if status != "OK":
        raise RuntimeError(f"IMAP search failed: {status}")
    ids = data[0].split() if data and data[0] else []
    return ids, search_query, has_time_filter


def _parse_internaldate(fetch_data: list[tuple[bytes, bytes]] | list[bytes | tuple]) -> datetime | None:
    """从 IMAP fetch 响应中提取 INTERNALDATE 并解析为 datetime。

    INTERNALDATE 格式示例: "08-Jul-2026 10:30:00 +0800"
    """
    try:
        # 将响应数据拼接为字符串，提取 INTERNALDATE 值
        raw = b""
        for item in fetch_data:
            if isinstance(item, tuple):
                raw += b" ".join(item)
            elif isinstance(item, bytes):
                raw += item
        text = raw.decode("utf-8", errors="replace")
        match = re.search(r'INTERNALDATE\s+"([^"]+)"', text)
        if not match:
            return None
        date_str = match.group(1)
        # IMAP INTERNALDATE 格式: "DD-Mon-YYYY HH:MM:SS +ZZZZ"
        return datetime.strptime(date_str, "%d-%b-%Y %H:%M:%S %z")
    except Exception:
        return None


def _read_mail(
    address: str,
    auth_code: str,
    provider: _ProviderConfig,
    save_dir: Path,
    contact: str | None,
    start_time: str | None,
    end_time: str | None,
    max_count: int,
) -> tuple[str, dict]:
    stage = "prepare read filters"
    started_at = time.perf_counter()
    debug_lines: list[str] = []
    try:
        start_dt, end_dt, window_mode = _resolve_read_window(start_time, end_time)
        if not contact and start_dt is None and end_dt is None:
            start_dt = datetime.now() - timedelta(days=30)
            window_mode = "default_last_30_days_unread"
        debug_lines.append(f"window_mode={window_mode}")
        debug_lines.append(f"contact_filter={contact or '(none)'}")
        debug_lines.append(f"start_time={start_dt.strftime('%Y-%m-%d %H:%M:%S') if start_dt else '(none)'}")
        debug_lines.append(f"end_time={end_dt.strftime('%Y-%m-%d %H:%M:%S') if end_dt else '(none)'}")
        debug_lines.append(f"max_count={max_count}")

        with imaplib.IMAP4_SSL(provider.imap_host, provider.imap_port) as mail:
            stage = "login IMAP"
            mail.login(address, auth_code)
            debug_lines.append("imap_login=ok")
            stage = "open inbox"
            select_status, _ = mail.select("INBOX")
            if select_status != "OK":
                raise RuntimeError("Failed to open INBOX.")
            debug_lines.append("open_inbox=ok")

            stage = "search messages"
            ids, search_query, has_time_filter = _search_read_targets(mail, contact, start_dt, end_dt)
            debug_lines.append(f"imap_query={search_query}")
            debug_lines.append(f"matched_count={len(ids)}")
            if not ids:
                debug_lines.append(f"elapsed_seconds={time.perf_counter() - started_at:.2f}")
                return "[OK] No matching emails found.\n\n" + _format_debug_block(debug_lines), {}

            # 当有时间范围时 IMAP 搜索可能不生效，需在 Python 侧兜底过滤
            # 从最新往旧遍历，直到找够 max_count 条或遍历完所有 ID
            summaries: list[str] = []
            image_bytes_list: list[bytes] = []
            fetched_count = 0
            skipped_count = 0
            date_fallback_count = 0
            scanned_count = 0

            # 从最新到最旧遍历
            max_scan = max(max_count * 10, 200)
            for mail_id in reversed(ids):
                if fetched_count >= max_count:
                    break
                if scanned_count >= max_scan:
                    break
                scanned_count += 1
                stage = f"fetch message {scanned_count}"
                status, data = mail.fetch(mail_id, "(RFC822 INTERNALDATE)")
                if status != "OK" or not data or not data[0]:
                    skipped_count += 1
                    continue
                raw_bytes = data[0][1]
                msg = email.message_from_bytes(raw_bytes)
                mail_dt = _mail_datetime(msg)
                # Date header 无法解析时，用 IMAP INTERNALDATE 兜底
                if mail_dt is None:
                    internal_dt = _parse_internaldate(data)
                    if internal_dt is not None:
                        mail_dt = internal_dt.astimezone().replace(tzinfo=None) if internal_dt.tzinfo else internal_dt
                        date_fallback_count += 1
                # 时间窗口过滤
                if has_time_filter and mail_dt is None:
                    skipped_count += 1
                    continue
                if start_dt and mail_dt and mail_dt < start_dt:
                    skipped_count += 1
                    continue
                if end_dt and mail_dt and mail_dt >= end_dt:
                    skipped_count += 1
                    continue
                stage = f"parse message {scanned_count}"
                body_text, image_bytes, attachment_paths = _extract_body_and_attachments(msg, save_dir)
                image_bytes_list.extend(image_bytes)
                summaries.append(_build_read_summary(msg, body_text, attachment_paths))
                fetched_count += 1

            debug_lines.append(f"scanned_count={scanned_count}")
            debug_lines.append(f"fetched_count={fetched_count}")
            debug_lines.append(f"skipped_count={skipped_count}")
            if date_fallback_count:
                debug_lines.append(f"date_fallback_count={date_fallback_count}")
            debug_lines.append(f"saved_image_count={len(image_bytes_list)}")
            debug_lines.append(f"elapsed_seconds={time.perf_counter() - started_at:.2f}")

            if not summaries:
                return (
                    "[OK] Matching emails were searched, but no messages remained after filtering.\n\n"
                    + _format_debug_block(debug_lines),
                    {},
                )

            artifact: dict = {}
            if image_bytes_list:
                artifact["images"] = image_bytes_list
                artifact["image_urls"] = [
                    f"data:{mimetypes.guess_type('x.png')[0] or 'image/png'};base64,{base64.b64encode(img).decode('ascii')}"
                    for img in image_bytes_list
                ]
            return _format_debug_block(debug_lines) + "\n\n" + ("\n" + ("-" * 60) + "\n\n").join(summaries), artifact
    except Exception as exc:
        debug_lines.append(f"failed_stage={stage}")
        debug_lines.append(f"elapsed_seconds={time.perf_counter() - started_at:.2f}")
        raise RuntimeError(f"read failed at stage '{stage}': {exc}\n\n{_format_debug_block(debug_lines)}") from exc


class MailToolInput(BaseModel):
    action: Literal["send", "read"] = Field(..., description="Required action: send or read.")
    contact: Optional[str] = Field(
        default=None,
        description="Recipient email address for send, or sender filter for read.",
    )
    start_time: Optional[str] = Field(
        default=None,
        description="Optional read start time. Format: YYYY-MM-DD or YYYY-MM-DD HH:MM[:SS]. If only a date is given and end_time is empty, it means that single day.",
    )
    end_time: Optional[str] = Field(
        default=None,
        description="Optional read end time. Format: YYYY-MM-DD or YYYY-MM-DD HH:MM[:SS].",
    )
    max_count: int = Field(
        default=DEFAULT_READ_MAX_COUNT,
        description=f"Maximum number of newest matched emails to read. Default is {DEFAULT_READ_MAX_COUNT}.",
    )
    subject: Optional[str] = Field(
        default=None,
        description="Required subject when action=send.",
    )
    content: Optional[str] = Field(
        default=None,
        description="Required body content when action=send.",
    )
    attachments: Optional[list[str]] = Field(
        default=None,
        description="Optional list of local file paths to attach when action=send.",
    )

    @field_validator("attachments", mode="before")
    @classmethod
    def _coerce_attachments(cls, v: object) -> list[str] | None:
        """LLM 可能将 attachments 传为 JSON 字符串，在此处转为列表。"""
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                try:
                    parsed = _json.loads(stripped)
                    if isinstance(parsed, list):
                        return parsed
                except (_json.JSONDecodeError, TypeError):
                    pass
            # 单文件路径字符串 → 转为单元素列表
            return [stripped]
        return [str(v)]

    @model_validator(mode="after")
    def _validate_inputs(self) -> "MailToolInput":
        if self.action == "send":
            if not self.contact:
                raise ValueError("contact is required when action=send.")
            if not self.subject:
                raise ValueError("subject is required when action=send.")
            if not self.content:
                raise ValueError("content is required when action=send.")
        if self.action == "read":
            if self.max_count <= 0:
                raise ValueError("max_count must be greater than 0 when action=read.")
        return self


class MailTool(BaseTool):
    args_schema: type[BaseModel] = MailToolInput
    name: str = "mail_tool"
    description: str = (
        "Email tool supporting QQ Mail (qq.com) and Netease Mail (163.com / 126.com / yeah.net).\n"
        "Automatically detects the email provider from EMAIL_ADDRESS in env config.\n"
        "- action='send': requires contact(recipient email), subject, content. Optionally attachments (local file paths).\n"
        "- action='read': optional contact(sender filter), optional start_time/end_time, and optional max_count.\n"
        "- If read only provides start_time as a date like 2026-07-08, it reads that full day.\n"
        f"- If read does not specify contact or time range, it defaults to unread emails from the last 30 days, limited to the newest {DEFAULT_READ_MAX_COUNT} messages.\n"
        "- Images are returned as artifact. Attachments are saved locally and their paths are added to the text result."
    )
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"

    def _run(
        self,
        action: str,
        contact: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        max_count: int = DEFAULT_READ_MAX_COUNT,
        subject: str | None = None,
        content: str | None = None,
        attachments: list[str] | None = None,
    ) -> tuple[str, dict]:
        stage = "initialize"
        try:
            stage = "load mail config"
            address, auth_code, provider, save_dir = _ensure_mail_config()
            normalized_action = (action or "").strip().lower()
            if normalized_action == "send":
                stage = "send email"
                result = _send_mail(
                    sender_address=address,
                    auth_code=auth_code,
                    provider=provider,
                    recipient=(contact or "").strip(),
                    subject=(subject or "").strip(),
                    content=content or "",
                    attachments=attachments,
                )
                return result, {}

            if normalized_action == "read":
                stage = "read email"
                return _read_mail(
                    address=address,
                    auth_code=auth_code,
                    provider=provider,
                    save_dir=save_dir,
                    contact=(contact or "").strip() or None,
                    start_time=start_time,
                    end_time=end_time,
                    max_count=max_count,
                )

            return f"[ERROR] Unsupported action: {action}", {}
        except Exception as exc:
            return f"[ERROR] mail_tool failed at stage '{stage}': {exc}", {}

    async def _arun(self, **kwargs) -> tuple[str, dict]:
        return await asyncio.to_thread(self._run, **kwargs)
