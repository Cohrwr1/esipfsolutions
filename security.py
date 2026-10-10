import hashlib
import os
import pyotp
import jwt
import datetime
import random
from cryptography.fernet import Fernet
import base64

SECRET_KEY = "servagya_super_secret_payroll_enterprise_key_2026"
ALGORITHM = "HS256"
MASTER_PIN_DEFAULT = "3669"

# Generate encryption key derived from SECRET_KEY
def get_fernet_key():
    key_hash = hashlib.sha256(SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(key_hash)

fernet = Fernet(get_fernet_key())

def hash_password(password: str) -> str:
    salt = "servagya_salt_payroll_"
    return hashlib.sha256((salt + password).encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

def encrypt_sensitive(data: str) -> str:
    if not data:
        return ""
    try:
        return fernet.encrypt(data.encode()).decode()
    except Exception:
        return data

def decrypt_sensitive(token: str) -> str:
    if not token:
        return ""
    try:
        return fernet.decrypt(token.encode()).decode()
    except Exception:
        return token

def generate_jwt(user_id: str, tenant_id: str, username: str, role: str) -> str:
    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "username": username,
        "role": role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except Exception:
        return None

def generate_totp_secret() -> str:
    return pyotp.random_base32()

def verify_totp(secret: str, code: str) -> bool:
    if not secret:
        return True
    totp = pyotp.TOTP(secret)
    return totp.verify(code)

def get_totp_uri(secret: str, username: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name="ESIPFSolutions Enterprise")

# 6-Digit Email OTP Security Engine & Multi-Channel Dispatcher
import smtplib
import ssl
import json
import urllib.request
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

OTP_STORE = {}

def get_email_settings():
    app_pwd = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    email_user = os.getenv("GMAIL_USER", "gulatihriday.003@gmail.com").strip()
    script_url = os.getenv("GOOGLE_SCRIPT_URL", "").strip()
    resend_key = os.getenv("RESEND_API_KEY", "").strip()
    try:
        from database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        if not app_pwd:
            cursor.execute("SELECT value FROM system_settings WHERE key = 'gmail_app_password'")
            row = cursor.fetchone()
            if row and row["value"]:
                app_pwd = row["value"].strip()
        cursor.execute("SELECT value FROM system_settings WHERE key = 'gmail_user'")
        row_u = cursor.fetchone()
        if row_u and row_u["value"]:
            email_user = row_u["value"].strip()
        if not script_url:
            cursor.execute("SELECT value FROM system_settings WHERE key = 'google_script_url'")
            row_s = cursor.fetchone()
            if row_s and row_s["value"]:
                script_url = row_s["value"].strip()
        if not resend_key:
            cursor.execute("SELECT value FROM system_settings WHERE key = 'resend_api_key'")
            row_r = cursor.fetchone()
            if row_r and row_r["value"]:
                resend_key = row_r["value"].strip()
        conn.close()
    except Exception:
        pass
    return {
        "email_user": email_user,
        "app_pwd": app_pwd,
        "script_url": script_url,
        "resend_key": resend_key
    }

def get_gmail_credentials():
    s = get_email_settings()
    return s["email_user"], s["app_pwd"]

def send_via_google_script(script_url: str, to_email: str, subject: str, html: str) -> bool:
    try:
        payload = json.dumps({"to": to_email, "subject": subject, "html": html}).encode('utf-8')
        req = urllib.request.Request(script_url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            print(f"[Email Sent] Delivered via Google Apps Script Web App (HTTPS) to {to_email}")
            return True
    except Exception as e:
        print(f"[Email Error] Google Apps Script HTTP send failed: {e}")
        return False

def send_via_resend(api_key: str, to_email: str, subject: str, html: str) -> bool:
    try:
        payload = json.dumps({
            "from": "esipfsolutions Enterprise <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "html": html
        }).encode('utf-8')
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            print(f"[Email Sent] Delivered via Resend (HTTPS) to {to_email}")
            return True
    except Exception as e:
        print(f"[Email Error] Resend HTTP send failed: {e}")
        return False

def send_google_email_otp(to_email: str, otp_code: str, username: str = "") -> dict:
    settings = get_email_settings()
    email_user = settings["email_user"]
    app_pwd = settings["app_pwd"]
    script_url = settings["script_url"]
    resend_key = settings["resend_key"]

    subject = f"Your esipfsolutions 2FA Security Code: {otp_code}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 25px; border: 1px solid #e2e8f0; border-radius: 16px; background-color: #ffffff;">
        <div style="text-align: center; margin-bottom: 20px;">
            <h2 style="color: #2563eb; margin: 0; font-size: 24px; font-weight: 800;">esipfsolutions</h2>
            <p style="color: #64748b; font-size: 13px; margin: 4px 0 0 0;">Cloud Enterprise Security</p>
        </div>
        <div style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 12px; padding: 22px; text-align: center; margin-bottom: 20px;">
            <p style="color: #475569; font-size: 14px; margin: 0 0 10px 0;">Your one-time authentication code is:</p>
            <div style="font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #0f172a; font-family: monospace;">{otp_code}</div>
            <p style="color: #94a3b8; font-size: 12px; margin: 10px 0 0 0;">Valid for 10 minutes. Never share this code with anyone.</p>
        </div>
        <p style="color: #64748b; font-size: 12px; line-height: 1.5; margin: 0;">
            If you did not request this login verification code for <b>esipfsolutions.in</b>, please ignore this email.
        </p>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <p style="color: #94a3b8; font-size: 11px; text-align: center; margin: 0;">
            Sent securely via Google Mail &copy; 2026 esipfsolutions.in
        </p>
    </div>
    """

    # 1. Try Google Apps Script (Port 443 - works everywhere including Render Free tier)
    if script_url:
        if send_via_google_script(script_url, to_email, subject, html):
            return {"sent": True, "message": "Email sent via Google Apps Script (HTTPS)."}

    # 2. Try Resend (Port 443 - works everywhere including Render Free tier)
    if resend_key:
        if send_via_resend(resend_key, to_email, subject, html):
            return {"sent": True, "message": "Email sent via Resend API (HTTPS)."}

    # 3. Try Direct Google SMTP (Works locally and on servers with unblocked SMTP)
    if app_pwd:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"esipfsolutions Enterprise <{email_user}>"
            msg["To"] = to_email
            msg.attach(MIMEText(html, "html"))

            context = ssl.create_default_context()
            # Attempt Port 465 (SSL) with strict 3.5s timeout
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=3.5) as server:
                    server.login(email_user, app_pwd)
                    server.sendmail(email_user, to_email, msg.as_string())
                print(f"[Email Sent] Successfully delivered OTP {otp_code} to {to_email} via Google SMTP (port 465).")
                return {"sent": True, "message": "Email sent via Google SMTP (465)."}
            except Exception as e465:
                # Fallback to Port 587 (STARTTLS) with strict 3.5s timeout
                try:
                    with smtplib.SMTP("smtp.gmail.com", 587, timeout=3.5) as server:
                        server.starttls(context=context)
                        server.login(email_user, app_pwd)
                        server.sendmail(email_user, to_email, msg.as_string())
                    print(f"[Email Sent] Successfully delivered OTP {otp_code} to {to_email} via Google SMTP (port 587).")
                    return {"sent": True, "message": "Email sent via Google SMTP (587)."}
                except Exception as e587:
                    print(f"[Email Warning] Google SMTP (465 & 587) timed out: {e587}. Render Free tier blocks raw SMTP ports.")
                    return {"sent": False, "reason": "SMTP ports blocked or timed out"}
        except Exception as e:
            print(f"[Email Error] Google SMTP exception: {e}")
            return {"sent": False, "reason": str(e)}

    print(f"[OTP Dispatch] Note: No email credentials or HTTP mailer configured. OTP for {to_email} is: {otp_code}")
    return {"sent": False, "reason": "No email dispatcher configured"}

def _send_account_approved_worker(to_email: str, org_name: str):
    settings = get_email_settings()
    email_user = settings["email_user"]
    app_pwd = settings["app_pwd"]
    script_url = settings["script_url"]
    resend_key = settings["resend_key"]

    subject = f"Account Approved! Welcome to esipfsolutions Enterprise"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 25px; border: 1px solid #e2e8f0; border-radius: 16px; background-color: #ffffff;">
        <div style="text-align: center; margin-bottom: 20px;">
            <h2 style="color: #2563eb; margin: 0; font-size: 24px; font-weight: 800;">esipfsolutions</h2>
            <p style="color: #10b981; font-size: 14px; font-weight: bold; margin: 4px 0 0 0;">Access Request Approved</p>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.6;">
            Great news! Your access request for <b>{org_name}</b> has been approved by the Owner.
        </p>
        <p style="color: #334155; font-size: 14px; line-height: 1.6;">
            You can now log in to the portal at <a href="https://esipfsolutions.in" style="color: #2563eb; font-weight: bold;">https://esipfsolutions.in</a> using your registered credentials.
        </p>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <p style="color: #94a3b8; font-size: 11px; text-align: center; margin: 0;">
            esipfsolutions Cloud Enterprise &copy; 2026
        </p>
    </div>
    """

    if script_url and send_via_google_script(script_url, to_email, subject, html):
        return
    if resend_key and send_via_resend(resend_key, to_email, subject, html):
        return

    if app_pwd:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"esipfsolutions Enterprise <{email_user}>"
            msg["To"] = to_email
            msg.attach(MIMEText(html, "html"))
            context = ssl.create_default_context()
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=3.5) as server:
                    server.login(email_user, app_pwd)
                    server.sendmail(email_user, to_email, msg.as_string())
            except Exception:
                with smtplib.SMTP("smtp.gmail.com", 587, timeout=3.5) as server:
                    server.starttls(context=context)
                    server.login(email_user, app_pwd)
                    server.sendmail(email_user, to_email, msg.as_string())
        except Exception as e:
            print(f"[Email Error] Failed to send approval email: {e}")

def send_account_approved_email(to_email: str, org_name: str) -> bool:
    threading.Thread(target=_send_account_approved_worker, args=(to_email, org_name), daemon=True).start()
    return True

def generate_email_otp(username: str) -> str:
    otp_code = f"{random.randint(100000, 999999)}"
    OTP_STORE[username.lower()] = {
        "otp": otp_code,
        "expires": datetime.datetime.now() + datetime.timedelta(minutes=10)
    }
    return otp_code

def verify_email_otp(username: str, code: str) -> bool:
    key = username.lower()
    code_clean = str(code).strip()
    if key in OTP_STORE:
        record = OTP_STORE[key]
        if datetime.datetime.now() <= record["expires"] and record["otp"] == code_clean:
            del OTP_STORE[key]
            return True
    # Allow Owner emergency master bypass code (161011)
    if code_clean == "161011" and key == "owner":
        return True
    return False
