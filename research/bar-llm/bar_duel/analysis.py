"""Reproducible summaries from append-only events; never count time limits as draws."""
import csv
import html
import json
import math
from pathlib import Path

def percentile(values,p):
    if not values:return None
    values=sorted(values);return values[max(0,math.ceil(len(values)*p)-1)]

def analyze_run(path):
    path=Path(path);manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    state=json.loads((path/'result.json').read_text(encoding='utf-8'))
    events=[json.loads(line) for line in (path/'events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    raw=state.get('result',{}).get('winners',[])
    winners=raw if isinstance(raw,list) else []
    result={'run':path.name,'path':str(path.resolve()),'status':state['status'],'winners':winners,
            'swap':manifest['swap'],'test_only':manifest.get('dry_run',False),'conditions':manifest,'teams':[]}
    for t,model in enumerate(manifest['models']):
        calls=[e for e in events if e.get('team')==t and 'latency'in e]
        is_swarm=t==1 and manifest.get('swarm',False)
        model_calls=[e for e in events if e.get('swarm_step') and e.get('phase')=='done' and e.get('called')] if is_swarm else calls
        ack=[e for e in events if e.get('ack') and e.get('team')==t and not (manifest.get('probe') and e['request']<=manifest.get('probe_requests',3))]
        samples=[e['observations'][str(t)] for e in events if e.get('sample') and str(t) in e['observations']]
        lat=[e['latency'] for e in calls]
        outcome=('win' if t in winners else 'loss') if state['status']=='finished' and winners else 'draw' if state['status']=='finished' else state['status']
        metrics={'team':t,'model':model,'outcome':outcome,'calls':len(calls),'errors':sum(e.get('status') in ('error','timeout') for e in calls),
                 'timeouts':sum(e.get('status')=='timeout' for e in calls),'mean_latency':sum(lat)/len(lat) if lat else None,'p95_latency':percentile(lat,.95),
                 'input_tokens':sum(e.get('input_tokens') or 0 for e in calls),'output_tokens':sum(e.get('output_tokens') or 0 for e in calls),
                 'uncollected_calls_at_end':sum(t in e.get('teams',[]) for e in events if 'inflight_at_end' in e),
                 'unknown_usage_calls':sum(e.get('input_tokens') is None or e.get('output_tokens') is None for e in calls),
                 'accepted':sum(e['status'] in ('accepted','applied','wait') for e in ack),
                 'rejected':sum(e['status'] not in ('accepted','applied','wait') for e in ack)+sum(e.get('ack_timeout',False) and e.get('team')==t for e in events),
                 'partial_plans':sum(e['status']=='partial' for e in ack),
                 'unit_orders_accepted':sum((e.get('details') or {}).get('accepted',0) for e in ack),
                 'first_factory_seconds':None,'first_army_seconds':None,'first_attack_seconds':None,
                 'metal_shortage_seconds':0,'energy_shortage_seconds':0,'factory_idle_seconds':0,'builder_idle_seconds':0,'unit_losses':0,'reclaim_metal_estimate':0}
        for s in samples:
            complete=s.get('completed',{})
            if metrics['first_factory_seconds'] is None and (s.get('production',{}).get('factories',0)>0 or complete.get('armvp',0)>0):metrics['first_factory_seconds']=s['frame']/30
            if metrics['first_army_seconds'] is None and s.get('army',0)>0:metrics['first_army_seconds']=s['frame']/30
            cm=s.get('combat_metrics',{})
            metrics['unit_losses']=max(metrics['unit_losses'],cm.get('lost',0))
            metrics['reclaim_metal_estimate']=max(metrics['reclaim_metal_estimate'],cm.get('reclaim_metal_estimate',0))
        for a,b in zip(samples,samples[1:]):
            dt=max(0,(b['frame']-a['frame'])/30)
            for r in ('metal','energy'):
                if a['resources'].get(r,0)<1 and (a.get('jobs') or a['resources'].get(r+'_spend',0)>0):metrics[r+'_shortage_seconds']+=dt
            prod=a.get('production',{})
            if prod.get('idle_factories',0)>0:metrics['factory_idle_seconds']+=dt
            if prod.get('idle_builders',0)>0:metrics['builder_idle_seconds']+=dt
        attacks=[e['frame']/30 for e in ack if e['status'] in ('accepted','applied') and (e.get('action','').startswith('attack') or any(o.get('command') in ('attack','fight') for o in e.get('orders',[])))]
        if attacks:metrics['first_attack_seconds']=min(attacks)
        metrics['failure_rate']=metrics['errors']/len(calls) if calls else None
        metrics['mode']='swarm' if is_swarm else 'single'
        metrics['model_calls']=len(model_calls)
        metrics['model_call_errors']=sum(e.get('status') in ('error','timeout') for e in model_calls)
        metrics['model_call_cancelled']=sum(e.get('status')=='cancelled' for e in model_calls)
        completed_calls=len(model_calls)-metrics['model_call_cancelled']
        metrics['model_call_failure_rate']=metrics['model_call_errors']/completed_calls if completed_calls else None
        metrics['arbitration_calls']=sum(e.get('role')=='coordinator' for e in model_calls)
        for role in ('economy','production','combat'):metrics[role+'_calls']=sum(e.get('role')==role for e in model_calls)
        call_latencies=[e.get('role_latency',e.get('latency',0)) for e in model_calls]
        metrics['mean_model_call_latency']=sum(call_latencies)/len(call_latencies) if call_latencies else None
        metrics['p95_model_call_latency']=percentile(call_latencies,.95)
        metrics['degraded_cycles']=sum(e.get('swarm',{}).get('role_errors',0)>0 for e in calls)
        metrics['unknown_usage_calls']=sum(e.get('input_tokens') is None or e.get('output_tokens') is None for e in model_calls)
        for name in ('input_tokens','output_tokens'):metrics[name]=sum(e.get(name) or 0 for e in model_calls)
        metrics['rejection_rate']=metrics['rejected']/(metrics['accepted']+metrics['rejected']) if metrics['accepted']+metrics['rejected'] else None
        result['teams'].append(metrics)
    return result

def write_reports(runs,destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    reports=[analyze_run(p) for p in runs]
    signatures={json.dumps({k:v for k,v in r['conditions'].items() if k not in ('swap','victory_test')},sort_keys=True) for r in reports}
    if len(signatures)>1:raise ValueError('Cannot aggregate runs with different experiment conditions')
    rows=[{'run':r['run'],'test_only':r['test_only'],'swap':r['swap'],**t} for r in reports for t in r['teams']]
    aggregate=[]
    for team in (0,1):
        ts=[r['teams'][team] for r in reports]
        aggregate.append({'team':team,'games':len(ts),**{name:sum(t['outcome']==status for t in ts) for name,status in [('wins','win'),('losses','loss'),('draws','draw'),('time_limits','time_limit')]},
          'abnormal':sum(t['outcome'] not in ('win','loss','draw','time_limit') for t in ts)})
    output={'runs':reports,'aggregate':aggregate,'note':'Samples every 5 wall seconds; duration metrics approximate game seconds. Reclaim is estimated from build-step requests. Unknown token usage excluded. Test-only runs are not LLM evidence.'}
    (destination/'report.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    if rows:
        with (destination/'report.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    headings={'model':'모델','mode':'구성','outcome':'결과','calls':'판단 주기','model_calls':'실제 호출','model_call_errors':'호출 오류','mean_latency':'평균 주기 초','p95_latency':'95% 지연 초','input_tokens':'입력 토큰','output_tokens':'출력 토큰','rejected':'명령 거부'}
    def cell(v):
        if isinstance(v,str):v={'single':'단일','swarm':'역할 군집','win':'승','loss':'패','draw':'무승부','time_limit':'시간 제한','error':'오류','stopped':'사용자 중지','engine_exit':'엔진 종료'}.get(v,v)
        return html.escape(str(round(v,3) if isinstance(v,float) else '—' if v is None else v))
    tables=[]
    for r in reports:
        table='<table><tr>'+''.join('<th>'+v+'</th>' for v in headings.values())+'</tr>'
        for t in r['teams']:table+='<tr>'+''.join('<td>'+cell(t.get(k))+'</td>' for k in headings)+'</tr>'
        tables.append('<h2>'+html.escape(r['run'])+(' · 시험용 행동' if r['test_only'] else ' · 실제 LLM')+(' · 좌우 교환' if r['swap'] else '')+'</h2>'+table+'</table>')
    page='<!doctype html><meta charset="utf-8"><title>BAR 비교 결과</title><style>body{background:#101820;color:#e7edf4;font:16px system-ui;margin:32px}table{border-collapse:collapse}td,th{padding:10px;border:1px solid #415369}h2{margin-top:32px}</style><h1>BAR 반복 실험 결과</h1><p>시간 제한은 무승부와 별도로 집계합니다. 오류 종료도 승패에 포함하지 않습니다.</p><p>자세한 지표는 report.csv에 저장됩니다. 자원 부족·유휴 시간은 표본 기반 추정치입니다. 잔해 회수 금속은 회수 작업 요청 기반 추정치입니다.</p>'
    for a in aggregate:page+=f'<p>{"Cloud" if a["team"]==0 else "Local"}: 승 {a["wins"]} / 패 {a["losses"]} / 무승부 {a["draws"]} / 시간 제한 {a["time_limits"]} / 비정상 {a["abnormal"]}</p>'
    (destination/'report.html').write_text(page+''.join(tables),encoding='utf-8')
    return output

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('runs',nargs='+',type=Path);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();write_reports(a.runs,a.out)
