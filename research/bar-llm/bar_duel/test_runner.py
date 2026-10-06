import json
import unittest
from unittest.mock import patch
import run

class ModelBoundaryTests(unittest.TestCase):
    obs={'team':1,'frame':300,'candidates':[{'id':'wait'},{'id':'expand_metal'}]}
    def decide_with(self,content,backend='local'):
        with patch.object(run.network,'bounded_cloud_response',return_value={'message':{'content':content}}) as call:
            result=run.decide(self.obs,'test-model',backend,'test-secret',45)
            return result,call.call_args.args[0]
    def test_legal_action(self):
        (choice,_),payload=self.decide_with('{"action_id":"expand_metal","reason_code":"economy"}')
        self.assertEqual(choice['action_id'],'expand_metal')
        self.assertEqual(json.loads(payload['messages'][1]['content']),self.obs)
        self.assertNotIn('test-secret',json.dumps(payload))
    def test_illegal_action_rejected(self):
        with self.assertRaises(run.network.InferenceError):self.decide_with('{"action_id":"control_enemy","reason_code":"economy"}')
    def test_invalid_reason_rejected(self):
        with self.assertRaises(run.network.InferenceError):self.decide_with('{"action_id":"wait","reason_code":"invented"}')
    def test_invalid_shape_rejected(self):
        for content in ('[]','null','42','"wait"'):
            with self.subTest(content=content),self.assertRaises(run.network.InferenceError):self.decide_with(content)
    def test_parse_errors_do_not_echo_response(self):
        for content in ('','PRIVATE_RAW_BODY_NOT_JSON'):
            with self.assertRaises(RuntimeError) as error:self.decide_with(content)
            self.assertNotIn('PRIVATE_RAW_BODY',str(error.exception))
    def test_same_observation_both_backends(self):
        body='{"action_id":"wait","reason_code":"wait"}'
        _,local=self.decide_with(body,'local');_,cloud=self.decide_with(body,'cloud')
        self.assertEqual(local['messages'][1],cloud['messages'][1])
    def test_position_swap(self):
        normal=run.start_script(18765);swapped=run.start_script(18765,True)
        self.assertIn('StartPosX=768',normal.split('[TEAM1]')[0])
        self.assertIn('StartPosX=5376',swapped.split('[TEAM1]')[0])

if __name__=='__main__':unittest.main()
