import datetime
from database import init_db, get_db_connection
from security import hash_password

def seed():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. System Master PIN
    cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('master_pin', '9999')")

    # 2. Clear out all sample demo data
    cursor.execute("DELETE FROM users WHERE role != 'owner'")
    cursor.execute("DELETE FROM tenants")
    cursor.execute("DELETE FROM companies")
    cursor.execute("DELETE FROM employees")
    cursor.execute("DELETE FROM loans")
    cursor.execute("DELETE FROM attendance")
    cursor.execute("DELETE FROM payroll_runs")
    cursor.execute("DELETE FROM tenant_backups")

    # 3. Create Clean Owner Super Admin Account ONLY
    cursor.execute('''
        INSERT OR REPLACE INTO users (id, tenant_id, username, email, password_hash, role, is_2fa_enabled)
        VALUES ('owner_usr_001', NULL, 'OwNeR', 'gulatihriday.003@gmail.com', ?, 'owner', 0)
    ''', (hash_password("Esipfsolutions@Owner"),))

    conn.commit()
    conn.close()
    print("Database cleaned! Only Owner Account 'OwNeR' and Master PIN '9999' remain.")

if __name__ == "__main__":
    seed()
