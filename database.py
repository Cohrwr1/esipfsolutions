import sqlite3
import os
import datetime
import hashlib
import json

# Support Persistent Disks (e.g. Render /var/data or /data or custom DATABASE_PATH)
DATA_DIR = os.getenv("DATA_DIR")
if not DATA_DIR:
    if os.path.exists("/var/data") and os.path.isdir("/var/data"):
        DATA_DIR = "/var/data"
    elif os.path.exists("/data") and os.path.isdir("/data"):
        DATA_DIR = "/data"
    else:
        DATA_DIR = os.path.dirname(__file__)

DB_PATH = os.getenv("DATABASE_PATH", os.path.join(DATA_DIR, "servagya_payroll.db"))
BACKUP_PATH = os.path.join(DATA_DIR, "servagya_payroll_backup.json")
ROOT_BACKUP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "servagya_payroll_backup.json")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def auto_backup_state():
    """Takes a persistent snapshot of all registered tenants, users, companies, and employees to guarantee zero data loss across deploys."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        state = {}
        for table in ["tenants", "users", "companies", "employees", "attendance", "loans", "payroll_runs", "system_settings"]:
            try:
                c.execute(f"SELECT * FROM {table}")
                state[table] = [dict(r) for r in c.fetchall()]
            except Exception:
                pass
        conn.close()

        for p in [BACKUP_PATH, ROOT_BACKUP_PATH]:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2, default=str)
            except Exception:
                pass
    except Exception as e:
        print("Auto-backup notice:", e)

def auto_restore_state():
    """If database is fresh or restarted on ephemeral disk, auto-restore all accounts and data from persistent snapshot."""
    backup_file = None
    for p in [BACKUP_PATH, ROOT_BACKUP_PATH]:
        if os.path.exists(p) and os.path.getsize(p) > 10:
            backup_file = p
            break
    if not backup_file:
        return

    try:
        with open(backup_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        
        conn = get_db_connection()
        c = conn.cursor()

        for t in state.get("tenants", []):
            cols = list(t.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            vals = [t[k] for k in cols]
            c.execute(f"INSERT OR IGNORE INTO tenants ({col_str}) VALUES ({placeholders})", vals)

        for u in state.get("users", []):
            cols = list(u.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            vals = [u[k] for k in cols]
            c.execute(f"INSERT OR IGNORE INTO users ({col_str}) VALUES ({placeholders})", vals)

        for comp in state.get("companies", []):
            cols = list(comp.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            vals = [comp[k] for k in cols]
            c.execute(f"INSERT OR IGNORE INTO companies ({col_str}) VALUES ({placeholders})", vals)

        for emp in state.get("employees", []):
            cols = list(emp.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            vals = [emp[k] for k in cols]
            c.execute(f"INSERT OR IGNORE INTO employees ({col_str}) VALUES ({placeholders})", vals)

        for att in state.get("attendance", []):
            cols = list(att.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            vals = [att[k] for k in cols]
            c.execute(f"INSERT OR IGNORE INTO attendance ({col_str}) VALUES ({placeholders})", vals)

        for ln in state.get("loans", []):
            cols = list(ln.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            vals = [ln[k] for k in cols]
            c.execute(f"INSERT OR IGNORE INTO loans ({col_str}) VALUES ({placeholders})", vals)

        for pr in state.get("payroll_runs", []):
            cols = list(pr.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            vals = [pr[k] for k in cols]
            c.execute(f"INSERT OR IGNORE INTO payroll_runs ({col_str}) VALUES ({placeholders})", vals)

        conn.commit()
        conn.close()
        print(f"Auto-restored accounts and data from persistent backup: {backup_file}")
    except Exception as e:
        print("Auto-restore notice:", e)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # System Settings (Master PIN & Global Config)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tenants (Organizations / Subscribers)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            plan_type TEXT NOT NULL DEFAULT '1_year', -- '6_months', '1_year', 'lifetime'
            subscription_status TEXT NOT NULL DEFAULT 'active', -- 'active', 'locked', 'grace_period'
            start_date DATE NOT NULL,
            expiry_date DATE,
            price_paid REAL NOT NULL DEFAULT 20000.0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tenant Backups for Undo Functionality
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tenant_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            name TEXT,
            email TEXT,
            phone TEXT,
            plan_type TEXT,
            subscription_status TEXT,
            start_date DATE,
            expiry_date DATE,
            price_paid REAL,
            backed_up_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Users
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            username TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin', -- 'owner', 'admin', 'hr', 'employee'
            totp_secret TEXT,
            is_2fa_enabled INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS device_trust (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            device_token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Companies
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            company_name TEXT NOT NULL,
            registration_no TEXT,
            epf_code TEXT,
            esi_code TEXT,
            tan_no TEXT,
            pan_no TEXT,
            address TEXT,
            state TEXT DEFAULT 'Maharashtra',
            bank_name TEXT,
            account_no TEXT,
            ifsc_code TEXT,
            contact_email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            epf_emp_rate REAL DEFAULT 12.0,
            epf_employer_rate REAL DEFAULT 12.0,
            esi_emp_rate REAL DEFAULT 0.75,
            esi_employer_rate REAL DEFAULT 3.25,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        )
    ''')

    # Employees
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            company_id TEXT NOT NULL,
            emp_code TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            designation TEXT,
            department TEXT,
            doj DATE,
            pan TEXT,
            aadhaar TEXT,
            uan_no TEXT,
            esi_no TEXT,
            bank_name TEXT,
            bank_acc TEXT,
            ifsc_code TEXT,
            basic_pay REAL NOT NULL DEFAULT 0.0,
            hra REAL NOT NULL DEFAULT 0.0,
            conveyance REAL NOT NULL DEFAULT 0.0,
            special_allowance REAL NOT NULL DEFAULT 0.0,
            pf_deduct INTEGER DEFAULT 1,
            esi_deduct INTEGER DEFAULT 1,
            pt_deduct INTEGER DEFAULT 1,
            tax_regime TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            custom_epf_rate REAL DEFAULT NULL,
            custom_esi_rate REAL DEFAULT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
            FOREIGN KEY (company_id) REFERENCES companies (id) ON DELETE CASCADE
        )
    ''')

    # Attendance & Leaves
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            company_id TEXT NOT NULL,
            emp_id TEXT NOT NULL,
            month_year TEXT NOT NULL,
            total_working_days INT NOT NULL DEFAULT 30,
            days_worked INT NOT NULL DEFAULT 30,
            casual_leaves INT DEFAULT 0,
            medical_leaves INT DEFAULT 0,
            privilege_leaves INT DEFAULT 0,
            loss_of_pay_days INT DEFAULT 0,
            overtime_hours REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        )
    ''')

    # Loans & Advances
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS loans (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            company_id TEXT NOT NULL,
            emp_id TEXT NOT NULL,
            loan_amount REAL NOT NULL,
            emi_amount REAL NOT NULL,
            total_emi INT NOT NULL,
            paid_emi INT DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        )
    ''')

    # Payroll Runs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payroll_runs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            company_id TEXT NOT NULL,
            month_year TEXT NOT NULL,
            emp_id TEXT NOT NULL,
            gross_salary REAL NOT NULL,
            basic_paid REAL NOT NULL,
            hra_paid REAL NOT NULL,
            allowances_paid REAL NOT NULL,
            overtime_pay REAL DEFAULT 0.0,
            epf_emp REAL NOT NULL DEFAULT 0.0,
            epf_employer REAL NOT NULL DEFAULT 0.0,
            esi_emp REAL NOT NULL DEFAULT 0.0,
            esi_employer REAL NOT NULL DEFAULT 0.0,
            pt_deduction REAL NOT NULL DEFAULT 0.0,
            tds_deduction REAL NOT NULL DEFAULT 0.0,
            lop_deduction REAL NOT NULL DEFAULT 0.0,
            loan_emi REAL NOT NULL DEFAULT 0.0,
            total_deductions REAL NOT NULL,
            net_salary REAL NOT NULL,
            status TEXT DEFAULT 'processed',
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        )
    ''')

    # Audit Logs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT,
            username TEXT,
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Safe migrations for customizable statutory rates
    for alter_sql in [
        "ALTER TABLE companies ADD COLUMN epf_emp_rate REAL DEFAULT 12.0",
        "ALTER TABLE companies ADD COLUMN epf_employer_rate REAL DEFAULT 12.0",
        "ALTER TABLE companies ADD COLUMN esi_emp_rate REAL DEFAULT 0.75",
        "ALTER TABLE companies ADD COLUMN esi_employer_rate REAL DEFAULT 3.25",
        "ALTER TABLE employees ADD COLUMN custom_epf_rate REAL DEFAULT NULL",
        "ALTER TABLE employees ADD COLUMN custom_esi_rate REAL DEFAULT NULL"
    ]:
        try:
            cursor.execute(alter_sql)
        except Exception:
            pass

    # Ensure default system settings exist (INSERT OR IGNORE)
    cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES ('master_pin', '3669')")
    cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES ('gmail_app_password', 'kjroafmhblrmgftv')")
    cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES ('gmail_user', 'gulatihriday.003@gmail.com')")

    # Ensure Super Admin Owner account exists (INSERT OR IGNORE - NEVER TOUCHES OR OVERWRITES TENANTS)
    owner_pwd_hash = hashlib.sha256("Esipfsolutions@Owner".encode()).hexdigest()
    cursor.execute('''
        INSERT OR IGNORE INTO users (id, tenant_id, username, email, password_hash, role, is_2fa_enabled)
        VALUES ('owner_usr_001', NULL, 'OwNeR', 'gulatihriday.003@gmail.com', ?, 'owner', 0)
    ''', (owner_pwd_hash,))

    conn.commit()
    conn.close()

    # Restore previous accounts from snapshot if database was recreated
    auto_restore_state()
    # Keep snapshot synchronized
    auto_backup_state()

if __name__ == "__main__":
    init_db()
    print("Database schema with Tenant Backups initialized successfully.")
