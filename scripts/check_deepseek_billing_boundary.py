"""Offline evidence diagnostic only: no keys, account API, DB or network."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
from app.billing_boundary import assess_boundary, conditional_context_scenario, STRATEGIES
from app.deepseek_bridge import synthetic_request


def main():
    report = {'mode': 'offline_evidence_only', 'real_requests': 0, 'approved_cny': '0',
              'dispatch_allowed': False, 'verified_input_upper_bound': None,
              'verified_maximum_cost': None, 'assessments': [], 'conditional_scenarios': []}
    for strategy in STRATEGIES:
        report['assessments'].append(asdict(assess_boundary(strategy=strategy, body=synthetic_request().body)))
    for currency in ('CNY', 'USD'):
        for context in (1_000_000, 1_048_576):
            scenario = asdict(conditional_context_scenario(currency, context))
            scenario['hypothetical_native_cost'] = str(scenario['hypothetical_native_cost'])
            scenario['certified'] = False
            report['conditional_scenarios'].append(scenario)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2  # Blocked is intentional. Never return a successful preflight.


if __name__ == '__main__':
    raise SystemExit(main())
