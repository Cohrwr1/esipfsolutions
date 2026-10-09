import datetime
from database import init_db, get_db_connection
from security import hash_password, generate_totp_secret

def seed():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. System Master PIN
    cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('master_pin', '9999')")

    # 2. Owner Super Admin Account (User)
    cursor.execute('''
        INSERT OR REPLACE INTO users (id, tenant_id, username, email, password_hash, role, is_2fa_enabled)
        VALUES ('owner_usr_001', NULL, 'owner', 'owner@servagyapayroll.com', ?, 'owner', 0)
    ''', (hash_password("owner123"),))

    # 3. Tenants (Subscribers)
    # Active 1-Year Tenant
    today = datetime.date.today()
    exp_1yr = str(today + datetime.timedelta(days=365))
    exp_6mo = str(today + datetime.timedelta(days=180))
    exp_locked = str(today - datetime.timedelta(days=10))

    cursor.execute('''
        INSERT OR REPLACE INTO tenants (id, name, email, phone, plan_type, subscription_status, start_date, expiry_date, price_paid)
        VALUES ('t_apex_01', 'Apex Global Technologies', 'admin@apextech.com', '+91 9876543210', '1_year', 'active', ?, ?, 20000.0)
    ''', (str(today), exp_1yr))

    cursor.execute('''
        INSERT OR REPLACE INTO tenants (id, name, email, phone, plan_type, subscription_status, start_date, expiry_date, price_paid)
        VALUES ('t_zenith_02', 'Zenith Logistics Solutions', 'hr@zenithlogistics.com', '+91 9811223344', '6_months', 'active', ?, ?, 10000.0)
    ''', (str(today), exp_6mo))

    cursor.execute('''
        INSERT OR REPLACE INTO tenants (id, name, email, phone, plan_type, subscription_status, start_date, expiry_date, price_paid)
        VALUES ('t_horizon_03', 'Horizon Trade Corporation', 'accounts@horizontrade.com', '+91 9988776655', '6_months', 'locked', ?, ?, 10000.0)
    ''', (str(today - datetime.timedelta(days=190)), exp_locked))

    # Admin User for Tenant 1 (Apex)
    cursor.execute('''
        INSERT OR REPLACE INTO users (id, tenant_id, username, email, password_hash, role, is_2fa_enabled)
        VALUES ('usr_apex_admin', 't_apex_01', 'apex_admin', 'admin@apextech.com', ?, 'admin', 0)
    ''', (hash_password("apex123"),))

    # 4. Companies inside Tenant 1
    cursor.execute('''
        INSERT OR REPLACE INTO companies (id, tenant_id, company_name, epf_code, esi_code, tan_no, pan_no, address, state, bank_name, account_no, ifsc_code)
        VALUES (
            'comp_apex_01', 't_apex_01', 'Apex Global Software India Pvt Ltd',
            'MH/BAN/0045812', '31000458120001001', 'MUMB12345F', 'AAACA1234F',
            'Suite 402, Cyber Heights, BKC, Mumbai - 400051', 'Maharashtra',
            'HDFC Bank', '50200012345678', 'HDFC0000123'
        )
    ''')

    # 5. Employees inside Company
    emps = [
        (
            'emp_001', 't_apex_01', 'comp_apex_01', 'EMP001', 'Rajesh Sharma', 'rajesh@apextech.com',
            'Senior Software Architect', 'Engineering', '2022-04-15', 'ABCDE1234F', '123456789012',
            '100987654321', '3109876543', 'HDFC Bank', '50100234567890', 'HDFC0000123',
            45000.0, 22500.0, 2000.0, 10500.0, 1, 0, 1, 'new'
        ),
        (
            'emp_002', 't_apex_01', 'comp_apex_01', 'EMP002', 'Priya Verma', 'priya@apextech.com',
            'HR Manager', 'Human Resources', '2023-01-10', 'BPVPV5678G', '987654321098',
            '100123456789', '3101234567', 'ICICI Bank', '000401567890', 'ICIC0000004',
            30000.0, 15000.0, 2000.0, 8000.0, 1, 0, 1, 'new'
        ),
        (
            'emp_003', 't_apex_01', 'comp_apex_01', 'EMP003', 'Amit Kumar', 'amit@apextech.com',
            'Junior Accountant', 'Finance', '2024-06-01', 'CPKAK9012H', '456789012345',
            '100456789012', '3104567890', 'State Bank of India', '30987654321', 'SBIN0001234',
            14000.0, 6000.0, 1000.0, 2000.0, 1, 1, 1, 'new'
        )
    ]

    for emp in emps:
        cursor.execute('''
            INSERT OR REPLACE INTO employees (
                id, tenant_id, company_id, emp_code, name, email,
                designation, department, doj, pan, aadhaar,
                uan_no, esi_no, bank_name, bank_acc, ifsc_code,
                basic_pay, hra, conveyance, special_allowance, pf_deduct, esi_deduct, pt_deduct, tax_regime
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', emp)

    # 6. Sample Attendance & Payroll Run for Oct 2026
    month = "2026-10"
    for emp_id in ['emp_001', 'emp_002', 'emp_003']:
        cursor.execute('''
            INSERT OR REPLACE INTO attendance (id, tenant_id, company_id, emp_id, month_year, total_working_days, days_worked, casual_leaves, medical_leaves, loss_of_pay_days, overtime_hours)
            VALUES (?, 't_apex_01', 'comp_apex_01', ?, ?, 30, 30, 0, 0, 0, 0.0)
        ''', (f"att_{emp_id}_{month}", emp_id, month))

    conn.commit()
    conn.close()
    print("Database seeded with Master PIN, Owner Account, Tenants, Companies, and Sample Employees.")

if __name__ == "__main__":
    seed()
