"""
Email Service for OTP Verification via SMTP (Gmail App Password supported)
"""

import os
import json
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMTP_CONFIG_FILE = os.path.join(BASE_DIR, "data", "smtp_config.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [EMAIL-SERVICE] %(message)s")

def get_smtp_config() -> Dict[str, Any]:
    """Retrieves current SMTP configuration from file or environment variables."""
    config = {
        "smtp_host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.environ.get("SMTP_PORT", 587)),
        "smtp_user": os.environ.get("SMTP_USER", ""),
        "smtp_password": os.environ.get("SMTP_PASSWORD", ""),
        "from_name": os.environ.get("SMTP_FROM_NAME", "RailSearch Team 10")
    }

    if os.path.exists(SMTP_CONFIG_FILE):
        try:
            with open(SMTP_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except Exception as e:
            logging.error(f"Error reading SMTP config file: {e}")

    return config

def save_smtp_config(smtp_user: str, smtp_password: str, smtp_host: str = "smtp.gmail.com", smtp_port: int = 587) -> Dict[str, Any]:
    """Saves SMTP credentials to local data file."""
    config = {
        "smtp_host": smtp_host.strip(),
        "smtp_port": int(smtp_port),
        "smtp_user": smtp_user.strip(),
        "smtp_password": smtp_password.strip(),
        "from_name": "RailSearch Team 10"
    }
    os.makedirs(os.path.dirname(SMTP_CONFIG_FILE), exist_ok=True)
    with open(SMTP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    logging.info(f"Updated SMTP config for user: {smtp_user}")
    return {"status": "SUCCESS", "message": "SMTP configuration saved successfully."}

def send_otp_email(recipient_email: str, otp: str, full_name: str) -> Dict[str, Any]:
    """
    Sends OTP verification email to recipient.
    If SMTP credentials are provided, transmits via SMTP server.
    If not provided or fails, returns simulated response for local testing.
    """
    config = get_smtp_config()
    smtp_user = config.get("smtp_user")
    smtp_pass = config.get("smtp_password")
    smtp_host = config.get("smtp_host", "smtp.gmail.com")
    smtp_port = config.get("smtp_port", 587)
    from_name = config.get("from_name", "RailSearch Team 10")

    logging.info(f"Initiating OTP verification for {recipient_email} (OTP: {otp})")

    # If no credentials configured yet
    if not smtp_user or not smtp_pass:
        logging.warning("SMTP credentials not configured. Running in local simulation mode.")
        return {
            "success": True,
            "simulated": True,
            "otp": otp,
            "message": f"SMTP credentials not yet set. Simulated OTP generated: {otp}. You can configure your Gmail App Password in Admin settings anytime."
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Your RailSearch Verification Code: {otp}"
        msg["From"] = f"{from_name} <{smtp_user}>"
        msg["To"] = recipient_email

        text_body = f"""Hello {full_name},

Thank you for registering with RailSearch (Team 10).
Your 6-digit verification code is: {otp}

This code will expire in 10 minutes.
Please enter this OTP to complete your account verification.

Safe travels,
The RailSearch Team
"""

        html_body = f"""<!DOCTYPE html>
<html>
<head>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; }}
    .container {{ max-width: 500px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .header {{ background: #1e3a8a; color: #ffffff; padding: 24px; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }}
    .header p {{ margin: 6px 0 0 0; opacity: 0.85; font-size: 13px; }}
    .body {{ padding: 32px 24px; text-align: center; }}
    .otp-box {{ display: inline-block; background: #eff6ff; border: 2px dashed #3b82f6; border-radius: 8px; padding: 14px 28px; margin: 20px 0; font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #1e3a8a; font-family: monospace; }}
    .note {{ color: #64748b; font-size: 13px; line-height: 1.5; margin-top: 16px; }}
    .footer {{ background: #f1f5f9; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>RailSearch Verification</h1>
      <p>Multi-Process Railway Search Engine · Team 10</p>
    </div>
    <div class="body">
      <p style="font-size: 16px; color: #1e293b; margin-top: 0;">Hello <strong>{full_name}</strong>,</p>
      <p style="color: #475569; font-size: 14px;">Use the verification code below to verify your email and set up your account password:</p>
      <div class="otp-box">{otp}</div>
      <p class="note">This OTP is valid for <strong>10 minutes</strong>. Never share this code with anyone.</p>
    </div>
    <div class="footer">
      &copy; 2026 RailSearch Team 10. All rights reserved.
    </div>
  </div>
</body>
</html>
"""
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10.0)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=10.0)
            server.ehlo()
            server.starttls()
            server.ehlo()

        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [recipient_email], msg.as_string())
        server.quit()

        logging.info(f"Verification email successfully sent to {recipient_email}")
        return {
            "success": True,
            "simulated": False,
            "message": f"Verification code sent to {recipient_email}"
        }

    except Exception as e:
        logging.error(f"Failed to send email via SMTP: {e}")
        # Fallback to simulated delivery so user testing is never blocked
        return {
            "success": True,
            "simulated": True,
            "otp": otp,
            "warning": f"SMTP dispatch failed ({str(e)}). Running fallback mode with OTP: {otp}"
        }
