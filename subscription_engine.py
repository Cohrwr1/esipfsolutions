import datetime
from database import get_db_connection, auto_backup_state

PRICING_TIERS = {
    "6_months": {"name": "6 Months Subscription", "price": 12000.0, "days": 180},
    "1_year": {"name": "1 Year Subscription", "price": 20000.0, "days": 365},
    "lifetime": {"name": "Lifetime Unlimited License", "price": 50000.0, "days": 36500}
}

def check_tenant_subscription(tenant_id: str) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
    tenant = cursor.fetchone()
    conn.close()

    if not tenant:
        return {"status": "invalid", "message": "Tenant organization not found"}

    status = tenant["subscription_status"]
    plan_type = tenant["plan_type"]
    expiry_str = tenant["expiry_date"]

    if status == "pending_approval":
        return {
            "status": "pending_approval",
            "is_locked": True,
            "message": "ACCOUNT AWAITING OWNER APPROVAL. Please wait for the Owner to approve your access request."
        }

    if status == "rejected":
        return {
            "status": "rejected",
            "is_locked": True,
            "message": "ACCOUNT ACCESS DECLINED by Owner. Please contact Administrator."
        }

    if plan_type == "lifetime":
        return {
            "status": "active",
            "plan_type": "lifetime",
            "days_left": 9999,
            "is_locked": False,
            "warning": None
        }

    if not expiry_str:
        return {"status": "locked", "message": "Subscription date not configured", "is_locked": True}

    expiry_date = datetime.datetime.strptime(expiry_str, "%Y-%m-%d").date()
    today = datetime.date.today()
    days_left = (expiry_date - today).days

    if days_left <= 0:
        if status != "locked":
            conn = get_db_connection()
            conn.cursor().execute("UPDATE tenants SET subscription_status = 'locked' WHERE id = ?", (tenant_id,))
            conn.commit()
            conn.close()
        return {
            "status": "locked",
            "plan_type": plan_type,
            "days_left": 0,
            "is_locked": True,
            "message": f"Subscription expired on {expiry_str}. Account locked. Contact Administrator for renewal."
        }

    warning = None
    if days_left <= 7:
        warning = f"CRITICAL: Subscription expires in {days_left} days ({expiry_str})! Please renew immediately."
    elif days_left <= 14:
        warning = f"URGENT: Subscription expires in {days_left} days ({expiry_str})."
    elif days_left <= 30:
        warning = f"Notice: Subscription expires in {days_left} days ({expiry_str})."

    return {
        "status": status,
        "plan_type": plan_type,
        "expiry_date": expiry_str,
        "days_left": days_left,
        "is_locked": (status == "locked"),
        "warning": warning
    }

def owner_lock_tenant(tenant_id: str):
    conn = get_db_connection()
    conn.cursor().execute("UPDATE tenants SET subscription_status = 'locked' WHERE id = ?", (tenant_id,))
    conn.commit()
    conn.close()
    auto_backup_state()
    return {"success": True, "message": f"Tenant locked successfully by Owner."}

def owner_unlock_tenant(tenant_id: str):
    conn = get_db_connection()
    conn.cursor().execute("UPDATE tenants SET subscription_status = 'active' WHERE id = ?", (tenant_id,))
    conn.commit()
    conn.close()
    auto_backup_state()
    return {"success": True, "message": f"Tenant unlocked successfully by Owner."}

def owner_extend_subscription(tenant_id: str, days: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT expiry_date FROM tenants WHERE id = ?", (tenant_id,))
    row = cursor.fetchone()
    if row and row["expiry_date"]:
        curr_exp = datetime.datetime.strptime(row["expiry_date"], "%Y-%m-%d").date()
        base_date = max(curr_exp, datetime.date.today())
        new_exp = base_date + datetime.timedelta(days=days)
    else:
        new_exp = datetime.date.today() + datetime.timedelta(days=days)

    cursor.execute("UPDATE tenants SET expiry_date = ?, subscription_status = 'active' WHERE id = ?", (str(new_exp), tenant_id))
    conn.commit()
    conn.close()
    auto_backup_state()
    return {"success": True, "new_expiry": str(new_exp)}

def owner_convert_to_lifetime(tenant_id: str):
    conn = get_db_connection()
    conn.cursor().execute(
        "UPDATE tenants SET plan_type = 'lifetime', subscription_status = 'active', price_paid = 50000.0 WHERE id = ?",
        (tenant_id,)
    )
    conn.commit()
    conn.close()
    auto_backup_state()
    return {"success": True, "message": "Tenant upgraded to Lifetime License (₹50,000)."}

def owner_update_tenant(tenant_id: str, name: str, email: str, phone: str, plan_type: str, status: str, expiry_date: str, price_paid: float):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Backup current state before editing
    cursor.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
    curr = cursor.fetchone()
    if curr:
        cursor.execute('''
            INSERT INTO tenant_backups (tenant_id, name, email, phone, plan_type, subscription_status, start_date, expiry_date, price_paid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (curr["id"], curr["name"], curr["email"], curr["phone"], curr["plan_type"], curr["subscription_status"], curr["start_date"], curr["expiry_date"], curr["price_paid"]))

    # 2. Apply update
    cursor.execute('''
        UPDATE tenants
        SET name = ?, email = ?, phone = ?, plan_type = ?, subscription_status = ?, expiry_date = ?, price_paid = ?
        WHERE id = ?
    ''', (name, email, phone, plan_type, status, expiry_date, price_paid, tenant_id))
    
    conn.commit()
    conn.close()
    auto_backup_state()
    return {"success": True, "message": f"Tenant '{name}' details updated successfully."}

def owner_undo_tenant_update(tenant_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get latest backup
    cursor.execute("SELECT * FROM tenant_backups WHERE tenant_id = ? ORDER BY backed_up_at DESC LIMIT 1", (tenant_id,))
    backup = cursor.fetchone()
    
    if not backup:
        conn.close()
        return {"success": False, "message": "No previous backup found to undo."}

    # Revert to backup state
    cursor.execute('''
        UPDATE tenants
        SET name = ?, email = ?, phone = ?, plan_type = ?, subscription_status = ?, start_date = ?, expiry_date = ?, price_paid = ?
        WHERE id = ?
    ''', (
        backup["name"], backup["email"], backup["phone"], backup["plan_type"],
        backup["subscription_status"], backup["start_date"], backup["expiry_date"], backup["price_paid"],
        tenant_id
    ))

    # Delete used backup
    cursor.execute("DELETE FROM tenant_backups WHERE id = ?", (backup["id"],))
    
    conn.commit()
    conn.close()
    auto_backup_state()
    return {"success": True, "message": f"Undid last edit. Restored '{backup['name']}' to previous state."}

def owner_delete_tenant(tenant_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
    cursor.execute("DELETE FROM users WHERE tenant_id = ?", (tenant_id,))
    conn.commit()
    conn.close()
    auto_backup_state()
    return {"success": True, "message": "Tenant organization and user accounts permanently deleted."}

def owner_approve_request(tenant_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
    tenant = cursor.fetchone()
    if not tenant:
        conn.close()
        return {"success": False, "message": "Access request not found."}

    days_map = {"6_months": 180, "1_year": 365, "lifetime": 36500}
    price_map = {"6_months": 12000.0, "1_year": 20000.0, "lifetime": 50000.0}

    days = days_map.get(tenant["plan_type"], 365)
    price = price_map.get(tenant["plan_type"], 20000.0)
    today = datetime.date.today()
    expiry = today + datetime.timedelta(days=days)

    cursor.execute("""
        UPDATE tenants
        SET subscription_status = 'active', start_date = ?, expiry_date = ?, price_paid = ?
        WHERE id = ?
    """, (str(today), str(expiry), price, tenant_id))
    conn.commit()
    conn.close()
    auto_backup_state()

    try:
        from security import send_account_approved_email
        send_account_approved_email(tenant["email"], tenant["name"])
    except Exception:
        pass

    return {"success": True, "message": f"Access granted for '{tenant['name']}'! Account is now active."}

def owner_decline_request(tenant_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM tenants WHERE id = ?", (tenant_id,))
    row = cursor.fetchone()
    name = row["name"] if row else "Tenant"

    cursor.execute("DELETE FROM users WHERE tenant_id = ?", (tenant_id,))
    cursor.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
    conn.commit()
    conn.close()
    auto_backup_state()
    return {"success": True, "message": f"Access request for '{name}' was declined and removed."}

def get_owner_dashboard_summary():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM tenants WHERE subscription_status != 'pending_approval'")
    total_tenants = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as active FROM tenants WHERE subscription_status = 'active'")
    active_tenants = cursor.fetchone()["active"]

    cursor.execute("SELECT COUNT(*) as locked FROM tenants WHERE subscription_status = 'locked'")
    locked_tenants = cursor.fetchone()["locked"]

    cursor.execute("SELECT COUNT(*) as pending FROM tenants WHERE subscription_status = 'pending_approval'")
    pending_count = cursor.fetchone()["pending"]

    cursor.execute("SELECT SUM(price_paid) as total_revenue FROM tenants WHERE subscription_status = 'active'")
    rev = cursor.fetchone()["total_revenue"]
    total_revenue = rev if rev else 0.0

    cursor.execute("""
        SELECT id, name, email, phone, plan_type, subscription_status, start_date, expiry_date, price_paid, created_at
        FROM tenants 
        WHERE subscription_status != 'pending_approval'
        ORDER BY created_at DESC
    """)
    all_tenants = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT t.id, t.name, t.email, t.phone, t.plan_type, t.subscription_status, t.created_at, u.username as admin_username
        FROM tenants t
        LEFT JOIN users u ON u.tenant_id = t.id
        WHERE t.subscription_status = 'pending_approval'
        ORDER BY t.created_at DESC
    """)
    pending_requests = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return {
        "total_tenants": total_tenants,
        "active_tenants": active_tenants,
        "locked_tenants": locked_tenants,
        "pending_count": pending_count,
        "total_revenue": total_revenue,
        "pricing_tiers": PRICING_TIERS,
        "tenants": all_tenants,
        "pending_requests": pending_requests
    }
