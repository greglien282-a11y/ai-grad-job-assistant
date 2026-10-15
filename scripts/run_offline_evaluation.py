"""Run with --profile 0/1/2 and an explicitly supplied TEST_DATABASE_URL.

No provider keys, HTTP model requests, daily database fallback or UI changes.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app.offline_evaluation import evaluate, isolated_database


def main():
    parser=argparse.ArgumentParser(description='Isolated MOCK evaluation; never calls real models')
    parser.add_argument('--profile',type=int,choices=[0,1,2],default=0)
    parser.add_argument('--fault',choices=['429','5xx','refusal','truncated','schema','source','timeout','crash'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with isolated_database(os.environ.get('TEST_DATABASE_URL')) as factory:
        report=evaluate(factory,args.profile,args.fault)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Isolated MOCK report complete; real requests=0; actual cost=0; real quality/latency=null')


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Offline evaluation refused/failed; details suppressed. Check test configuration and contract tests.') from None
