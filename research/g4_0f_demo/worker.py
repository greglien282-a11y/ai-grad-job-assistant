"""Trusted synthetic ingress OR bound signer; NO owner and NO HTTP listener."""
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'apps/api'))
from dataclasses import asdict, replace
import hmac
import json
from types import SimpleNamespace
import psycopg
from psycopg.rows import dict_row
from research.g3_choice_protocol.runtime import Refused
from research.g4_source_binding.binding import Ingress, BoundIssuer, Origin, approved_hash, origin_message
from research.g4_trusted_boundary.runtime import message
from research.g4_0e_hardening.execution_pin import ExecutionPin, inventory
from research.g4_0f_demo.services import manifest, execution_hash
from research.g4_0f_demo.audit import encode


def main():
    setup = json.loads(sys.stdin.readline())
    if setup['manifest'] != manifest() or setup['version'] != execution_hash(setup['manifest']): return
    pin = ExecutionPin(setup['manifest']['base'])
    mode = setup['mode']; source_key = bytes.fromhex(setup['source_key'])
    service = Ingress(source_key) if mode == 'ingress' else BoundIssuer(bytes.fromhex(setup['signing_key']), source_key, approved_hash())
    gate = SimpleNamespace(**setup['gate']) if mode == 'ingress' else None
    identity = SimpleNamespace(**setup['identity']) if mode == 'ingress' else None
    # JSON UUID fields are converted explicitly; no pickle/code deserialization.
    if identity:
        from uuid import UUID
        identity.sid=UUID(identity.sid); identity.pid=UUID(identity.pid)
    print(json.dumps({'ready':True}),flush=True)
    for line in sys.stdin:
        try:
            pin.verify()
            if setup['manifest'] != manifest(): raise Refused('execution_chain_unapproved')
            request = json.loads(line)
            if mode == 'ingress':
                with psycopg.connect(setup['reader_dsn'],row_factory=dict_row) as db:
                    db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    source = service.capture(db,gate,identity,request['key'],request['body'])
                    ttl=setup['source_ttl']
                    if type(ttl) is not int or not 1<=ttl<=120: raise Refused('source_policy_unapproved')
                    source=replace(source,expires=min(source.expires,int(time.time())+ttl))
                    source=replace(source,mac=hmac.digest(source_key,origin_message(source),'sha256'))
                    result=encode(source)
            else:
                value = request['source']; source = Origin(**{**value,'mac':bytes.fromhex(value['mac'])})
                graph = json.loads(request['seal']); receipt = graph.get('source_receipt')
                if not receipt or receipt['source_record'] != encode(source) or receipt['operation_id'] != graph['operation']['id'] or receipt['session_id'] != graph['operation']['session_id'] or receipt['created_xid'] != graph['operation']['created_xid']:
                    raise Refused('source_audit_mismatch')
                proof = service.issue(request['seal'],source)
                proof = replace(proof,validator_hash=setup['version'])
                proof = replace(proof,mac=hmac.digest(bytes.fromhex(setup['signing_key']),message(proof.seal,proof.nonce,proof.expires,proof.validator_hash),'sha256'))
                result = {**asdict(proof),'mac':proof.mac.hex()}
        except Refused as exc: result={'error':str(exc)}
        except Exception: result={'error':'trusted_validator_unavailable'}
        print(json.dumps(result),flush=True)


if __name__ == '__main__': main()
