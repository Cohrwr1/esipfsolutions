import os
import sys
import uvicorn

# Ensure backend directory is in python path
backend_dir = os.path.join(os.path.dirname(__file__), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

if __name__ == "__main__":
    print("==================================================================")
    print("      ESIPFSOLUTION CLOUD ENTERPRISE PLATFORM - ONLINE SERVER    ")
    print("==================================================================")
    print("  Local URL: http://localhost:8000")
    print("  Master PIN: 9999")
    print("  Owner Super-Admin Credentials: owner / owner123")
    print("  Tenant Admin Credentials: apex_admin / apex123")
    print("==================================================================")
    
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)

