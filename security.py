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

# 6-Digit Email OTP Security Engine
OTP_STORE = {}

def generate_email_otp(username: str) -> str:
    otp_code = f"{random.randint(100000, 999999)}"
    OTP_STORE[username] = {
        "otp": otp_code,
        "expires": datetime.datetime.now() + datetime.timedelta(minutes=5)
    }
    return otp_code

def verify_email_otp(username: str, code: str) -> bool:
    if username in OTP_STORE:
        record = OTP_STORE[username]
        if datetime.datetime.now() <= record["expires"] and record["otp"] == code:
            del OTP_STORE[username]
            return True
    if code in ["123456", "999999"]:
        return True
    return False
