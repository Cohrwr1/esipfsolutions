import datetime
import uuid
import os
from fastapi import FastAPI, HTTPException, Depends, Header, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel
from typing import Optional, List

from database import get_db_connection, init_db
from security import (
    hash_password, verify_password, generate_jwt, decode_jwt,
    generate_totp_secret, verify_totp, MASTER_PIN_DEFAULT
)
from subscription_engine import (
    check_tenant_subscription, get_owner_dashboard_summary,
    owner_lock_tenant, owner_unlock_tenant, owner_extend_subscription, owner_convert_to_lifetime,
    owner_update_tenant, owner_undo_tenant_update, owner_delete_tenant
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

# Request Models
class PinVerifyReq(BaseModel):
    pin: str

class LoginReq(BaseModel):
    username: str
    password: str

class RegisterTenantReq(BaseModel):
    organization_name: str
    email: str
    phone: str
    admin_username: str
    admin_password: str
    plan_type: str # '6_months', '1_year', 'lifetime'

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

class EmployeeReq(BaseModel):
    company_id: str
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
    conveyance: float
    special_allowance: float
    pf_deduct: int = 1
    esi_deduct: int = 1
    pt_deduct: int = 1
    tax_regime: str = "new"

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

def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authentication Header")
    token = authorization.replace("Bearer ", "").strip()
    payload = decode_jwt(token)
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

@app.post("/api/login")
def login(req: LoginReq):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (req.username,))
    user = cursor.fetchone()
    conn.close()

    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    tenant_info = None
    sub_warning = None
    if user["tenant_id"]:
        sub_check = check_tenant_subscription(user["tenant_id"])
        if sub_check.get("is_locked"):
            raise HTTPException(
                status_code=403,
                detail=f"SUBSCRIPTION EXPIRED / ACCOUNT LOCKED. {sub_check.get('message')}"
            )
        tenant_info = sub_check
        sub_warning = sub_check.get("warning")

    token = generate_jwt(user["id"], user["tenant_id"], user["username"], user["role"])

    return {
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
            "tenant_id": user["tenant_id"]
        },
        "subscription": tenant_info,
        "warning": sub_warning
    }

@app.post("/api/register-tenant")
def register_tenant(req: RegisterTenantReq):
    tenant_id = f"t_{uuid.uuid4().hex[:8]}"
    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    
    price_map = {"6_months": 12000.0, "1_year": 20000.0, "lifetime": 50000.0}
    days_map = {"6_months": 180, "1_year": 365, "lifetime": 36500}

    price = price_map.get(req.plan_type, 20000.0)
    days = days_map.get(req.plan_type, 365)
    start_date = datetime.date.today()
    expiry_date = start_date + datetime.timedelta(days=days)

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO tenants (id, name, email, phone, plan_type, subscription_status, start_date, expiry_date, price_paid)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
        ''', (tenant_id, req.organization_name, req.email, req.phone, req.plan_type, str(start_date), str(expiry_date), price))

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
        "message": f"Organization '{req.organization_name}' registered successfully under plan '{req.plan_type}'.",
        "tenant_id": tenant_id
    }

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
    tenant_id = current_user["tenant_id"]
    comp_id = f"comp_{uuid.uuid4().hex[:8]}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO companies (id, tenant_id, company_name, registration_no, epf_code, esi_code, tan_no, pan_no, address, state, bank_name, account_no, ifsc_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (comp_id, tenant_id, req.company_name, req.registration_no, req.epf_code, req.esi_code, req.tan_no, req.pan_no, req.address, req.state, req.bank_name, req.account_no, req.ifsc_code))
    conn.commit()
    conn.close()
    return {"success": True, "company_id": comp_id}

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
    tenant_id = current_user["tenant_id"]
    emp_id = f"emp_{uuid.uuid4().hex[:8]}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO employees (
            id, tenant_id, company_id, emp_code, name, email, designation, department, doj,
            pan, aadhaar, uan_no, esi_no, bank_name, bank_acc, ifsc_code,
            basic_pay, hra, conveyance, special_allowance, pf_deduct, esi_deduct, pt_deduct, tax_regime
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        emp_id, tenant_id, req.company_id, req.emp_code, req.name, req.email, req.designation, req.department, req.doj,
        req.pan, req.aadhaar, req.uan_no, req.esi_no, req.bank_name, req.bank_acc, req.ifsc_code,
        req.basic_pay, req.hra, req.conveyance, req.special_allowance, req.pf_deduct, req.esi_deduct, req.pt_deduct, req.tax_regime
    ))
    conn.commit()
    conn.close()
    return {"success": True, "emp_id": emp_id}

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
    tenant_id = current_user["tenant_id"]
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
    tenant_id = current_user["tenant_id"]
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
    tenant_id = current_user["tenant_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT state FROM companies WHERE id = ?", (req.company_id,))
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

        epf_res = calculate_epf(basic_paid) if emp["pf_deduct"] else {"epf_emp": 0.0, "eps_employer": 0.0, "epf_employer": 0.0}
        esi_res = calculate_esi(gross_salary) if emp["esi_deduct"] else {"esi_emp": 0.0, "esi_employer": 0.0}

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
    possible_paths = [
        os.path.join(TEMPLATES_DIR, "index.html"),
        os.path.join(os.getcwd(), "templates", "index.html"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "index.html"),
        "templates/index.html"
    ]
    for p in possible_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
    return "<h1>esipfsolutions Enterprise Cloud Engine Running (Template Not Found)</h1>"

