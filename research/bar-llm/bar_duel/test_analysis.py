import json
import tempfile
import unittest
from pathlib import Path
from analysis import analyze_run,write_reports,percentile
from run import decision_view

class ExperimentTests(unittest.TestCase):
    def make_run(self,root,name,status,winners=None,swap=False,dry=False):
        p=Path(root)/name;p.mkdir()
        (p/'manifest.json').write_text(json.dumps({'models':['cloud','local'],'swap':swap,'dry_run':dry}),encoding='utf-8')
        (p/'result.json').write_text(json.dumps({'status':status,'result':{'winners':winners or []}}),encoding='utf-8')
        (p/'events.jsonl').write_text(json.dumps({'team':0,'latency':6,'status':'timeout'})+'\n'+json.dumps({'inflight_at_end':1,'teams':[1]})+'\n',encoding='utf-8')
        return p
    def test_outcome_and_unknown_usage(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as d:
            for status,winners,outcomes in [('finished',[1],['loss','win']),('finished',[],['draw','draw']),('time_limit',[],['time_limit']*2),('error',[],['error']*2)]:
                r=analyze_run(self.make_run(d,status+str(winners),status,winners))
                self.assertEqual([t['outcome'] for t in r['teams']],outcomes)
                self.assertEqual(r['teams'][0]['unknown_usage_calls'],1)
                self.assertEqual(r['teams'][1]['uncollected_calls_at_end'],1)
    def test_paired_aggregation_and_incompatible_runs(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as d:
            a=self.make_run(d,'a','finished',[0]);b=self.make_run(d,'b','time_limit',swap=True)
            r=write_reports([a,b],Path(d)/'out')
            self.assertEqual(r['aggregate'][0]['wins'],1)
            self.assertEqual(r['aggregate'][0]['time_limits'],1)
            c=self.make_run(d,'c','finished',[0],dry=True)
            with self.assertRaises(ValueError):write_reports([a,c],Path(d)/'mixed')
    def test_observation_history_isolated(self):
        old={'frame':30,'resources':{'metal':100,'energy':200},'units':{'armcom':1}}
        current={'frame':60,'resources':{'metal':80,'energy':210},'units':{'armcom':1,'armmex':1}}
        view=decision_view(current,[{'action':'build_energy','status':'accepted','error':'private'}],old)
        self.assertEqual(view['recent_changes']['metal_change'],-20)
        self.assertNotIn('error',view['recent_actions'][0])
        self.assertNotIn('recent_actions',current)
    def test_percentile(self):
        self.assertEqual(percentile(list(range(1,101)),.95),95)
        self.assertIsNone(percentile([],.95))
    def test_sampled_durations_and_milestones(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as d:
            p=self.make_run(d,'samples','time_limit')
            obs={'frame':30,'resources':{'metal':0,'energy':20},'jobs':[{'type':'tank'}],
                 'production':{'idle_factories':1,'idle_builders':0},'completed':{'armvp':1},'army':1,
                 'combat_metrics':{'lost':2,'reclaim_metal_estimate':3}}
            with (p/'events.jsonl').open('a',encoding='utf-8') as f:
                for frame in (30,90):
                    obs['frame']=frame;f.write(json.dumps({'sample':True,'observations':{'0':obs}})+'\n')
                f.write(json.dumps({'ack':True,'team':0,'request':1,'status':'accepted','action':'attack_metal_3','frame':45})+'\n')
            m=analyze_run(p)['teams'][0]
            self.assertEqual((m['metal_shortage_seconds'],m['energy_shortage_seconds'],m['factory_idle_seconds'],m['builder_idle_seconds']),(2,0,2,0))
            self.assertEqual((m['first_factory_seconds'],m['first_army_seconds'],m['first_attack_seconds']),(1,1,1.5))
            self.assertEqual((m['unit_losses'],m['reclaim_metal_estimate']),(2,3))
    def test_swarm_partial_cycle_usage_not_double_counted(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as d:
            p=self.make_run(d,'swarm','time_limit')
            manifest=json.loads((p/'manifest.json').read_text());manifest['swarm']=True
            (p/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            rows=[{'team':1,'latency':4,'status':'sent','input_tokens':20,'output_tokens':4},
                  {'swarm_step':True,'team':1,'phase':'done','role':'economy','called':True,'status':'ok','input_tokens':20,'output_tokens':4,'role_latency':2},
                  {'swarm_step':True,'team':1,'phase':'done','role':'production','called':True,'status':'ok','input_tokens':7,'output_tokens':2,'role_latency':1},
                  {'swarm_step':True,'team':1,'phase':'done','role':'combat','called':True,'status':'cancelled','role_latency':.5}]
            with (p/'events.jsonl').open('a',encoding='utf-8') as f:
                for row in rows:f.write(json.dumps(row)+'\n')
            m=analyze_run(p)['teams'][1]
            self.assertEqual((m['calls'],m['model_calls'],m['input_tokens'],m['output_tokens']),(1,3,27,6))
            self.assertEqual((m['model_call_errors'],m['model_call_cancelled'],m['unknown_usage_calls']),(0,1,1))

if __name__=='__main__':unittest.main()
