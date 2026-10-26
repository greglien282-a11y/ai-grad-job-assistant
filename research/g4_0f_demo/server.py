"""Source-bound loopback research demo. Strict COMMIT deadline remains BLOCK."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import sys
from threading import Lock, Thread
from uuid import UUID
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'apps/api'))
from psycopg import sql, Error as DatabaseError
from research.g3_choice_protocol.runtime import apply, command, Refused
from research.g3_choice_protocol.projection import project
from research.g4_trusted_boundary.runtime import admit_gate, seal, permit, read
from research.g4_disposable_demo.server import Demo, NotSaved, provision, server_for, SAMPLES
from research.g4_0e_hardening.guard import install as install_guard, verify as verify_guard
from research.g4_0e_hardening.execution_pin import ExecutionPin
from research.g4_0f_demo import audit
from research.g4_0f_demo.services import IngressService, SignerService, manifest, execution_hash

SUBMIT = 'g4-source-bound-disposable-submit-v1'
READ = 'g4-source-bound-disposable-read-v1'
BLOCKS = ['STRICT_COMMIT_DEADLINE_BLOCK','R03_NOT_PROVEN','SHARED_LEGACY_CO_DOMAIN_BLOCK','PRODUCTION_ADMISSION_BLOCK']


@contextmanager
def integrated_provision():
    with provision() as x:
        try:
            install_guard(x); audit.install(x)
            yield x
        finally:
            if hasattr(x,'audit_schema'):
                x.model.admin.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(x.audit_schema)))


class SourceBoundDemo(Demo):
    def __init__(self, x, *, source_ttl=120):
        self.x=x; self.b=x.model.seed(); self.lock=Lock(); self.command_lock=Lock(); self.cookie=secrets.token_urlsafe(32)
        self.approved=manifest(); self.pin=ExecutionPin(self.approved['base']); version=execution_hash(self.approved)
        x.model.admin.execute(sql.SQL('UPDATE {} SET validator_hash=%s').format(sql.Identifier(x.gate.schema,'policy')),(version,))
        x.gate.validator_hash=version
        source_key=secrets.token_bytes(32)
        common={'manifest':self.approved,'version':version,'source_key':source_key.hex()}
        identity={k:str(getattr(self.b,k)) for k in ('sid','pid','subject','token')}
        self.ingress=IngressService({**common,'mode':'ingress','reader_dsn':x.model.dsn('reader'),'gate':vars(x.gate),'identity':identity,'source_ttl':source_ttl})
        try: self.signer=SignerService({**common,'mode':'signer','signing_key':x.secret.hex()})
        except Exception: self.ingress.close(); raise
        # Bootstrap/provisioner remains trusted. Handles contain no signing key;
        # this does NOT claim same-OS-account malware or memory-erasure safety.

    def _save(self, key, payload):
        if type(payload) is not dict or set(payload) != {'demo_contract','synthetic','content','kind','stage','lose_response'} or payload['demo_contract'] != SUBMIT or payload['synthetic'] is not True or type(payload['lose_response']) is not bool or type(payload['content']) is not str:
            raise Refused('demo_request_invalid')
        texts=payload['content'].split('\r\n')
        if not 1<=len(texts)<=5 or any(t not in SAMPLES for t in texts): raise Refused('demo_synthetic_samples_only')
        self.pin.verify()
        if self.approved != manifest(): raise Refused('execution_chain_unapproved')
        normalized={k:v for k,v in payload.items() if k!='lose_response'}
        old=getattr(self,'request',None)
        if old:
            if old[0]!=key or old[1]!=normalized: raise Refused('demo_single_operation_or_payload_conflict')
            body=old[2]
            # Replay ORIGINAL committed result first, even if either service is
            # dead. Never mint a replacement source or selection ID.
            with self.x.model.connect() as db:
                verify_guard(db,self.x); admit_gate(db,self.x.gate); audit.admit(db,self.x,'writer')
                _,state=apply(db,self.b.sid,self.b.token,key,body)
                if state!='replayed': raise Refused('demo_receipt_unavailable')
            return self.recover(key)
        with self.x.model.connect('reader',True) as db:
            revision=db.execute('SELECT revision FROM ref_sessions WHERE id=%s',(self.b.sid,)).fetchone()['revision']
        body=command(self.b.sid,self.b.pid,texts,revision=revision,kind=payload['kind'],stage=payload['stage'])
        try:
            source=self.ingress.capture(key,body)
            with self.x.model.connect() as db:
                verify_guard(db,self.x); admit_gate(db,self.x.gate); audit.admit(db,self.x,'writer')
                result,state=apply(db,self.b.sid,self.b.token,key,body)
                if state!='staged': raise Refused('demo_receipt_unavailable')
                oid=result['operation_id']; audit.insert(db,self.x,oid,self.b.sid,source)
                proof=self.signer.issue(seal(db,self.x.gate,oid),source)
                permit(db,self.x.gate,oid,proof)
                # Only this trusted program owns the connection/COMMIT. No SQL
                # or SET CONSTRAINTS is accepted over HTTP. This is a trust
                # assumption, NOT a database hard deadline at physical COMMIT.
        except Refused as exc:
            raise NotSaved(str(exc)) from None
        self.request=(key,normalized,body)
        return self.recover(key)

    def recover(self,key):
        with self.x.model.connect('reader',True) as db:
            result=read(db,self.x.gate,self.b,key)
            projected=project(db,self.b.sid,self.b.token,key)
            source=audit.read(db,self.x,self.b,key,result['operation_id'])
        return dict(demo_contract=READ,scope='DISPOSABLE_RESEARCH_DATABASE',operation_id=result['operation_id'],result='committed_pending_review',truth_verified=False,persistence_authorized=False,facts=projected.view,source_receipt=source,blocks=BLOCKS)

    def close(self):
        self.ingress.close(); self.signer.close()


def strict_pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate_json_field')
        result[key]=value
    return result


def integrated_server(demo,port=0,assets=None):
    server=server_for(demo,port,assets or ROOT/'research/g4_disposable_demo/web/dist')
    base=server.RequestHandlerClass
    class Handler(base):
        def do_POST(self):
            if self.path!='/candidate': return self.respond(404,{'code':'demo_not_found'})
            if not self.admitted(write=True): return self.respond(403,{'code':'demo_origin_required'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=20000: raise ValueError()
                key=str(UUID(self.headers.get('X-Research-Key','')))
                body=json.loads(self.rfile.read(size).decode('utf8'),object_pairs_hook=strict_pairs)
                result=demo.save(key,body)
                if body['lose_response']: self.close_connection=True; return
                return self.respond(201,result)
            except (ValueError,TypeError,KeyError): return self.respond(422,{'code':'demo_request_invalid'})
            except NotSaved as exc: return self.respond(503 if str(exc)=='trusted_validator_unavailable' else 409,{'code':'demo_not_saved'})
            except Refused: return self.respond(409,{'code':'demo_result_unknown'})
            except DatabaseError: return self.respond(503,{'code':'demo_database_unavailable'})
    server.RequestHandlerClass=Handler
    return server


def main():
    p=argparse.ArgumentParser(description='Source-bound disposable research; formal admission BLOCK')
    p.add_argument('--synthetic-disposable',action='store_true',required=True); p.add_argument('--port',type=int,default=18175)
    args=p.parse_args()
    with integrated_provision() as x:
        demo=SourceBoundDemo(x); server=integrated_server(demo,args.port)
        def control():
            for line in sys.stdin:
                if line.strip()=='STOP': server.shutdown(); return
                if line.strip()=='EVIDENCE':
                    rows=x.model.snapshot()
                    print(json.dumps({'evidence':hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest(),'facts':len(rows['ref_facts']),'permits':len(rows['g4_permits']),'source_receipts':len(rows['g4_source_receipts'])}),flush=True)
        Thread(target=control,daemon=True).start()
        print(json.dumps({'ready':f'http://127.0.0.1:{server.server_port}','scope':'SYNTHETIC_SOURCE_BOUND_RESEARCH_BLOCKED'}),flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally: server.server_close(); demo.close()


if __name__=='__main__': main()
