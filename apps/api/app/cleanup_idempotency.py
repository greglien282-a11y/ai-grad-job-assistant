"""Run hourly in deployment; diagnostics contain counts/times only."""
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import func, select
from app.db import build_engine, session_factory
from app.idempotency import cleanup
from app.models import IdempotencyOperation, utcnow


def run():
    engine = build_engine()
    try:
        with session_factory(engine)() as db, db.begin():
            oldest = db.scalar(select(func.min(IdempotencyOperation.expires_at)).where(IdempotencyOperation.expires_at <= utcnow()))
            count = cleanup(db)
        print(f'Expired operation metadata removed: {count}; oldest expiration: {oldest.isoformat() if oldest else "none"}')
    finally:
        engine.dispose()


def main():
    load_dotenv(Path(__file__).parents[1] / '.env', override=False)
    try:
        run()
    except Exception:
        raise SystemExit('Operation metadata cleanup failed; monitoring required (connection details suppressed)')


if __name__ == '__main__':
    main()
