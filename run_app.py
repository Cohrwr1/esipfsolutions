import os
import sys
import uvicorn

# Ensure current root directory and backend directory are in python path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

backend_dir = os.path.join(root_dir, "backend")
if os.path.exists(backend_dir) and backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

if __name__ == "__main__":
    print("==================================================================")
    print("      ESIPFSOLUTIONS CLOUD ENTERPRISE PLATFORM - ONLINE SERVER   ")
    print("==================================================================")
    
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
