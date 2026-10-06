"""Sequential paired trials; each pair exchanges start positions."""
import argparse
import json
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
import run
from analysis import write_reports

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pairs',type=int,default=1)
    p.add_argument('--seconds',type=int,default=600)
    p.add_argument('--headless',action='store_true')
    p.add_argument('--data',type=Path)
    p.add_argument('--local-mode',choices=('single','swarm'),default='single')
    p.add_argument('--control',choices=('macro','direct','assisted'),default='macro')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--fixture',action='store_true')
    p.add_argument('--victory-test',action='store_true')
    a=p.parse_args()
    if a.pairs<1 or a.seconds<1:p.error('pairs and seconds must be positive')
    if (a.fixture or a.victory_test) and not a.dry_run:p.error('test flags require --dry-run')
    cfg=run.env_settings()
    data=a.data or run.configured_data(cfg)
    models=[cfg.get('OLLAMA_MODEL','glm-5.3'),cfg.get('LOCAL_MODEL','openfront-local')]
    game=re.findall(r'name = "(Beyond All Reason [^"]+)"',(data/'cache/ArchiveCache22.lua').read_text(encoding='utf-8'))[-1]
    engine=sorted((data/'engine').glob('*/spring.exe'))[-1]
    dest=run.ROOT/'batches'/time.strftime('%Y%m%d-%H%M%S');dest.mkdir(parents=True)
    trials=[];completed=[]
    try:
        for n in range(a.pairs*2):
            folder=run.ROOT/'runs'/f'{dest.name}-trial-{n+1:02}'
            cmd=[sys.executable,str(run.ROOT/'run.py'),'--run-dir',str(folder),'--game',game,'--engine',str(engine),'--cloud-model',models[0],'--local-model',models[1],'--seconds',str(a.seconds),'--local-mode',a.local_mode]
            if n%2:cmd+=['--swap']
            cmd+=['--control',a.control]
            cmd+=['--data',str(data)]
            for flag in ('headless','dry_run','fixture'):
                if getattr(a,flag):cmd+=['--'+flag.replace('_','-')]
            if a.victory_test:cmd+=['--victory-test',str(n%2)]
            print(f'Trial {n+1}/{a.pairs*2}',flush=True)
            code=subprocess.call(cmd)
            trials.append({'run':str(folder),'exit_code':code})
            if (folder/'result.json').exists():
                completed.append(folder);write_reports(completed,dest)
            if code:break
    finally:
        (dest/'batch.json').write_text(json.dumps({'planned_games':a.pairs*2,'trials':trials,'game':game,'engine':str(engine),'models':models,'local_mode':a.local_mode},indent=2),encoding='utf-8')
        print('Batch records: '+str(dest),flush=True)
        if completed and not a.headless:webbrowser.open((dest/'report.html').resolve().as_uri())

if __name__=='__main__':main()
