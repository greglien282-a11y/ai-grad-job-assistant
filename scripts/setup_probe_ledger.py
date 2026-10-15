"""Explicit future owner setup; zero funding/approvals, never daily DB."""
import json
from pathlib import Path
import sys
import argparse

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.controlled_probe import ExperimentAdmin
from controlled_live_probe import confirmation


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--owner-config',required=True)
    parser.add_argument('--runtime-role',required=True)
    args=parser.parse_args();engine=None
    try:
        value=json.loads(Path(args.owner_config).read_text(encoding='utf-8-sig'))
        if set(value)!={'database_url'}:raise ValueError()
        url=make_url(value['database_url'])
        if (url.drivername!='postgresql+psycopg' or url.host not in ('127.0.0.1','localhost')
            or (url.port or 5432)!=5432 or url.database!='pathwise_probe' or url.query):raise ValueError()
        confirmation('SETUP pathwise_probe')
        engine=create_engine(url,hide_parameters=True,echo=False)
        with engine.connect() as conn:
            if conn.scalar(text('SELECT count(*) FROM information_schema.tables WHERE table_schema=\'public\''))!=0:
                raise ValueError('requires empty dedicated database; never upgrades a populated target')
            conn.commit()
            cfg=Config(str(Path(__file__).resolve().parents[1]/'apps/api/alembic.ini'))
            cfg.attributes['connection']=conn
            command.upgrade(cfg,'head');conn.commit();command.check(cfg)
            ledger_id=conn.scalar(text('SELECT ledger_id FROM public.paid_funding WHERE id=1'))
        ExperimentAdmin(sessionmaker(engine)).provision_runtime('public',args.runtime_role)
        print(json.dumps({'ledger_id':str(ledger_id),'approved_cny':'0','real_calls':0}))
        return 0
    except BaseException:
        print('controlled_setup_stopped; no provider request; inspect dedicated DB manually before any retry')
        return 2
    finally:
        if engine is not None:engine.dispose()


if __name__=='__main__':raise SystemExit(main())
