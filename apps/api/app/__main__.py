"""Development launcher: never emit raw URLs, query strings or headers to logs."""
import uvicorn
from pathlib import Path
from dotenv import load_dotenv


if __name__ == "__main__":
    load_dotenv(Path(__file__).parents[1] / ".env", override=False)
    from app.cleanup_idempotency import run
    try:
        run()
    except Exception:
        raise SystemExit('Startup cleanup failed; check migrations/database privately')
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, access_log=False)
