import copy
import json
import threading
import unittest
from swarm import SwarmController,owner
import network

class SwarmTests(unittest.TestCase):
    def test_air_production_role_can_propose_and_coordinate(self):
        obs={**self.obs,'candidates':[{'id':x} for x in ('wait','build_energy','build_air_factory','produce_fighter','build_anti_air','air_intercept')]}
        infer,calls=self.fake(dict(economy='build_energy',production='build_air_factory',combat='air_intercept',coordinator='build_air_factory'))
        choice,_=SwarmController(infer,'test').decide(obs)
        self.assertEqual(choice['action_id'],'build_air_factory')
        self.assertEqual({c['id'] for c in calls[1][1]['candidates']},{'wait','build_air_factory','produce_fighter'})
        self.assertEqual({c['id'] for c in calls[2][1]['candidates']},{'wait','build_anti_air','air_intercept'})
    obs={'frame':30,'team':1,'resources':{'metal':100,'energy':100},'candidates':[{'id':x} for x in ('wait','build_energy','build_factory','attack')]}
    def fake(self,actions,fail=()):
        calls=[]
        def infer(obs,*args,role_instruction=None):
            role='coordinator' if 'coordinate' in role_instruction else next(r for r in ('economy','production','combat') if r.upper() in role_instruction)
            calls.append((role,copy.deepcopy(obs)))
            if role in fail:raise network.InferenceError('SECRET_RAW_ERROR',{'input_tokens':2,'output_tokens':None})
            return {'action_id':actions[role],'reason_code':'production'},{'prompt_eval_count':10,'eval_count':3}
        return infer,calls
    def test_role_isolation_arbitration_and_usage(self):
        infer,calls=self.fake(dict(economy='build_energy',production='build_factory',combat='attack',coordinator='build_factory'))
        original=copy.deepcopy(self.obs);c=SwarmController(infer,'test');choice,result=c.decide(self.obs)
        self.assertEqual(choice['action_id'],'build_factory')
        self.assertEqual([r for r,_ in calls],['economy','production','combat','coordinator'])
        for role,obs in calls[:3]:
            self.assertTrue(all(x['id']=='wait' or owner(x['id'])==role for x in obs['candidates']))
            self.assertNotIn('role_proposals',obs)
        self.assertEqual(len(calls[-1][1]['role_proposals']),3)
        self.assertEqual((result['prompt_eval_count'],result['eval_count']),(40,12))
        self.assertEqual(result['swarm']['selected_roles'],['production'])
        self.assertEqual(self.obs,original)
    def test_coordinator_cannot_invent_action(self):
        infer,_=self.fake(dict(economy='build_energy',production='wait',combat='wait',coordinator='build_factory'))
        with self.assertRaises(network.InferenceError) as e:SwarmController(infer,'test').decide(self.obs)
        self.assertEqual(e.exception.metrics['swarm']['selection'],'arbitration_failed')
    def test_failed_roles_not_silently_replaced(self):
        infer,_=self.fake(dict(economy='build_energy'),fail=('production','combat'))
        _,r=SwarmController(infer,'test').decide(self.obs)
        self.assertEqual(r['swarm']['role_errors'],2)
        self.assertEqual(r['swarm']['unknown_usage_calls'],2)
        self.assertEqual(r['prompt_eval_count'],14)
        self.assertNotIn('SECRET',json.dumps(r))
    def test_all_failures_produce_no_action(self):
        infer,_=self.fake({},fail=('economy','production','combat'))
        with self.assertRaises(network.InferenceError):SwarmController(infer,'test').decide(self.obs)
    def test_skip_no_action_and_agreement(self):
        infer,calls=self.fake(dict(economy='wait',production='wait',combat='wait'))
        _,r=SwarmController(infer,'test').decide(self.obs)
        self.assertEqual(len(calls),3);self.assertEqual(r['swarm']['selection'],'agreement')
        obs={**self.obs,'candidates':[{'id':'wait'},{'id':'build_energy'}]}
        _,r=SwarmController(infer,'test').decide(obs)
        self.assertEqual(r['swarm']['model_calls'],1)
        self.assertEqual([s['status'] for s in r['swarm']['steps']],['ok','no_available_action','no_available_action'])
    def test_cancel_prevents_all_calls(self):
        infer,calls=self.fake({});cancel=threading.Event();cancel.set()
        with self.assertRaises(network.DecisionDeadline):SwarmController(infer,'test').decide(self.obs,cancel)
        self.assertEqual(calls,[])
    def test_total_budget_does_not_restart_per_role(self):
        now=[0];timeouts=[]
        def infer(obs,model,backend,key,timeout,cancel,**kw):
            timeouts.append(timeout);now[0]+=timeout
            raise network.DecisionDeadline('total_deadline',{})
        with self.assertRaises(network.DecisionDeadline):SwarmController(infer,'test',timeout=15,clock=lambda:now[0]).decide(self.obs)
        self.assertEqual(timeouts,[12,3])
    def test_cancelled_request_not_counted_as_inference_error(self):
        def infer(*a,**kw):raise network.DecisionDeadline('cancelled',{'timeout_kind':'cancelled'})
        with self.assertRaises(network.InferenceError) as e:SwarmController(infer,'test').decide(self.obs)
        trace=e.exception.metrics['swarm']
        self.assertEqual(trace['role_errors'],0)
        self.assertTrue(all(p['status']=='cancelled' for p in trace['steps']))

if __name__=='__main__':unittest.main()
