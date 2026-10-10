import datetime
import uuid
import os
import threading
import hmac
import hashlib
from dotenv import load_dotenv

# Load Razorpay and Environment Configurations
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
load_dotenv()

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

try:
    import razorpay
except ImportError:
    razorpay = None

def get_razorpay_config():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM system_settings WHERE key IN ('razorpay_key_id', 'razorpay_key_secret')")
        db_vals = {r["key"]: r["value"] for r in cursor.fetchall()}
        conn.close()
    except Exception:
        db_vals = {}

    key_id = db_vals.get("razorpay_key_id") or os.getenv("RAZORPAY_KEY_ID")
    key_secret = db_vals.get("razorpay_key_secret") or os.getenv("RAZORPAY_KEY_SECRET")
    return key_id, key_secret

def get_razorpay_client():
    key_id, key_secret = get_razorpay_config()
    if not key_id or not key_secret:
        raise HTTPException(status_code=500, detail="Razorpay credentials not configured. Please configure in Owner Settings or .env file.")
    if not razorpay:
        raise HTTPException(status_code=500, detail="Razorpay Python SDK is not installed.")
    return razorpay.Client(auth=(key_id, key_secret))

from fastapi import FastAPI, HTTPException, Depends, Header, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel
from typing import Optional, List

from database import get_db_connection, init_db
from seed_data import seed
from security import (
    hash_password, verify_password, generate_jwt, decode_jwt,
    generate_totp_secret, verify_totp, MASTER_PIN_DEFAULT,
    generate_email_otp, verify_email_otp, get_totp_uri,
    send_google_email_otp, send_account_approved_email
)
from subscription_engine import (
    check_tenant_subscription, get_owner_dashboard_summary,
    owner_lock_tenant, owner_unlock_tenant, owner_extend_subscription, owner_convert_to_lifetime,
    owner_update_tenant, owner_undo_tenant_update, owner_delete_tenant,
    owner_approve_request, owner_decline_request
)
from statutory_engine import (
    calculate_epf, calculate_esi, calculate_professional_tax,
    calculate_tds_estimate, calculate_gratuity, calculate_bonus,
    generate_epf_ecr_file, generate_esi_challan_csv, generate_bank_disbursement_csv
)
from payslip_generator import generate_pdf_payslip

app = FastAPI(title="Servagya Cloud Payroll Enterprise", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()
    try:
        seed()
    except Exception as e:
        print("Startup seed notice:", e)

# Request Models
class PinVerifyReq(BaseModel):
    pin: str

class LoginReq(BaseModel):
    username: str
    password: str
    device_token: Optional[str] = None

class RegisterTenantReq(BaseModel):
    organization_name: str
    email: str
    phone: str
    admin_username: str
    admin_password: str
    plan_type: str # '6_months', '1_year', 'lifetime'
    mode: Optional[str] = "request_approval" # 'razorpay' or 'request_approval'
    payment_id: Optional[str] = None
    order_id: Optional[str] = None
    signature: Optional[str] = None

class CompanyReq(BaseModel):
    company_name: str
    registration_no: Optional[str] = ""
    epf_code: Optional[str] = ""
    esi_code: Optional[str] = ""
    tan_no: Optional[str] = ""
    pan_no: Optional[str] = ""
    address: Optional[str] = ""
    state: Optional[str] = "Maharashtra"
    bank_name: Optional[str] = ""
    account_no: Optional[str] = ""
    ifsc_code: Optional[str] = ""
    epf_emp_rate: Optional[float] = 12.0
    epf_employer_rate: Optional[float] = 12.0
    esi_emp_rate: Optional[float] = 0.75
    esi_employer_rate: Optional[float] = 3.25

class EmployeeReq(BaseModel):
    company_id: Optional[str] = ""
    emp_code: str
    name: str
    email: Optional[str] = ""
    designation: Optional[str] = ""
    department: Optional[str] = ""
    doj: Optional[str] = ""
    pan: Optional[str] = ""
    aadhaar: Optional[str] = ""
    uan_no: Optional[str] = ""
    esi_no: Optional[str] = ""
    bank_name: Optional[str] = ""
    bank_acc: Optional[str] = ""
    ifsc_code: Optional[str] = ""
    basic_pay: float
    hra: float
    conveyance: float = 2000.0
    special_allowance: float = 5000.0
    pf_deduct: int = 1
    esi_deduct: int = 1
    pt_deduct: int = 1
    tax_regime: str = "new"
    custom_epf_rate: Optional[float] = None
    custom_esi_rate: Optional[float] = None

class LoanReq(BaseModel):
    company_id: str
    emp_id: str
    loan_amount: float
    total_emi: int

class AttendanceReq(BaseModel):
    company_id: str
    emp_id: str
    month_year: str
    total_working_days: int
    days_worked: int
    casual_leaves: int = 0
    medical_leaves: int = 0
    privilege_leaves: int = 0
    loss_of_pay_days: int = 0
    overtime_hours: float = 0.0

class ProcessPayrollReq(BaseModel):
    company_id: str
    month_year: str

class OwnerActionReq(BaseModel):
    tenant_id: str
    days: Optional[int] = 30

class OwnerUpdateTenantReq(BaseModel):
    tenant_id: str
    name: str
    email: str
    phone: Optional[str] = ""
    plan_type: str
    subscription_status: str
    expiry_date: str
    price_paid: float

class GratuityReq(BaseModel):
    basic_pay: float
    years_of_service: float

class BonusReq(BaseModel):
    basic_pay: float
    percentage: Optional[float] = 8.33

def get_current_user(authorization: Optional[str] = Header(None), token: Optional[str] = None):
    jwt_token = None
    if authorization:
        jwt_token = authorization.replace("Bearer ", "").strip()
    elif token:
        jwt_token = token.strip()
    
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Missing Authentication Header")
    payload = decode_jwt(jwt_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or Expired Security Token")
    
    if payload.get("role") != "owner" and payload.get("tenant_id"):
        sub_check = check_tenant_subscription(payload["tenant_id"])
        if sub_check.get("is_locked"):
            raise HTTPException(status_code=403, detail=f"ACCOUNT LOCKED: {sub_check.get('message')}")
            
    return payload

# --- 1. Master PIN & Auth API ---

@app.post("/api/verify-master-pin")
def verify_master_pin(req: PinVerifyReq):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM system_settings WHERE key = 'master_pin'")
    row = cursor.fetchone()
    conn.close()
    
    saved_pin = row["value"] if row else MASTER_PIN_DEFAULT
    if req.pin == saved_pin:
        return {"success": True, "message": "Master Access Granted"}
    raise HTTPException(status_code=401, detail="Invalid Master Access PIN")

class VerifyOtpReq(BaseModel):
    username: str
    otp: str
    device_token: Optional[str] = None

class PaymentOrderReq(BaseModel):
    amount: Optional[int] = None # in paise (>= 100 paise)
    currency: Optional[str] = "INR"
    receipt: Optional[str] = None
    plan_type: Optional[str] = None
    tenant_id: Optional[str] = ""
    notes: Optional[dict] = None

class PaymentVerifyReq(BaseModel):
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_signature: Optional[str] = None
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    signature: Optional[str] = None
    tenant_id: Optional[str] = ""
    plan_type: Optional[str] = ""

class Google2faSetupReq(BaseModel):
    username: str

class Google2faVerifyReq(BaseModel):
    username: str
    code: str

@app.post("/api/login")
def login(req: LoginReq):
    conn = get_db_connection()
    cursor = conn.cursor()

    if req.username.lower() == "owner":
        if req.password == "Esipfsolutions@Owner":
            cursor.execute('''
                INSERT OR REPLACE INTO users (id, tenant_id, username, email, password_hash, role, is_2fa_enabled)
                VALUES ('owner_usr_001', NULL, 'OwNeR', 'gulatihriday.003@gmail.com', ?, 'owner', 0)
            ''', (hash_password("Esipfsolutions@Owner"),))
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE username = 'OwNeR'")
            user = cursor.fetchone()
        else:
            cursor.execute("SELECT * FROM users WHERE LOWER(username) = 'owner'")
            user = cursor.fetchone()
    else:
        cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (req.username,))
        user = cursor.fetchone()

    if not user or not verify_password(req.password, user["password_hash"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user_dict = dict(user)
    if user_dict["tenant_id"]:
        sub_check = check_tenant_subscription(user_dict["tenant_id"])
        if sub_check.get("status") == "pending_approval":
            conn.close()
            raise HTTPException(
                status_code=403,
                detail="ACCESS PENDING APPROVAL: Your account request is awaiting Owner approval. You will be able to log in once the Owner approves your request."
            )
        if sub_check.get("status") == "rejected":
            conn.close()
            raise HTTPException(
                status_code=403,
                detail="ACCESS DECLINED: Your registration request was declined by the Owner. Please contact Administrator."
            )
        if sub_check.get("is_locked"):
            conn.close()
            raise HTTPException(
                status_code=403,
                detail=f"SUBSCRIPTION EXPIRED / ACCOUNT LOCKED. {sub_check.get('message')}"
            )

    # Check Device Trust (Remembered Device)
    if req.device_token:
        cursor.execute(
            "SELECT id FROM device_trust WHERE user_id = ? AND device_token = ?",
            (user_dict["id"], req.device_token)
        )
        trusted_row = cursor.fetchone()
        if trusted_row:
            conn.close()
            token = generate_jwt(user_dict["id"], user_dict["tenant_id"], user_dict["username"], user_dict["role"])
            tenant_info = None
            sub_warning = None
            if user_dict["tenant_id"]:
                tenant_info = check_tenant_subscription(user_dict["tenant_id"])
                sub_warning = tenant_info.get("warning")
            return {
                "success": True,
                "require_2fa": False,
                "token": token,
                "user": {
                    "id": user_dict["id"],
                    "username": user_dict["username"],
                    "email": user_dict["email"],
                    "role": user_dict["role"],
                    "tenant_id": user_dict["tenant_id"]
                },
                "subscription": tenant_info,
                "warning": sub_warning
            }

    conn.close()
    otp_code = generate_email_otp(user_dict["username"])
    # Send actual email in background thread so HTTP login returns in milliseconds with zero glitch
    threading.Thread(
        target=send_google_email_otp,
        args=(user_dict["email"], otp_code, user_dict["username"]),
        daemon=True
    ).start()
    masked_email = f"{user_dict['email'][:3]}***@{user_dict['email'].split('@')[-1]}" if user_dict.get('email') else "registered email"

    return {
        "success": True,
        "require_2fa": True,
        "username": user_dict["username"],
        "email_masked": masked_email,
        "message": f"2FA Security Code sent to {masked_email} via Google Mail."
    }

@app.post("/api/2fa/google-setup")
def google_2fa_setup(req: Google2faSetupReq):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (req.username,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
        
    user = dict(row)
    secret = user.get("totp_secret") or generate_totp_secret()
    cursor.execute("UPDATE users SET totp_secret = ? WHERE id = ?", (secret, user["id"]))
    conn.commit()
    conn.close()

    totp_uri = get_totp_uri(secret, req.username)
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={totp_uri}"

    return {
        "success": True,
        "secret": secret,
        "totp_uri": totp_uri,
        "qr_code_url": qr_url
    }

@app.post("/api/2fa/google-verify")
def google_2fa_verify(req: Google2faVerifyReq):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (req.username,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    user = dict(row)
    secret = user.get("totp_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Google 2FA not setup for this user")

    if not verify_totp(secret, req.code):
        raise HTTPException(status_code=401, detail="Invalid Google Authenticator code")

    return {"success": True, "message": "Google Authenticator 2FA verified successfully!"}


@app.post("/api/verify-otp")
def verify_otp_endpoint(req: VerifyOtpReq):
    if not verify_email_otp(req.username, req.otp):
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA security code.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (req.username,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    user_dict = dict(user)

    # Save Device Token for trusted device
    new_device_token = req.device_token or f"dev_trust_{uuid.uuid4().hex}"
    cursor.execute(
        "INSERT OR REPLACE INTO device_trust (user_id, device_token) VALUES (?, ?)",
        (user_dict["id"], new_device_token)
    )
    conn.commit()
    conn.close()

    tenant_info = None
    sub_warning = None
    if user_dict["tenant_id"]:
        sub_check = check_tenant_subscription(user_dict["tenant_id"])
        if sub_check.get("is_locked"):
            raise HTTPException(status_code=403, detail=f"ACCOUNT LOCKED: {sub_check.get('message')}")
        tenant_info = sub_check
        sub_warning = sub_check.get("warning")

    token = generate_jwt(user_dict["id"], user_dict["tenant_id"], user_dict["username"], user_dict["role"])

    return {
        "success": True,
        "token": token,
        "device_token": new_device_token,
        "user": {
            "id": user_dict["id"],
            "username": user_dict["username"],
            "email": user_dict["email"],
            "role": user_dict["role"],
            "tenant_id": user_dict["tenant_id"]
        },
        "subscription": tenant_info,
        "warning": sub_warning
    }

@app.post("/api/create-order")
@app.post("/api/payment/create-order")
def create_payment_order(req: PaymentOrderReq):
    # Determine amount in paise
    price_map = {"6_months": 12000.0, "1_year": 20000.0, "lifetime": 50000.0}
    amount_in_paise = None

    if req.amount is not None:
        amount_in_paise = int(req.amount)
    elif req.plan_type:
        price_rupees = price_map.get(req.plan_type, 20000.0)
        amount_in_paise = int(price_rupees * 100)
    else:
        amount_in_paise = 2000000 # Default to 1-year in paise

    # Validation: minimum 100 paise
    if amount_in_paise < 100:
        raise HTTPException(status_code=400, detail="Minimum order amount is 100 paise (INR 1.00).")

    currency = (req.currency or "INR").upper()
    receipt = req.receipt or f"rcpt_{uuid.uuid4().hex[:10]}"
    notes = req.notes or {}
    if req.plan_type:
        notes["plan_type"] = req.plan_type
    if req.tenant_id:
        notes["tenant_id"] = req.tenant_id

    client = get_razorpay_client()
    try:
        order = client.order.create({
            "amount": amount_in_paise,
            "currency": currency,
            "receipt": receipt,
            "notes": notes
        })
    except Exception as e:
        err_msg = str(e)
        if "Authentication failed" in err_msg or "auth" in err_msg.lower() or "401" in err_msg:
            raise HTTPException(status_code=401, detail="Razorpay Authentication Failed. Invalid Key ID or Secret.")
        raise HTTPException(status_code=500, detail=f"Razorpay order creation failed: {err_msg}")

    key_id, _ = get_razorpay_config()
    return {
        "success": True,
        "order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
        "key_id": key_id
    }

@app.post("/api/verify-payment")
@app.post("/api/payment/verify")
def verify_payment(req: PaymentVerifyReq):
    order_id = req.razorpay_order_id or req.order_id
    payment_id = req.razorpay_payment_id or req.payment_id
    signature = req.razorpay_signature or req.signature

    if not order_id or not payment_id or not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing required fields for payment verification: order_id, payment_id, and signature are required."
        )

    _, key_secret = get_razorpay_config()
    if not key_secret:
        raise HTTPException(status_code=500, detail="Razorpay secret key is not configured on the server.")

    # Algorithm: HMAC-SHA256(order_id + "|" + payment_id, KEY_SECRET)
    message = f"{order_id}|{payment_id}".encode("utf-8")
    generated_signature = hmac.new(
        key_secret.encode("utf-8"),
        message,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(generated_signature, signature):
        raise HTTPException(
            status_code=400,
            detail="Payment signature verification failed. Signatures do not match."
        )

    # If tenant_id is provided, activate subscription in database
    if req.tenant_id:
        conn = get_db_connection()
        cursor = conn.cursor()
        today = datetime.date.today()
        price_map = {"test_verify": 1.0, "6_months": 12000.0, "1_year": 20000.0, "lifetime": 50000.0}
        price = price_map.get(req.plan_type, 20000.0) if req.plan_type else 20000.0
        cursor.execute(
            "UPDATE tenants SET subscription_status = 'active', start_date = ?, price_paid = ? WHERE id = ?",
            (str(today), price, req.tenant_id)
        )
        conn.commit()
        conn.close()

    return {
        "success": True,
        "message": "Payment signature verified successfully!",
        "order_id": order_id,
        "payment_id": payment_id
    }


@app.post("/api/register-tenant")
def register_tenant(req: RegisterTenantReq):
    tenant_id = f"t_{uuid.uuid4().hex[:8]}"
    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    
    price_map = {"test_verify": 1.0, "6_months": 12000.0, "1_year": 20000.0, "lifetime": 50000.0}
    days_map = {"test_verify": 30, "6_months": 180, "1_year": 365, "lifetime": 36500}

    price = price_map.get(req.plan_type, 20000.0)
    days = days_map.get(req.plan_type, 365)
    start_date = datetime.date.today()
    expiry_date = start_date + datetime.timedelta(days=days)

    if req.mode == "razorpay":
        if not req.payment_id:
            raise HTTPException(status_code=400, detail="Razorpay payment verification is required to activate subscription directly.")
        # If signature and order_id are provided, verify signature
        if req.order_id and req.signature:
            _, key_secret = get_razorpay_config()
            if not key_secret:
                raise HTTPException(status_code=500, detail="Razorpay secret key is not configured on the server.")
            message = f"{req.order_id}|{req.payment_id}".encode("utf-8")
            gen_sig = hmac.new(key_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(gen_sig, req.signature):
                raise HTTPException(status_code=400, detail="Payment signature verification failed. Registration blocked.")
        status = "active"
        price_paid = price
        expiry = str(expiry_date)
        resp_msg = f"Payment verified! Organization '{req.organization_name}' activated successfully under plan '{req.plan_type}'."
    else:
        status = "pending_approval"
        price_paid = 0.0
        expiry = None
        resp_msg = f"Access request for '{req.organization_name}' submitted to Owner! Access will be granted once the Owner approves your request."

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO tenants (id, name, email, phone, plan_type, subscription_status, start_date, expiry_date, price_paid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tenant_id, req.organization_name, req.email, req.phone, req.plan_type, status, str(start_date), expiry, price_paid))

        cursor.execute('''
            INSERT INTO users (id, tenant_id, username, email, password_hash, role)
            VALUES (?, ?, ?, ?, ?, 'admin')
        ''', (user_id, tenant_id, req.admin_username, req.email, hash_password(req.admin_password)))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Registration failed: {str(e)}")
    
    conn.close()
    return {
        "success": True,
        "message": resp_msg,
        "tenant_id": tenant_id,
        "status": status
    }

class OwnerSettingsReq(BaseModel):
    gmail_app_password: Optional[str] = None
    gmail_user: Optional[str] = None
    google_script_url: Optional[str] = None
    razorpay_key_id: Optional[str] = None
    razorpay_key_secret: Optional[str] = None

@app.post("/api/owner/approve-request")
def approve_request(req: OwnerActionReq, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    return owner_approve_request(req.tenant_id)

@app.post("/api/owner/decline-request")
def decline_request(req: OwnerActionReq, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    return owner_decline_request(req.tenant_id)

@app.post("/api/owner/settings")
def update_owner_settings(req: OwnerSettingsReq, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    conn = get_db_connection()
    cursor = conn.cursor()
    if req.gmail_app_password is not None:
        cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gmail_app_password', ?)", (req.gmail_app_password.strip(),))
    if req.gmail_user is not None:
        cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gmail_user', ?)", (req.gmail_user.strip(),))
    if req.google_script_url is not None:
        cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('google_script_url', ?)", (req.google_script_url.strip(),))
    if req.razorpay_key_id is not None:
        cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('razorpay_key_id', ?)", (req.razorpay_key_id.strip(),))
    if req.razorpay_key_secret is not None:
        cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('razorpay_key_secret', ?)", (req.razorpay_key_secret.strip(),))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Platform & Gateway settings updated successfully."}

@app.get("/api/owner/settings")
def get_owner_settings(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    from security import get_email_settings
    settings = get_email_settings()
    key_id, key_secret = get_razorpay_config()
    return {
        "gmail_user": settings["email_user"],
        "has_app_pwd": bool(settings["app_pwd"]),
        "has_script_url": bool(settings["script_url"]),
        "script_url": settings["script_url"],
        "has_resend_key": bool(settings["resend_key"]),
        "razorpay_key_id": key_id or "",
        "has_razorpay_secret": bool(key_secret),
        "razorpay_mode": "Test Mode" if (key_id and key_id.startswith("rzp_test")) else ("Live Mode" if key_id else "Not Configured")
    }

@app.post("/api/owner/test-email")
def test_email_endpoint(req: dict, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    to_email = req.get("email", current_user.get("email", "gulatihriday.003@gmail.com"))
    res = send_google_email_otp(to_email, "777888", "test_user")
    return res

@app.post("/api/owner/test-razorpay")
def test_razorpay_endpoint(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    key_id, key_secret = get_razorpay_config()
    if not key_id or not key_secret:
        return {"success": False, "message": "Razorpay Key ID or Key Secret is not configured."}
    if not razorpay:
        return {"success": False, "message": "Razorpay Python SDK is not installed."}
    try:
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.create({
            "amount": 100,
            "currency": "INR",
            "receipt": f"test_auth_{uuid.uuid4().hex[:6]}"
        })
        is_test = key_id.startswith("rzp_test")
        return {
            "success": True,
            "mode": "Test Mode" if is_test else "Live Mode",
            "key_id": key_id,
            "message": f"Successfully connected to Razorpay ({'Test Mode' if is_test else 'Live Mode'})! Key pair is 100% active and verified."
        }
    except Exception as e:
        err_msg = str(e)
        if "Authentication failed" in err_msg or "auth" in err_msg.lower() or "401" in err_msg:
            return {"success": False, "message": "Authentication failed: Invalid Key ID or Secret. Please check your keys in Razorpay Dashboard."}
        return {"success": False, "message": f"Razorpay API error: {err_msg}"}

# --- 2. Owner Super Admin API (Edit / Undo / Controls) ---

@app.get("/api/owner/summary")
def owner_summary(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner Super-Admin privileges required.")
    return get_owner_dashboard_summary()

@app.post("/api/owner/lock")
def owner_lock(req: OwnerActionReq, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    return owner_lock_tenant(req.tenant_id)

@app.post("/api/owner/unlock")
def owner_unlock(req: OwnerActionReq, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    return owner_unlock_tenant(req.tenant_id)

@app.post("/api/owner/extend")
def owner_extend(req: OwnerActionReq, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    return owner_extend_subscription(req.tenant_id, req.days or 30)

@app.post("/api/owner/convert-lifetime")
def owner_lifetime(req: OwnerActionReq, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    return owner_convert_to_lifetime(req.tenant_id)

@app.post("/api/owner/update-tenant")
def owner_update(req: OwnerUpdateTenantReq, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    return owner_update_tenant(
        req.tenant_id, req.name, req.email, req.phone,
        req.plan_type, req.subscription_status, req.expiry_date, req.price_paid
    )

@app.post("/api/owner/undo-tenant")
def owner_undo(req: OwnerActionReq, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    return owner_undo_tenant_update(req.tenant_id)

@app.delete("/api/owner/tenant/{tenant_id}")
def owner_delete(tenant_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required.")
    return owner_delete_tenant(tenant_id)

# --- 3. Company & Employee CRUD ---

@app.get("/api/companies")
def get_companies(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user["tenant_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    if current_user["role"] == "owner":
        cursor.execute("SELECT * FROM companies ORDER BY created_at DESC")
    else:
        cursor.execute("SELECT * FROM companies WHERE tenant_id = ? ORDER BY created_at DESC", (tenant_id,))
    companies = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return companies

@app.post("/api/companies")
def create_company(req: CompanyReq, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id") or "owner_platform_tenant"
    comp_id = f"comp_{uuid.uuid4().hex[:8]}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO companies (
            id, tenant_id, company_name, registration_no, epf_code, esi_code, tan_no, pan_no,
            address, state, bank_name, account_no, ifsc_code,
            epf_emp_rate, epf_employer_rate, esi_emp_rate, esi_employer_rate
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        comp_id, tenant_id, req.company_name, req.registration_no, req.epf_code, req.esi_code,
        req.tan_no, req.pan_no, req.address, req.state, req.bank_name, req.account_no, req.ifsc_code,
        req.epf_emp_rate if req.epf_emp_rate is not None else 12.0,
        req.epf_employer_rate if req.epf_employer_rate is not None else 12.0,
        req.esi_emp_rate if req.esi_emp_rate is not None else 0.75,
        req.esi_employer_rate if req.esi_employer_rate is not None else 3.25
    ))
    conn.commit()
    conn.close()
    return {"success": True, "company_id": comp_id}

@app.put("/api/companies/{comp_id}")
def update_company(comp_id: str, req: CompanyReq, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE companies SET
            company_name = ?, registration_no = ?, epf_code = ?, esi_code = ?,
            tan_no = ?, pan_no = ?, address = ?, state = ?, bank_name = ?,
            account_no = ?, ifsc_code = ?,
            epf_emp_rate = ?, epf_employer_rate = ?, esi_emp_rate = ?, esi_employer_rate = ?
        WHERE id = ? AND (tenant_id = ? OR ? = 'owner')
    ''', (
        req.company_name, req.registration_no, req.epf_code, req.esi_code,
        req.tan_no, req.pan_no, req.address, req.state, req.bank_name,
        req.account_no, req.ifsc_code,
        req.epf_emp_rate if req.epf_emp_rate is not None else 12.0,
        req.epf_employer_rate if req.epf_employer_rate is not None else 12.0,
        req.esi_emp_rate if req.esi_emp_rate is not None else 0.75,
        req.esi_employer_rate if req.esi_employer_rate is not None else 3.25,
        comp_id, tenant_id, current_user.get("role")
    ))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Company profile & statutory rates updated successfully."}

@app.delete("/api/companies/{comp_id}")
def delete_company(comp_id: str, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tenant_id, company_name FROM companies WHERE id = ?", (comp_id,))
    comp = cursor.fetchone()
    if not comp:
        conn.close()
        raise HTTPException(status_code=404, detail="Company not found.")
    if current_user.get("role") != "owner" and comp["tenant_id"] != current_user.get("tenant_id"):
        conn.close()
        raise HTTPException(status_code=403, detail="Unauthorized.")
    cursor.execute("DELETE FROM companies WHERE id = ?", (comp_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Company '{comp['company_name']}' deleted successfully."}

@app.get("/api/employees")
def get_employees(company_id: str, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM employees WHERE company_id = ? ORDER BY emp_code ASC", (company_id,))
    employees = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return employees

@app.post("/api/employees")
def add_employee(req: EmployeeReq, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id") or "owner_platform_tenant"
    emp_id = f"emp_{uuid.uuid4().hex[:8]}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO employees (
            id, tenant_id, company_id, emp_code, name, email, designation, department, doj,
            pan, aadhaar, uan_no, esi_no, bank_name, bank_acc, ifsc_code,
            basic_pay, hra, conveyance, special_allowance, pf_deduct, esi_deduct, pt_deduct, tax_regime,
            custom_epf_rate, custom_esi_rate
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        emp_id, tenant_id, req.company_id, req.emp_code, req.name, req.email, req.designation, req.department, req.doj,
        req.pan, req.aadhaar, req.uan_no, req.esi_no, req.bank_name, req.bank_acc, req.ifsc_code,
        req.basic_pay, req.hra, req.conveyance, req.special_allowance, req.pf_deduct, req.esi_deduct, req.pt_deduct, req.tax_regime,
        req.custom_epf_rate, req.custom_esi_rate
    ))
    conn.commit()
    conn.close()
    return {"success": True, "emp_id": emp_id}

@app.put("/api/employees/{emp_id}")
def update_employee(emp_id: str, req: EmployeeReq, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE employees SET
            emp_code = ?, name = ?, email = ?, designation = ?, department = ?, doj = ?,
            pan = ?, aadhaar = ?, uan_no = ?, esi_no = ?, bank_name = ?, bank_acc = ?, ifsc_code = ?,
            basic_pay = ?, hra = ?, conveyance = ?, special_allowance = ?,
            pf_deduct = ?, esi_deduct = ?, pt_deduct = ?, tax_regime = ?,
            custom_epf_rate = ?, custom_esi_rate = ?
        WHERE id = ?
    ''', (
        req.emp_code, req.name, req.email, req.designation, req.department, req.doj,
        req.pan, req.aadhaar, req.uan_no, req.esi_no, req.bank_name, req.bank_acc, req.ifsc_code,
        req.basic_pay, req.hra, req.conveyance, req.special_allowance,
        req.pf_deduct, req.esi_deduct, req.pt_deduct, req.tax_regime,
        req.custom_epf_rate, req.custom_esi_rate,
        emp_id
    ))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Employee details and custom rates updated successfully."}

@app.delete("/api/employees/{emp_id}")
def delete_employee(emp_id: str, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Employee record removed."}

# --- 4. Loans & Statutory Calculators ---

@app.get("/api/loans")
def get_loans(company_id: str, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT l.*, e.name as emp_name, e.emp_code
        FROM loans l
        JOIN employees e ON l.emp_id = e.id
        WHERE l.company_id = ?
        ORDER BY l.created_at DESC
    ''', (company_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@app.post("/api/loans")
def create_loan(req: LoanReq, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id") or "owner_platform_tenant"
    loan_id = f"loan_{uuid.uuid4().hex[:8]}"
    emi_amount = round(req.loan_amount / float(req.total_emi)) if req.total_emi > 0 else req.loan_amount
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO loans (id, tenant_id, company_id, emp_id, loan_amount, emi_amount, total_emi, paid_emi, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'active')
    ''', (loan_id, tenant_id, req.company_id, req.emp_id, req.loan_amount, emi_amount, req.total_emi))
    conn.commit()
    conn.close()
    return {"success": True, "loan_id": loan_id, "emi_amount": emi_amount}

@app.post("/api/calculators/gratuity")
def calc_gratuity_api(req: GratuityReq):
    return calculate_gratuity(req.basic_pay, req.years_of_service)

@app.post("/api/calculators/bonus")
def calc_bonus_api(req: BonusReq):
    bonus_amt = calculate_bonus(req.basic_pay, req.percentage or 8.33)
    return {"success": True, "basic_pay": req.basic_pay, "bonus_annual": bonus_amt}

# --- 5. Attendance & Payroll Run API ---

@app.get("/api/attendance")
def get_attendance(company_id: str, month_year: str, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM attendance WHERE company_id = ? AND month_year = ?", (company_id, month_year))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@app.post("/api/attendance")
def save_attendance(req: AttendanceReq, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id") or "owner_platform_tenant"
    att_id = f"att_{req.emp_id}_{req.month_year}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO attendance (id, tenant_id, company_id, emp_id, month_year, total_working_days, days_worked, casual_leaves, medical_leaves, privilege_leaves, loss_of_pay_days, overtime_hours)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        att_id, tenant_id, req.company_id, req.emp_id, req.month_year,
        req.total_working_days, req.days_worked, req.casual_leaves, req.medical_leaves, req.privilege_leaves, req.loss_of_pay_days, req.overtime_hours
    ))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/api/payroll/process")
def process_payroll(req: ProcessPayrollReq, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id") or "owner_platform_tenant"
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM companies WHERE id = ?", (req.company_id,))
    comp_row = cursor.fetchone()
    state = comp_row["state"] if comp_row else "Maharashtra"

    cursor.execute("SELECT * FROM employees WHERE company_id = ?", (req.company_id,))
    employees = [dict(r) for r in cursor.fetchall()]

    processed_count = 0
    total_disbursement = 0.0

    for emp in employees:
        emp_id = emp["id"]
        cursor.execute("SELECT * FROM attendance WHERE emp_id = ? AND month_year = ?", (emp_id, req.month_year))
        att = cursor.fetchone()
        
        working_days = att["total_working_days"] if att else 30
        days_worked = att["days_worked"] if att else 30
        lop_days = att["loss_of_pay_days"] if att else 0
        overtime_hours = att["overtime_hours"] if att else 0.0

        prorate_factor = (working_days - lop_days) / float(working_days) if working_days > 0 else 1.0
        
        basic_paid = round(emp["basic_pay"] * prorate_factor)
        hra_paid = round(emp["hra"] * prorate_factor)
        allowances_paid = round((emp["conveyance"] + emp["special_allowance"]) * prorate_factor)
        
        hourly_rate = (emp["basic_pay"] / 240.0) * 1.5 if emp["basic_pay"] > 0 else 0
        overtime_pay = round(overtime_hours * hourly_rate)

        gross_salary = basic_paid + hra_paid + allowances_paid + overtime_pay

        # Customizable statutory rates
        comp_pf_rate = (comp_row["epf_emp_rate"] / 100.0) if (comp_row and comp_row["epf_emp_rate"] is not None) else 0.12
        comp_pf_employer_rate = (comp_row["epf_employer_rate"] / 100.0) if (comp_row and comp_row["epf_employer_rate"] is not None) else 0.12
        emp_pf_rate = (emp["custom_epf_rate"] / 100.0) if emp.get("custom_epf_rate") is not None else comp_pf_rate

        comp_esi_rate = (comp_row["esi_emp_rate"] / 100.0) if (comp_row and comp_row["esi_emp_rate"] is not None) else 0.0075
        comp_esi_employer_rate = (comp_row["esi_employer_rate"] / 100.0) if (comp_row and comp_row["esi_employer_rate"] is not None) else 0.0325
        emp_esi_rate = (emp["custom_esi_rate"] / 100.0) if emp.get("custom_esi_rate") is not None else comp_esi_rate

        epf_res = calculate_epf(basic_paid, emp_rate=emp_pf_rate, employer_rate=comp_pf_employer_rate) if emp["pf_deduct"] else {"epf_emp": 0.0, "eps_employer": 0.0, "epf_employer": 0.0}
        esi_res = calculate_esi(gross_salary, emp_rate=emp_esi_rate, employer_rate=comp_esi_employer_rate) if emp["esi_deduct"] else {"esi_emp": 0.0, "esi_employer": 0.0}

        month_num = req.month_year.split("-")[1] if "-" in req.month_year else "01"
        pt_deduct = calculate_professional_tax(gross_salary, state=state, month=month_num) if emp["pt_deduct"] else 0.0

        annual_gross = gross_salary * 12
        tds_deduct = calculate_tds_estimate(annual_gross, regime=emp.get("tax_regime", "new"))

        cursor.execute("SELECT * FROM loans WHERE emp_id = ? AND status = 'active'", (emp_id,))
        loan = cursor.fetchone()
        loan_emi = loan["emi_amount"] if loan else 0.0

        lop_deduction = round((emp["basic_pay"] + emp["hra"]) * (lop_days / float(working_days))) if lop_days > 0 else 0.0

        total_deductions = epf_res["epf_emp"] + esi_res["esi_emp"] + pt_deduct + tds_deduct + loan_emi + lop_deduction
        net_salary = max(0.0, gross_salary - total_deductions)

        run_id = f"pay_{emp_id}_{req.month_year}"
        cursor.execute('''
            INSERT OR REPLACE INTO payroll_runs (
                id, tenant_id, company_id, month_year, emp_id, gross_salary,
                basic_paid, hra_paid, allowances_paid, overtime_pay,
                epf_emp, epf_employer, esi_emp, esi_employer, pt_deduction, tds_deduction,
                lop_deduction, loan_emi, total_deductions, net_salary, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'processed')
        ''', (
            run_id, tenant_id, req.company_id, req.month_year, emp_id, gross_salary,
            basic_paid, hra_paid, allowances_paid, overtime_pay,
            epf_res["epf_emp"], epf_res["epf_employer"], esi_res["esi_emp"], esi_res["esi_employer"],
            pt_deduct, tds_deduct, lop_deduction, loan_emi, total_deductions, net_salary
        ))

        processed_count += 1
        total_disbursement += net_salary

    conn.commit()
    conn.close()
    return {
        "success": True,
        "month_year": req.month_year,
        "processed_employees": processed_count,
        "total_disbursement": total_disbursement
    }

@app.get("/api/payroll/runs")
def get_payroll_runs(company_id: str, month_year: str, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.*, e.name as emp_name, e.emp_code, e.bank_acc, e.ifsc_code, e.uan_no, e.esi_no
        FROM payroll_runs p
        JOIN employees e ON p.emp_id = e.id
        WHERE p.company_id = ? AND p.month_year = ?
    ''', (company_id, month_year))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

# --- 6. Statutory Exporters & PDF Pay Slips ---

@app.get("/api/reports/epf-ecr")
def export_epf_ecr(company_id: str, month_year: str, current_user: dict = Depends(get_current_user)):
    runs = get_payroll_runs(company_id, month_year, current_user)
    ecr_text = generate_epf_ecr_file(runs)
    return Response(
        content=ecr_text,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=EPF_ECR_{month_year}.txt"}
    )

@app.get("/api/reports/esi-csv")
def export_esi_csv(company_id: str, month_year: str, current_user: dict = Depends(get_current_user)):
    runs = get_payroll_runs(company_id, month_year, current_user)
    csv_text = generate_esi_challan_csv(runs)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=ESI_Return_{month_year}.csv"}
    )

@app.get("/api/reports/bank-disbursement")
def export_bank_csv(company_id: str, month_year: str, current_user: dict = Depends(get_current_user)):
    runs = get_payroll_runs(company_id, month_year, current_user)
    csv_data = generate_bank_disbursement_csv(runs)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=Bank_Transfer_{month_year}.csv"}
    )

@app.get("/api/reports/payslip-pdf")
def download_payslip_pdf(company_id: str, emp_id: str, month_year: str, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
    company = dict(cursor.fetchone())

    cursor.execute("SELECT * FROM employees WHERE id = ?", (emp_id,))
    employee = dict(cursor.fetchone())

    cursor.execute("SELECT * FROM payroll_runs WHERE emp_id = ? AND month_year = ?", (emp_id, month_year))
    payroll_row = cursor.fetchone()
    if not payroll_row:
        raise HTTPException(status_code=404, detail="Payroll run not found for this employee and month.")
    payroll = dict(payroll_row)

    conn.close()

    pdf_bytes = generate_pdf_payslip(company, employee, payroll)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=PaySlip_{employee['emp_code']}_{month_year}.pdf"}
    )

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
def root_page():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cwd = os.getcwd()
    possible_paths = [
        os.path.join(TEMPLATES_DIR, "index.html"),
        os.path.join(cwd, "templates", "index.html"),
        os.path.join(cwd, "index.html"),
        os.path.join(base_dir, "..", "templates", "index.html"),
        os.path.join(base_dir, "..", "index.html"),
        os.path.join(base_dir, "index.html"),
        os.path.join(base_dir, "templates", "index.html"),
        "templates/index.html",
        "index.html",
        "servagya_payroll/templates/index.html",
        "servagya_payroll/index.html"
    ]
    for p in possible_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
    return f"<h1>esipfsolutions Enterprise Cloud Engine Running</h1><p>Debug info - CWD: {cwd} | BaseDir: {base_dir}</p>"




if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
