"""Start the restaurant app: python run.py  ->  http://localhost:5000"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Restaurant app running: open http://localhost:{port}  (staff login: admin / admin)\n")
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
