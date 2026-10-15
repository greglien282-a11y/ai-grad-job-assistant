"""Local operator CLI. No startup execution, env key or balance endpoint."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.controlled_probe import ExperimentAdmin, ExperimentControl, ExperimentPolicy
from app.controlled_probe_io import orchestrate
from app.deepseek_bridge import synthetic_request
from app.deepseek_contract import ProbeError
from app.probe_estimate import estimate
from app.probe_preview import operator_preview_store


def confirmation(phrase):
    if os.name!='nt' or not sys.stdin.isatty():raise ProbeError('controlled_interactive_windows_required')
    if input('仅在已批准后输入 '+phrase+': ').strip()!=phrase:
        raise ProbeError('controlled_confirmation_cancelled')


def main():
    parser=argparse.ArgumentParser(description='单次风险明确的合成探针；prepare/report不访问供应商')
    parser.add_argument('command',choices=['prepare','execute','report','authorize','revoke','reconcile','close-unsent'])
    parser.add_argument('--config',required=True,help='受保护本机JSON；固定DB/ledger，不含供应商Key')
    parser.add_argument('--tokenizer-archive')
    parser.add_argument('--approval-json')
    parser.add_argument('--actual-cny')
    parser.add_argument('--invoice-sha')
    parser.add_argument('--review-sha')
    args=parser.parse_args()
    engine=None
    try:
        config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        if set(config)!={'database_url','ledger_id'}:raise ProbeError('controlled_config_invalid')
        url=make_url(config['database_url'])
        if url.drivername!='postgresql+psycopg' or url.host not in ('localhost','127.0.0.1') or (url.port or 5432)!=5432 or url.database!='pathwise_probe' or url.query:
            raise ProbeError('controlled_live_database_required')
        engine=create_engine(url,hide_parameters=True,echo=False)
        control=ExperimentControl(engine,'public',config['ledger_id'])
        if args.command in ('authorize','revoke','reconcile','close-unsent'):
            admin=ExperimentAdmin(sessionmaker(engine,expire_on_commit=False))
            if args.command=='authorize':
                policy=ExperimentPolicy.model_validate_json(Path(args.approval_json).read_text(encoding='utf-8-sig'))
                if policy.execution!='controlled_live_probe' or str(policy.ledger_id)!=control.ledger_id:
                    raise ProbeError('controlled_mode_mismatch')
                if estimate(args.tokenizer_archive,synthetic_request().body)!=policy.estimated_input_tokens:
                    raise ProbeError('controlled_estimate_changed')
                print('该审批会记录剩余费用风险，不是硬上界证书；内部计划CNY '+str(policy.planned_cny))
                confirmation('AUTHORIZE '+policy.sha()[:12])
                print(json.dumps({'grant_id':str(admin.authorize(policy)),'network_requests':0}))
            elif args.command=='revoke':
                confirmation('REVOKE '+control.ledger_id)
                admin.revoke(args.review_sha);print('revoked; no network request')
            elif args.command=='reconcile':
                confirmation('RECONCILE '+control.ledger_id+' CNY '+str(args.actual_cny))
                admin.reconcile(args.actual_cny,args.invoice_sha,args.review_sha)
                print('manual CNY invoice recorded; no balance API; pool remains frozen')
            else:
                confirmation('CLOSE-UNSENT '+control.ledger_id)
                admin.close_unsent(args.review_sha);print('provably unsent experiment closed; no new send slot')
            return 0
        control.check_role(live=True)
        if args.command=='report':result=control.report(preview_store=operator_preview_store())
        else:
            policy=control.policy('controlled_live_probe')
            count=estimate(args.tokenizer_archive,synthetic_request().body)
            if count!=policy.estimated_input_tokens:raise ProbeError('controlled_estimate_changed')
            if args.command=='prepare':
                row=control.read()
                if row['state']!='approved' or row['frozen'] or row['ceiling']-row['held']-row['spent']<policy.planned_cny:
                    raise ProbeError('controlled_not_ready')
                result={'ready_for_manual_confirmation':True,'network_requests':0,'secret_resolved':False,
                    'account_ref':policy.account_ref,'currency':policy.currency,'policy_sha':policy.sha(),
                    'provider':policy.provider,'endpoint':policy.endpoint,'model':policy.model,'expected_version':policy.expected_version,
                    'region':policy.region,'api_mode':policy.api_mode,'output_cap':policy.output_cap,
                    'secret_ref':policy.secret_ref,'secret_revision':policy.secret_revision,
                    'request_sha':policy.request_sha,'tokenizer_estimate':count,'verified_token_bound':None,
                    'estimated_peak_miss_cny':str(policy.estimate_cny()),'internal_plan_cny':str(policy.planned_cny),
                    'guaranteed_loss_cap':False,'risk_acceptance':policy.risk_acceptance,'remaining_calls':1}
            else:result=asyncio.run(orchestrate(control,execution='controlled_live_probe'))
        if result.get('validated_preview') is not None:
            result['preview_notice']='仅固定合成案例的模型候选，未经用户确认，未写入经历库。'
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if args.command!='execute' or result['state']=='response_received' else 2
    except BaseException as error:
        # Never print exception text/tracebacks, DB URLs, Key or raw HTTP data.
        code='controlled_operator_error'
        if isinstance(error,ProbeError) and str(error).startswith('controlled_') and len(str(error))<100:
            code=str(error)
        print(json.dumps({'safe_code':code,'automatic_retry':False,'instruction':'停止；仅report读取，不重新执行或换键。'},ensure_ascii=False))
        return 2
    finally:
        if engine is not None:engine.dispose()


if __name__=='__main__':raise SystemExit(main())
