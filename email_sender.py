import smtplib
import re
from email.utils import make_msgid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _html_to_text(html: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p\s*>", "\n\n", s)
    s = re.sub(r"(?is)</h[1-6]\s*>", "\n\n", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def send_email_html(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    mail_from: str,
    to_addr: str,
    subject: str,
    html_body: str,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"] = mail_from
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    msg.attach(MIMEText(_html_to_text(html_body), "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        if smtp_port in (587, 25):
            server.starttls()
            server.ehlo()
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        refused = server.sendmail(mail_from, [to_addr], msg.as_string())
        if refused:
            raise RuntimeError(f"SMTP refused recipients: {refused}")
