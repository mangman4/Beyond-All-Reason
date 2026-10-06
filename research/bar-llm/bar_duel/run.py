"""Local BAR launcher. Swarm mode additionally uses local LangGraph."""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import network
import hashlib
import copy
import queue
import direct
import assisted
from analysis import write_reports

ROOT = Path(__file__).resolve().parent
DATA = Path.home() / 'Desktop/Beyond-All-Reason/Launcher/data'
REASONS = {'economy':'경제 확장', 'energy':'에너지 확보', 'production':'생산 기반 확보',
           'military':'병력 확보', 'pressure':'공격', 'defense':'방어·후퇴', 'scouting':'정찰', 'repair':'수리·복구','reclaim':'자원 회수','wait':'기존 명령 유지'}

def decision_view(obs,history,old=None):
    view=copy.deepcopy(obs)
    view['recent_actions']=[{k:e[k] for k in ('action','orders','status','frame','applied_frame') if k in e} for e in history[:5]]
    if any('swarm' in e for e in history[:3]):
        view['recent_collaboration']=[{'action':e.get('action'),'execution_status':e['status'],
            'selection':e['swarm']['selection'],'selected_roles':e['swarm']['selected_roles'],
            'proposals':[{'role':p['role'],**p['choice']} for p in e['swarm']['steps'] if p.get('choice') and p['role']!='coordinator']}
            for e in history[:3] if 'swarm' in e]
    if old and obs['frame']>old['frame']:
        dt=(obs['frame']-old['frame'])/30
        view['recent_changes']={'over_game_seconds':round(dt,1),
            'metal_change':obs['resources']['metal']-old['resources']['metal'],
            'energy_change':obs['resources']['energy']-old['resources']['energy'],
            'unit_count_change':sum(obs['units'].values())-sum(old['units'].values())}
    return view

def env_settings(path=None):
    result = {}
    path=Path(path) if path is not None else ROOT.parent/'settings.env'
    lines=path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
    for line in lines:
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1);result[k.strip()]=v.strip().strip('"').strip("'")
    return {**result, **os.environ}

def configured_data(cfg):
    value=cfg.get('BAR_DATA_DIR','').strip()
    return Path(value).expanduser() if value else DATA

def decide(obs, model, backend, key, timeout, cancel=None, role_instruction=None):
    ids=[c['id'] for c in obs['candidates']]
    payload={'model':model,'stream':True,'_backend':backend,'keep_alive':'30m',
      'messages':[{'role':'system','content':
        'You command one Armada team in Beyond All Reason. Win by destroying the opponent. '
        'Choose exactly one available action. Build extractors for metal, solar for energy, '
        'a vehicle factory for production, constructors for expansion, tanks for combat. '
        'Resources are spent gradually while building. Existing orders continue while you think. '
        'Enemies are currently visible; last_seen_enemies are uncertain old sightings, not current positions. '
        'Use recent_actions, jobs, income balance, health and threats. Accepted means order issued, not finished. '
        'Choose economy, production, scouting, combat, repair or reclaim according to conditions. '
        'Do not assume repeating the last action is useful. Avoid repeated unnecessary factories. '
        'Return JSON action_id and reason_code only. reason_code must be one of: '
        +', '.join(REASONS)+'. Use an exact action_id from candidates.'},
        {'role':'user','content':json.dumps(obs,separators=(',',':'))}],
      'format':{'type':'object','properties':{'action_id':{'type':'string','enum':ids},
        'reason_code':{'type':'string','enum':list(REASONS)}},'required':['action_id','reason_code'],'additionalProperties':False},
      'options':{'temperature':0,'num_predict':96 if backend=='local' else 4096,'num_ctx':8192}}
    if role_instruction:payload['messages'][0]['content']+=' '+role_instruction
    if obs.get('control_mode')=='assisted':
        payload['messages'][0]['content']=assisted.PROMPT+' '+(role_instruction or '')
        payload['messages'][1]['content']=json.dumps(assisted.compact(obs),separators=(',',':'))
        payload['options']['num_predict']=64
    if obs.get('control_mode')=='direct' and not obs.get('proposal_selection'):
        payload['messages'][0]['content']=direct.PROMPT+' Valid reason_code: '+', '.join(REASONS)+'. '+(role_instruction or '')
        payload['format']=direct.schema(ids,list(REASONS),obs)
        payload['options']['num_predict']=384
    if backend=='cloud':
        # Cloud schemas/options are not guaranteed; use the already verified OpenFront path.
        payload.pop('format');payload.pop('options');payload['think']='low'
        payload['messages'][0]['content']+=' Decide directly from this snapshot. Do not simulate future turns.'
        if obs.get('control_mode')!='direct':payload['messages'][0]['content']+=' Example: {"action_id":"wait","reason_code":"wait"}.'
    result=network.bounded_cloud_response(payload,key,timeout,cancel=cancel,
        first_output_limit=min(timeout,25),idle_limit=10)
    metrics={'input_tokens':result.get('prompt_eval_count'),'output_tokens':result.get('eval_count'),'timing':result.get('_timing')}
    def invalid(message):
        return network.InferenceError(message,metrics)
    content=result['message']['content'].strip()
    if content.startswith('```json\n') and content.endswith('```'):content=content[8:-3].strip()
    elif content.startswith('```\n') and content.endswith('```'):content=content[4:-3].strip()
    if not content: raise invalid('모델이 행동 답변을 완성하지 못했습니다 (빈 답변).')
    try:value=json.loads(content)
    except json.JSONDecodeError:raise invalid('모델 행동 JSON 형식 오류 (원문 미저장)') from None
    if not isinstance(value,dict) or value.get('action_id') not in ids or value.get('reason_code') not in REASONS:
        raise invalid('Invalid model action')
    if obs.get('control_mode')=='direct' and not obs.get('proposal_selection'):
        if value['action_id']=='wait':value.setdefault('orders',[])
        try:direct.validate(value,obs)
        except (ValueError,KeyError,TypeError) as exc:
            code=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
            raise invalid('직접 명령 검증 실패: '+code+' (원문 미저장)') from None
    return value,result

def install(data,game=None):
    cache=(data/'cache/ArchiveCache22.lua').read_text(encoding='utf-8')
    import re
    versions=re.findall(r'name = "(Beyond All Reason [^"]+)"',cache)
    if not versions: raise RuntimeError('Installed BAR game version not found')
    game=game or versions[-1]
    if game not in versions:raise RuntimeError('Pinned BAR game version is not installed')
    mod=data/'games/llm-duel.sdd'
    (mod/'luarules/gadgets').mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'duel.lua',mod/'luarules/gadgets/llm_duel.lua')
    (mod/'luarules/gadgets/include').mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'tactics.lua',mod/'luarules/gadgets/include/llm_tactics.lua')
    shutil.copy2(ROOT/'direct.lua',mod/'luarules/gadgets/include/llm_direct.lua')
    (mod/'luaui/Widgets').mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'bridge_widget.lua',mod/'luaui/Widgets/llm_duel_transport.lua')
    (mod/'modinfo.lua').write_text('return {name="BAR LLM Duel",version="0.1",modtype=1,depend={'+json.dumps(game)+'}}',encoding='utf-8')
    (mod/'luaai.lua').write_text('return {{name="LLMCloud",desc="External Cloud LLM"},{name="LLMLocal",desc="External Local LLM"}}',encoding='utf-8')
    return game

def start_script(port, swap=False):
    teams=[]
    for t in range(2):
        x=5376 if bool(t)^swap else 768
        teams.append(f'[TEAM{t}]{{TeamLeader=0;AllyTeam={t};Side=Armada;RGBColor={"0.2 0.9 0.7" if t==0 else "0.95 0.45 0.6"};StartPosX={x};StartPosZ=2048;}}')
        teams.append(f'[ALLYTEAM{t}]{{NumAllies=0;}}')
        teams.append(f'[AI{t}]{{Name={"Cloud GLM" if t==0 else "Local Qwen"};ShortName={"LLMCloud" if t==0 else "LLMLocal"};Team={t};Host=0;IsFromDemo=0;}}')
    return '[GAME]{MapName=Red Comet Remake 1.8;GameType=BAR LLM Duel 0.1;HostIP=127.0.0.1;HostPort=18452;IsHost=1;MyPlayerName=ResearchObserver;StartPosType=3;GameStartDelay=1;NumPlayers=1;NumUsers=3;\n[PLAYER0]{Name=ResearchObserver;Spectator=1;Team=0;}\n'+ '\n'.join(teams)+f'\n[MODOPTIONS]{{llm_duel=1;llm_port={port};deathmode=com;startmetal=1000;startenergy=1000;maxunits=300;}}}}'

def summarize(agents):
    return [{k:a.get(k,0) for k in ('model','decisions','model_calls','role_errors','errors','timeouts','input_tokens','output_tokens','latency_sum','accepted','rejected')} for a in agents]

def warm_local(model):
    import urllib.request
    req=urllib.request.Request('http://127.0.0.1:11434/api/generate',data=json.dumps({'model':model,'stream':False,'keep_alive':'30m','options':{'num_ctx':8192}}).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=120) as r:
        value=json.load(r)
    if not value.get('done') or value.get('error'):raise RuntimeError('Local model preload failed')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data',type=Path,help='BAR data directory; overrides BAR_DATA_DIR')
    p.add_argument('--dry-run',action='store_true',help='Scripted plumbing check, not model evaluation')
    p.add_argument('--headless',action='store_true')
    p.add_argument('--game')
    p.add_argument('--engine',type=Path)
    p.add_argument('--run-dir',type=Path)
    p.add_argument('--cloud-model')
    p.add_argument('--local-model')
    p.add_argument('--local-mode',choices=('single','swarm'),default='single')
    p.add_argument('--control',choices=('macro','direct','assisted'),default='macro')
    p.add_argument('--victory-test',type=int,choices=(0,1),help='TEST ONLY: eliminate selected team commander at frame 900')
    p.add_argument('--fixture',action='store_true',help='TEST ONLY: symmetric starting factory and army')
    p.add_argument('--probe',action='store_true',help='TEST ONLY: exercise rejected commands')
    p.add_argument('--seconds',type=int,default=1800,help='Wall clock cap; no decision-count termination')
    p.add_argument('--swap',action='store_true')
    p.add_argument('--port',type=int,default=18765)
    p.add_argument('--dashboard-port',type=int,default=8766)
    args=p.parse_args()
    if (args.fixture or args.probe or args.victory_test is not None) and not args.dry_run:p.error('fixture/probe/victory-test require --dry-run')
    if args.seconds<=0:p.error('seconds must be positive')
    for port in (args.port,args.dashboard_port,18452):
        with socket.socket() as test:
            try:test.bind(('127.0.0.1',port))
            except OSError:raise RuntimeError(f'Port {port} is occupied. Close the previous BAR comparison first.') from None
    cfg=env_settings();key=cfg.get('OLLAMA_API_KEY','')
    args.data=args.data or configured_data(cfg)
    if not args.dry_run and not key: raise RuntimeError('Enter OLLAMA_API_KEY in existing settings.env')
    models=[args.cloud_model or cfg.get('OLLAMA_MODEL','glm-5.3'),args.local_model or cfg.get('LOCAL_MODEL','openfront-local')]
    swarm=None
    if args.local_mode=='swarm':
        from swarm import SwarmController
        def fixture_infer(obs,*a,**kw):
            if obs.get('control_mode')=='direct' and not obs.get('proposal_selection'):
                choice,result=direct.fixture_choice(obs)
                if choice['action_id'] not in [c['id'] for c in obs['candidates']]:choice={'action_id':'wait','reason_code':'wait','orders':[]}
                return choice,result
            return {'action_id':obs['candidates'][-1]['id'],'reason_code':'production'},{}
        try:swarm=SwarmController(fixture_infer if args.dry_run else decide,models[1])
        except ImportError:raise RuntimeError('군집 환경이 필요합니다. start-bar-swarm.cmd 또는 bar_duel/.venv/Scripts/python.exe를 사용하세요.') from None
    if not args.dry_run:
        print('Preparing local model...',flush=True)
        warm_local(models[1])
    basegame=install(args.data,args.game)
    engine=args.engine or sorted((args.data/'engine').glob('*/spring.exe'))[-1]
    if args.headless: engine=engine.with_name('spring-headless.exe')
    previous=sorted((ROOT/'runs').glob('*/cache'))
    run=(args.run_dir or ROOT/'runs'/time.strftime('%Y%m%d-%H%M%S')).resolve();run.mkdir(parents=True)
    if previous:shutil.copytree(previous[-1],run/'cache')
    shutil.copytree(engine.parent/'base',run/'base')
    shutil.copytree(engine.parent/'fonts',run/'fonts')
    script=start_script(args.port,args.swap)
    if args.control=='direct':script=script.replace('llm_duel=1;','llm_duel=1;llm_direct=1;')
    if args.control=='assisted':script=script.replace('llm_duel=1;','llm_duel=1;llm_assisted=1;')
    if args.fixture:script=script.replace('llm_duel=1;','llm_duel=1;llm_fixture=1;')
    if args.victory_test is not None:script=script.replace('llm_duel=1;',f'llm_duel=1;llm_victorytest={args.victory_test};')
    (run/'script.txt').write_text(script,encoding='utf-8')
    (run/'engine.cfg').write_text('LuaSocketEnabled = 1\nTCPAllowListen = 127.0.0.1:'+str(args.port)+'\nTCPAllowConnect = 127.0.0.1:'+str(args.port)+'\nSpringData = '+str(args.data)+'\nFullscreen = 0\nXResolutionWindowed = 1280\nYResolutionWindowed = 720\nVSync = 1\n',encoding='utf-8')
    manifest={'game':basegame,'engine':engine.parent.name,'map':'Red Comet Remake 1.8','models':models,
              'probe_requests':(6 if args.control=='direct' else 3) if args.probe else 0,'dry_run':args.dry_run,'fixture':args.fixture,'probe':args.probe,'swap':args.swap,'max_seconds':args.seconds,'memory':False,'observation_memory_seconds':120,'swarm':bool(swarm),
              'local_mode':args.local_mode,'collaboration':{'roles':['economy','production','combat'],'execution':'sequential','arbitration':'same local LLM, one proposed action or wait','cycle_deadline_seconds':45,'role_deadline_seconds':12,'max_calls_per_cycle':4} if swarm else None,
              'action_interface':{'direct':'direct-v1','macro':'macro-v2','assisted':'assisted-v1'}[args.control],'visibility':'current LOS + own last sightings (120s TTL)','deadline_seconds':45,
              'victory_test':args.victory_test,'deathmode':'com','source_hash':hashlib.sha256(b''.join((ROOT/n).read_bytes() for n in ('run.py','network.py','duel.lua','tactics.lua','bridge_widget.lua','swarm.py','direct.py','direct.lua','assisted.py'))).hexdigest(),
              'random_seed':'engine-generated; not fixed','initial_resources':{'metal':1000,'energy':1000},'unit_cap':300}
    if swarm:
        from importlib.metadata import version
        manifest['langgraph_version']=version('langgraph')
    (run/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    state={'status':'starting','dry_run':args.dry_run,'local_mode':args.local_mode,'control':args.control,'agents':[{'model':m,'history':[],'status':'waiting','model_calls':0,'role_errors':0,
        'decisions':0,'errors':0,'timeouts':0,'input_tokens':0,'output_tokens':0,'latency_sum':0,'accepted':0,'rejected':0} for m in models]}
    lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path=='/state':
                with lock: data=json.dumps(state,ensure_ascii=False).encode()
                typ='application/json'
            elif self.path=='/':data=(ROOT/'dashboard.html').read_bytes();typ='text/html; charset=utf-8'
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',typ);self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
        def log_message(self,*a):pass
    http=ThreadingHTTPServer(('127.0.0.1',args.dashboard_port),Handler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    log=(run/'events.jsonl').open('a',encoding='utf-8')
    def event(value): log.write(json.dumps(value,ensure_ascii=False)+'\n');log.flush()
    progress=queue.Queue()
    def drain_progress():
        while True:
            try:v=progress.get_nowait()
            except queue.Empty:break
            event(v)
            with lock:
                a=state['agents'][1]
                a.setdefault('collaboration',{'steps':{}})['steps'][v['role']]=v
                if v['phase']=='done' and v.get('called'):
                    a['model_calls']+=1
                    a['role_errors']+=v['status'] in ('error','timeout')
                    a['input_tokens']+=v.get('input_tokens') or 0
                    a['output_tokens']+=v.get('output_tokens') or 0
    output=(run/'engine-output.txt').open('w',encoding='utf-8')
    try:
        proc=subprocess.Popen([str(engine),'--isolation','--isolation-dir',str(args.data),'--write-dir',str(run),'--config',str(run/'engine.cfg'),'--window',str(run/'script.txt')],cwd=run,stdout=output,stderr=subprocess.STDOUT)
    except BaseException:
        output.close();log.close();http.shutdown();http.server_close();raise
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=2)
    cancel=threading.Event()
    futures={};latest={};tracks={0:[],1:[]};next_due={0:0,1:0};sequence={0:0,1:0};failures={0:0,1:0}
    pending={};sock=None;buffer=b'';started=time.monotonic();connected=False;match_started=None;last_packet=started;last_sample=0;probed=set();probe_results=[]
    print('Dashboard: http://127.0.0.1:'+str(args.dashboard_port),flush=True)
    if not args.headless: webbrowser.open('http://127.0.0.1:'+str(args.dashboard_port))
    try:
        while proc.poll() is None and (match_started is None or time.monotonic()-match_started<args.seconds):
            drain_progress()
            now=time.monotonic()
            if now-last_packet>(300 if match_started is None else 30):
                raise RuntimeError('No game observations received. Check engine-output.txt.')
            if sock is None:
                try:sock=socket.create_connection(('127.0.0.1',args.port),timeout=.3);sock.settimeout(.02);connected=True
                except OSError:
                    if now-started>300:raise RuntimeError('BAR bridge did not start; inspect engine-output.txt')
                    time.sleep(.2);continue
            try:
                part=sock.recv(65536)
                if not part:raise RuntimeError('BAR bridge disconnected')
                last_packet=now
                buffer+=part
            except socket.timeout:pass
            while b'\n' in buffer:
                line,buffer=buffer.split(b'\n',1);v=json.loads(line)
                if v.get('gameover'):event({'sample':True,'observations':latest});state.update(status='finished',result=v);event(v);return
                if v.get('ack'):
                    if args.probe and v['request']<=(6 if args.control=='direct' else 3):
                        expected=('invalid_role' if args.control=='direct' else 'unavailable') if v['request']==3 else 'stale'
                        if v['request']>3:expected={4:'out_of_bounds',5:'unit_not_owned',6:'duplicate_unit'}[v['request']]
                        if v['status']!=expected:raise RuntimeError('Command rejection probe failed')
                        probe_results.append(v)
                    item=pending.pop((v['team'],v['request']),None)
                    if item:
                        with lock:
                            item.update(status=v['status'],applied_frame=v['frame'])
                            if 'details' in v:item['order_result']=v['details']
                            if 'orders' in item:v['orders']=item['orders']
                            state['agents'][v['team']]['accepted' if v['status'] in ('applied','accepted','wait') else 'rejected']+=1
                    event(v)
                else:
                    if match_started is None:match_started=now
                    latest[v['team']]=v
                    tracks[v['team']]=(tracks[v['team']]+[v])[-16:]
                    with lock:state['agents'][v['team']]['observation']=v;state['status']='running'
            if now-last_sample>=5 and latest:
                event({'sample':True,'observations':latest});last_sample=now
            for k,item in list(pending.items()):
                if now-item['sent_at']>10:
                    with lock:item['status']='ack_timeout';state['agents'][k[0]]['rejected']+=1
                    event({'ack_timeout':True,'team':k[0],'request':k[1]});pending.pop(k)
            for t in range(2):
                if t in futures and futures[t][0].done():
                    fut,obs,when=futures.pop(t);sequence[t]+=1
                    item={'request':sequence[t],'team':t,'frame':obs['frame'],'latency':round(now-when,3),'status':'error','sent_at':now}
                    try:
                        choice,result=fut.result()
                        item.update(action=choice['action_id'],reason=REASONS[choice['reason_code']],reason_code=choice['reason_code'],status='sent',
                            input_tokens=result.get('prompt_eval_count'),output_tokens=result.get('eval_count'),timing=result.get('_timing'))
                        if 'swarm' in result:item['swarm']=result['swarm']
                        if 'orders' in choice:item['orders']=choice['orders']
                        sock.sendall((json.dumps({'team':t,'request':sequence[t],'frame':obs['frame'],'action':choice['action_id'],'orders':choice.get('orders',[])})+'\n').encode())
                        pending[t,sequence[t]]=item;failures[t]=0
                    except Exception as exc:
                        item.update({k:v for k,v in getattr(exc,'metrics',{}).items() if k in ('input_tokens','output_tokens','timing','swarm')})
                        item['error']=str(exc).replace(key,'[REDACTED]') if key else str(exc)
                        if isinstance(exc,network.DecisionDeadline):item['status']='timeout'
                        failures[t]+=1
                    event({'observation':obs,**item})
                    with lock:
                        a=state['agents'][t];a['decisions']+=1;a['latency_sum']+=item['latency']
                        if not (t==1 and swarm):a['model_calls']+=1
                        if not (t==1 and swarm):
                            a['input_tokens']+=item.get('input_tokens') or 0;a['output_tokens']+=item.get('output_tokens') or 0
                        if item['status'] in ('error','timeout'):a['errors']+=1
                        if item['status']=='timeout':a['timeouts']+=1
                        state['agents'][t]['history'].insert(0,item);state['agents'][t]['history']=state['agents'][t]['history'][:80]
                        state['agents'][t]['status']='disabled' if failures[t]>=5 else 'waiting'
                    next_due[t]=now+min(2**failures[t],16)
                if t not in futures and t in latest and now>=next_due[t] and failures[t]<5 and latest[t]['alive']:
                    obs=decision_view(latest[t],state['agents'][t]['history'],tracks[t][0] if tracks[t] else None)
                    if args.probe and t not in probed:
                        for request,frame,action in [(1,obs['frame']-2001,'build_energy'),(2,obs['frame']+100000,'build_energy'),(3,obs['frame'],'not_a_legal_action')]:
                            sock.sendall((json.dumps({'team':t,'request':request,'frame':frame,'action':action,'orders':[]})+'\n').encode())
                        if args.control=='direct':
                            actor=obs['own_units'][0]['id']
                            probes=[(4,[{'command':'move','units':[actor],'x':-1,'z':0}]),(5,[{'command':'stop','units':[999999]}]),(6,[{'command':'stop','units':[actor,actor]}])]
                            for request,orders in probes:
                                sock.sendall((json.dumps({'team':t,'request':request,'frame':obs['frame'],'action':'direct_combat','orders':orders})+'\n').encode())
                        sequence[t]=6 if args.control=='direct' else 3;probed.add(t);next_due[t]=now+2;continue
                    if len(obs['candidates'])==1:
                        with lock:state['agents'][t]['status']='executing existing orders'
                        next_due[t]=now+1
                        continue
                    if t==1 and swarm:
                        with lock:state['agents'][t]['collaboration']={'frame':obs['frame'],'steps':{}}
                        callback=lambda step,frame=obs['frame'],request=sequence[t]+1:progress.put({'swarm_step':True,'team':1,'frame':frame,'request':request,**step})
                        f=pool.submit(swarm.decide,obs,cancel,callback)
                    elif args.dry_run:
                        def mock(o):
                            if args.control=='direct':return direct.fixture_choice(o)
                            ids=[c['id'] for c in o['candidates']];units=o['units']
                            order=['expand_metal','build_energy','build_factory','produce_constructor','produce_tank','attack','wait']
                            if units.get('armmex',0)>=2:order.remove('expand_metal')
                            if units.get('armsolar',0)>=3:order.remove('build_energy')
                            if units.get('armvp',0)>=1:order.remove('build_factory')
                            if units.get('armcv',0)>=1:order.remove('produce_constructor')
                            if o['army']>=3:
                                phase=(o['frame']//450)%3 if args.fixture else 0
                                order=[['attack','retreat','scout_center'][phase]]+order
                            if args.fixture:
                                phase=(o['frame']//150)%8
                                prefix=['reclaim_','repair_','scout_north','defend_expansion','withdraw_wounded','attack','retreat','scout_south'][phase]
                                preferred=next((x for x in ids if x.startswith(prefix)),None)
                                order=[preferred] if preferred else ['wait']
                            return {'action_id':next(x for x in order if x in ids),'reason_code':'production'},{}
                        f=pool.submit(mock,obs)
                    else:f=pool.submit(decide,obs,models[t],'cloud' if t==0 else 'local',key if t==0 else '',45,cancel)
                    futures[t]=(f,obs,now)
                    with lock:state['agents'][t]['status']='thinking'
            time.sleep(.05)
        state['status']='time_limit' if proc.poll() is None else 'engine_exit'
        event({'end':state['status'],'engine_exit':proc.poll(),'connected':connected})
        if not connected:raise RuntimeError('Engine exited before bridge connection. See '+str(run/'engine-output.txt'))
    except KeyboardInterrupt:state['status']='stopped'
    except Exception as exc:
        state.update(status='error',error=str(exc).replace(key,'[REDACTED]') if key else str(exc))
        event({'end':'error','error':state['error']});raise
    finally:
        event({'sample':True,'observations':latest})
        event({'inflight_at_end':len(futures),'teams':list(futures)})
        cancel.set()
        if sock:sock.close()
        if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        pool.shutdown(wait=True,cancel_futures=True)
        drain_progress()
        state['summary']=summarize(state['agents'])
        state['probe_results']=probe_results
        (run/'result.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        log.close();output.close();http.shutdown();http.server_close()
        write_reports([run],run)
        print('Records: '+str(run),flush=True)

if __name__=='__main__':main()
