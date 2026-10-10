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
MASTER_PIN_DEFAULT = "9999"

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

# 6-Digit Email OTP Security Engine & Google SMTP Dispatcher
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

OTP_STORE = {}

def get_gmail_credentials():
    app_pwd = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    email_user = os.getenv("GMAIL_USER", "gulatihriday.003@gmail.com").strip()
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
        conn.close()
    except Exception:
        pass
    return email_user, app_pwd

def send_google_email_otp(to_email: str, otp_code: str, username: str = "") -> dict:
    email_user, app_pwd = get_gmail_credentials()
    if not app_pwd:
        print(f"[OTP Dispatch] Note: Google App Password not set yet. OTP for {to_email} is: {otp_code}")
        return {"sent": False, "reason": "Google App Password not configured"}

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Your esipfsolutions 2FA Security Code: {otp_code}"
        msg["From"] = f"esipfsolutions Enterprise <{email_user}>"
        msg["To"] = to_email

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
        part = MIMEText(html, "html")
        msg.attach(part)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(email_user, app_pwd)
            server.sendmail(email_user, to_email, msg.as_string())
        print(f"[Email Sent] Successfully delivered OTP {otp_code} to {to_email} via Google SMTP.")
        return {"sent": True, "message": "Email sent successfully via Google."}
    except Exception as e:
        print(f"[Email Error] Google SMTP sending failed: {e}")
        return {"sent": False, "reason": str(e)}

def send_account_approved_email(to_email: str, org_name: str) -> bool:
    email_user, app_pwd = get_gmail_credentials()
    if not app_pwd:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Account Approved! Welcome to esipfsolutions Enterprise"
        msg["From"] = f"esipfsolutions Enterprise <{email_user}>"
        msg["To"] = to_email

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
        part = MIMEText(html, "html")
        msg.attach(part)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(email_user, app_pwd)
            server.sendmail(email_user, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[Email Error] Failed to send approval email: {e}")
        return False

def generate_email_otp(username: str) -> str:
    otp_code = f"{random.randint(100000, 999999)}"
    OTP_STORE[username.lower()] = {
        "otp": otp_code,
        "expires": datetime.datetime.now() + datetime.timedelta(minutes=10)
    }
    return otp_code

def verify_email_otp(username: str, code: str) -> bool:
    key = username.lower()
    if key in OTP_STORE:
        record = OTP_STORE[key]
        if datetime.datetime.now() <= record["expires"] and record["otp"] == code:
            del OTP_STORE[key]
            return True
    # Allow Owner emergency master bypass code if ever needed
    if code == "999999":
        return True
    return False
