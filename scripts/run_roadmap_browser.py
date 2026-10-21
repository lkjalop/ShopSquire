"""Run connected browser checks against a disposable prepared shop or its restore.

Use the clean environment's Python to exercise the clean dependency installation.
Both owned servers are stopped on completion. No external effects are enabled.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import socket
import signal
import subprocess
import sys
import time
import urllib.request
import uuid
from scripts.roadmap_runtime import simulation_controls, local_backend_isolation

ROOT=Path(__file__).resolve().parents[1]


def validate_specs(root: Path, specs: list[str]) -> list[str]:
    directory = (root / 'frontend' / 'e2e').resolve()
    selected = []
    for spec in specs:
        path = Path(spec)
        candidate = (directory / path).resolve() if len(path.parts) == 1 else (root / path).resolve()
        if not candidate.is_relative_to(directory) or not candidate.is_file() or not candidate.name.endswith('.spec.ts'):
            raise ValueError(f'missing_browser_spec:{spec}')
        selected.append(candidate.relative_to(root.resolve()).as_posix())
    return selected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--restore',action='store_true')
    parser.add_argument('--api-port',type=int,default=8098)
    parser.add_argument('--ui-port',type=int,default=5188)
    parser.add_argument('--label',help='Unique receipt directory name for a new run against the same database')
    parser.add_argument('--restart-stage',choices=['before','after'])
    parser.add_argument('--soak-seconds',type=int,default=0)
    parser.add_argument('--frontend-mode',choices=['development','preview'],default='development',
        help='Compare development module serving with an isolated production build')
    parser.add_argument('--live-research',action='store_true',help='Explicit read-only live research; all commerce transports remain fake')
    parser.add_argument('specs',nargs='+')
    args=parser.parse_args()
    try:
        args.specs=validate_specs(ROOT,args.specs)
    except ValueError as exc:
        parser.error(str(exc))
    for port in (args.api_port,args.ui_port):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',port))==0:
                parser.error(f'Port {port} is already in use; refusing to test another runtime')
    directory=args.directory.resolve()
    if not directory.is_relative_to(ROOT/'.artifacts'):
        parser.error('Only disposable .artifacts fixtures are supported')
    config=json.loads((directory/'runtime-private.json').read_text(encoding='utf-8'))
    if config.get('FULFILLMENT_SUPPLIER_TRANSPORT')!='sandbox':
        parser.error('Fake transport must be enforced')
    if args.live_research:
        if (config.get('APP_ENV')!='local' or config.get('EXTERNAL_RESEARCH_ENABLED')!='1'
            or config.get('SEMANTIC_RESEARCH_FIXTURES_ENABLED')!='0'):
            parser.error('Live research requires explicit local configuration and disabled research fixtures')
    elif config.get('EXTERNAL_RESEARCH_ENABLED')!='0':
        parser.error('Offline research required unless --live-research is explicit')
    database=directory/('restore.sqlite3' if args.restore else 'shop.sqlite3')
    config.update(DATABASE_URL='sqlite:///'+database.as_posix(),DATABASE_URL_RO='sqlite:///'+database.as_posix())
    # Each replay starts with new enrolled demo buyers. Existing accepted carts
    # must survive another buyer case; tests must not delete them to look green.
    run_id = uuid.uuid4().hex
    offer_buyers = {kind: f'roadmap-{kind}-buyer-{run_id}' for kind in ('bundle', 'upgrade')}
    bindings = json.loads(config.get('BUYER_TENANT_BINDINGS_JSON', '{}'))
    for subject in offer_buyers.values():
        bindings[subject] = ['synthetic-bundles']
    config['BUYER_TENANT_BINDINGS_JSON'] = json.dumps(bindings)
    label=args.label or ('restored-browser' if args.restore else 'connected-browser')
    if not label or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in label):
        parser.error('Use a plain run label')
    run=directory/label
    run.mkdir(exist_ok=False)
    with sqlite3.connect(database) as db:
        before=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
            migration=db.execute('SELECT version_num FROM alembic_version').fetchone()[0],
            products=db.execute('SELECT COUNT(*) FROM products').fetchone()[0])
    env={**os.environ,**config,'ROADMAP_TEST_JWT_KEY':config['JWT_SIGNING_KEY'],
        'ROADMAP_BUNDLE_BUYER':offer_buyers['bundle'],'ROADMAP_UPGRADE_BUYER':offer_buyers['upgrade'],
        'ROADMAP_TEST_ROOT':str(ROOT),'ROADMAP_TEST_PYTHON':sys.executable,
        'PLAYWRIGHT_BASE_URL':f'http://127.0.0.1:{args.ui_port}', 'PLAYWRIGHT_DISABLE_GPU':'1',
        'VITE_API_PROXY_TARGET':f'http://127.0.0.1:{args.api_port}',
        'VITE_CACHE_DIR':str(run/'vite-cache'),
        'VITE_API_BASE_URL':'','VITE_API_KEY':'','VITE_OWNER_API_KEY':''}
    env.update(simulation_controls())
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(('127.0.0.1',1)) == 0:
            parser.error('Local fallback port 1 must be unavailable')
    env.update(local_backend_isolation())
    if any(Path(spec).name == 'inventory-scheduler.spec.ts' for spec in args.specs):
        env.update(INVENTORY_EXPIRY_SCHEDULER_ENABLED='1', INVENTORY_EXPIRY_INTERVAL_SECONDS='5')
    if args.restart_stage:
        state=directory/'restart-state.json'
        if args.restart_stage=='before' and state.exists():parser.error('Restart state already exists')
        if args.restart_stage=='after' and not state.exists():parser.error('Run the before stage first')
        env.update(ROADMAP_RESTART_STAGE=args.restart_stage,ROADMAP_RESTART_STATE=str(state))
    node=shutil.which('node')
    owned=[]
    handles=[]
    try:
        vite=[node,str(ROOT/'frontend/node_modules/vite/bin/vite.js')]
        ui_command=[*vite,'--host','127.0.0.1','--port',str(args.ui_port),'--strictPort']
        if args.frontend_mode=='preview':
            build=run/'frontend-build'
            with (run/'build.log').open('w',encoding='utf-8') as log:
                subprocess.run([*vite,'build','--outDir',str(build)],cwd=ROOT/'frontend',env=env,
                    stdout=log,stderr=subprocess.STDOUT,check=True)
            ui_command=[*vite,'preview','--outDir',str(build),'--host','127.0.0.1',
                '--port',str(args.ui_port),'--strictPort']
        commands=[([sys.executable,'-m','uvicorn','src.app.main:app','--host','127.0.0.1','--port',str(args.api_port)],ROOT,'api.log'),
            (ui_command,ROOT/'frontend','ui.log')]
        for command,cwd,filename in commands:
            log=(run/filename).open('w',encoding='utf-8');handles.append(log)
            owned.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt'))
        for url in [f'http://127.0.0.1:{args.api_port}/readyz',env['PLAYWRIGHT_BASE_URL']]:
            deadline=time.monotonic()+90
            while True:
                try:
                    with urllib.request.urlopen(url,timeout=3) as response:
                        if response.status==200:break
                except Exception:
                    if any(process.poll() is not None for process in owned):raise RuntimeError('isolated_server_exited')
                    if time.monotonic()>=deadline:raise RuntimeError('isolated_readiness_timeout')
                    time.sleep(.5)
        with (run/'report.json').open('w',encoding='utf-8') as out,(run/'browser.log').open('w',encoding='utf-8') as err:
            command=[node,str(ROOT/'frontend/node_modules/@playwright/test/cli.js'),'test',
                '--config=frontend/playwright.config.ts',*args.specs,'--workers=1','--retries=0',
                '--reporter=json','--output='+str(run/'traces')]
            if args.soak_seconds:
                command=[sys.executable,'-m','scripts.soak_portfolio_browser','--duration-seconds',str(args.soak_seconds),
                    '--base-url',env['PLAYWRIGHT_BASE_URL'],'--api-port',str(args.api_port),'--output',str(run/'soak'),'--net-log']
                for spec in args.specs:command.extend(['--spec',Path(spec).relative_to('frontend').as_posix()])
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=out,stderr=err)
        receipt=dict(database=str(database),restored=args.restore,before=before,readiness='passed',
            browser_exit_code=result.returncode,simulation_only=True,external_research=args.live_research,
            server_pids=[p.pid for p in owned],restart_stage=args.restart_stage,soak_seconds=args.soak_seconds,
            requested_specs=args.specs,cache_backend='isolated_local_fallback',frontend_mode=args.frontend_mode)
        receipt['offer_buyer_subjects'] = offer_buyers
        (run/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print(json.dumps(receipt))
        return result.returncode
    finally:
        for process in reversed(owned):
            if process.poll() is not None:continue
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
            else:
                os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill()
        for handle in handles:handle.close()


if __name__=='__main__':raise SystemExit(main())
