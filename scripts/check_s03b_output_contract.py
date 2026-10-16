"""Pure offline synthetic contract matrix; no DB, credential, HTTP or download."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app.offline_output_contract import evaluate, length_analysis


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokenizer-archive', help='Optional already-local pinned public archive; never downloaded')
    parser.add_argument('--output', help='Optional synthetic offline report; exclusive create, no overwrite')
    args=parser.parse_args()
    try:
        report=evaluate()
        report['length_analysis']=length_analysis(args.tokenizer_archive) if args.tokenizer_archive else dict(
            status='TOKENIZER_NOT_PROVIDED', supplier_actual_output_tokens=None, verified_token_upper_bound=None)
        if args.output:
            with Path(args.output).open('x',encoding='utf-8') as file:
                file.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(dict(mode=report['mode'], cases=len(report['cases']),
            all_expectations_met=report['all_expectations_met'], real_provider_requests=0,
            length_status=report['length_analysis']['status']),ensure_ascii=True))
        return 0 if report['all_expectations_met'] else 2
    except Exception:
        print('{"safe_code":"offline_contract_check_failed","provider_requests":0,"automatic_retry":false}')
        return 2


if __name__=='__main__':raise SystemExit(main())
