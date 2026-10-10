import datetime
from database import init_db, get_db_connection
from security import hash_password

def seed():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. System Master PIN & Google Mail Credentials
    cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('master_pin', '3669')")
    cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gmail_app_password', 'kjroafmhblrmgftv')")
    cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gmail_user', 'gulatihriday.003@gmail.com')")

    # 2. Ensure Clean Owner Super Admin Account exists without touching tenant accounts
    cursor.execute('''
        INSERT OR IGNORE INTO users (id, tenant_id, username, email, password_hash, role, is_2fa_enabled)
        VALUES ('owner_usr_001', NULL, 'OwNeR', 'gulatihriday.003@gmail.com', ?, 'owner', 0)
    ''', (hash_password("Esipfsolutions@Owner"),))

    conn.commit()
    conn.close()
    print("Database verified: Owner account and system settings initialized. User accounts preserved.")

if __name__ == "__main__":
    seed()
