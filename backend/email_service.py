import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import Config

logger = logging.getLogger(__name__)

def send_verification_email(user_or_email, token_or_name=None, token=None) -> bool:
    if hasattr(user_or_email, 'email'):
        to_email = user_or_email.email
        name = user_or_email.name
        actual_token = token_or_name
    elif token is not None:
        to_email = user_or_email
        name = token_or_name
        actual_token = token
    else:
        to_email = user_or_email
        name = "Operative"
        actual_token = token_or_name

    event_name = Config.EVENT.get('eventName', 'CTF Tournament')
    event_motto = Config.EVENT.get('eventSubtitle', 'Think. Enumerate. Exploit. Capture.')
    verify_url = f"{Config.PORTAL_BASE_URL}/verify/{actual_token}"
    subject = f"Verify your {event_name} account"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0b0f19; color: #f1f5f9; padding: 20px; }}
  .card {{ max-width: 600px; margin: 0 auto; background-color: #151d30; border: 1px solid #1e293b; border-radius: 8px; padding: 30px; }}
  .header {{ text-align: center; border-bottom: 1px solid #1e293b; padding-bottom: 20px; margin-bottom: 20px; }}
  .title {{ color: #38bdf8; font-size: 24px; font-weight: bold; margin: 0; }}
  .btn {{ display: inline-block; padding: 12px 28px; background-color: #0284c7; color: #ffffff !important; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 25px 0; }}
  .footer {{ font-size: 12px; color: #94a3b8; text-align: center; margin-top: 30px; }}
</style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1 class="title">{event_name}</h1>
      <p style="color: #94a3b8; margin-top: 5px;">{event_motto}</p>
    </div>
    <p>Hello <strong>{name}</strong>,</p>
    <p>Welcome to {event_name}. To authenticate your account and participate in the tournament, please verify your email address below:</p>
    <div style="text-align: center;">
      <a href="{verify_url}" class="btn">VERIFY EMAIL ADDRESS</a>
    </div>
    <p style="font-size: 13px; color: #94a3b8;">If the button does not work, copy and paste this verification URL into your browser:</p>
    <p style="font-size: 12px; word-break: break-all; color: #38bdf8;">{verify_url}</p>
    <p style="font-size: 13px; color: #94a3b8;">This link expires in 24 hours. If you did not register for this tournament, you can safely ignore this email.</p>
    <div class="footer">
      &copy; {event_name} Organization. All rights reserved.
    </div>
  </div>
</body>
</html>"""

    text_content = f"""Hello {name},

Welcome to {event_name}.

Please verify your email address by opening the following link in your browser:
{verify_url}

This verification link will expire in 24 hours.
"""

    if not Config.SMTP_HOST or not Config.SMTP_USERNAME:
        logger.info(f"[SIMULATED EMAIL] To: {to_email} | Subject: {subject} | Verify URL: {verify_url}")
        print(f"\n==================================================")
        print(f"[*] SIMULATED VERIFICATION EMAIL (SMTP NOT CONFIGURED)")
        print(f"[*] To: {to_email}")
        print(f"[*] URL: {verify_url}")
        print(f"==================================================\n")
        return True

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = Config.EMAIL_FROM
        msg['To'] = to_email

        msg.attach(MIMEText(text_content, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))

        if Config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(Config.SMTP_HOST, Config.SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=10)
            if Config.SMTP_USE_TLS:
                server.starttls()

        server.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
        server.sendmail(Config.EMAIL_FROM, [to_email], msg.as_string())
        server.quit()
        logger.info(f"Verification email successfully sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to dispatch verification email to {to_email}: {str(e)}")
        return False
