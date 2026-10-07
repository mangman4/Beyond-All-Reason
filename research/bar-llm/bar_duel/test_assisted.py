import copy
import json
import unittest
from unittest.mock import patch
import assisted
import run

class AssistedTests(unittest.TestCase):
    def test_air_counts_and_threats_survive_compaction(self):
        self.obs.update(force={'ground':4,'air':3,'fighters':1,'bombers':1,'air_scouts':1},threat={'visible_air':2,'visible_ground':1})
        value=assisted.compact(self.obs)
        self.assertEqual(value['force'],self.obs['force'])
        self.assertEqual(value['threat'],self.obs['threat'])
    def setUp(self):
        self.obs={'control_mode':'assisted','frame':30,'resources':{'metal':100,'energy':500},
          'candidates':[{'id':'wait','description':'Keep orders'},{'id':'build_energy','description':'Build solar'}],
          'completed':{'armcom':1},'jobs':[{'type':'armsolar','complete_percent':20,'x':400}],
          'enemies':[{'type':'tank','id':9,'x':1},{'type':'tank','id':10,'x':2}],
          'recent_actions':[{'action':'build_energy','status':'accepted','orders':[{'x':5}]}]*5,
          'recent_collaboration':[{'large':'unused'}],'own_units':[{'id':1}],
          'role_proposals':[{'role':'economy','action_id':'build_energy','reason_code':'energy'}]}
    def test_compaction_preserves_choices_and_coordination(self):
        before=copy.deepcopy(self.obs);v=assisted.compact(self.obs)
        self.assertEqual(v['candidates'],self.obs['candidates'])
        self.assertEqual(v['role_proposals'],self.obs['role_proposals'])
        self.assertEqual(v['visible_enemies'],{'tank':2})
        self.assertEqual(len(v['recent_actions']),3)
        self.assertNotIn('own_units',v);self.assertNotIn('recent_collaboration',v)
        self.assertEqual(v['jobs'],[{'type':'armsolar','complete_percent':20}])
        self.assertEqual(self.obs,before)
    def test_both_backends_get_same_observation_and_wait_is_not_overridden(self):
        payloads=[]
        def response(p,*a,**kw):
            payloads.append(p)
            return {'message':{'content':'{"action_id":"wait","reason_code":"wait"}'}}
        with patch.object(run.network,'bounded_cloud_response',side_effect=response):
            for backend in ('local','cloud'):
                choice,_=run.decide(self.obs,'test',backend,'',12)
                self.assertEqual(choice['action_id'],'wait')
        self.assertEqual(payloads[0]['messages'][1],payloads[1]['messages'][1])
        self.assertEqual(payloads[0]['options']['num_predict'],64)
        self.assertNotIn('format',payloads[1])
        self.assertEqual(json.loads(payloads[0]['messages'][1]['content'])['candidates'],self.obs['candidates'])

if __name__=='__main__':unittest.main()
