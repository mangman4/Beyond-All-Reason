import copy
import unittest
import direct
from swarm import SwarmController

class DirectTests(unittest.TestCase):
    def setUp(self):
        self.obs={'control_mode':'direct','map':{'x':1000,'z':1000},'own_units':[
          {'id':1,'type':'builder','complete':True,'builder':True,'factory':False,'mobile':True,'attack':True},
          {'id':2,'type':'factory','complete':True,'builder':True,'factory':True,'mobile':False,'attack':False},
          {'id':3,'type':'tank','complete':True,'builder':False,'factory':False,'mobile':True,'attack':True}],
          'enemies':[{'id':8}],'visible_features':[{'id':9}],
          'catalog':[{'name':'solar','role':'economy'},{'name':'tank','role':'combat'}],
          'build_menus':{'builder':['solar'],'factory':['tank']},
          'candidates':[{'id':x} for x in ('wait','direct_economy','direct_production','direct_combat')]}
        self.move={'action_id':'direct_combat','reason_code':'scouting','orders':[{'command':'move','units':[3],'x':450,'z':800}]}
    def test_valid_plan_and_wait(self):
        direct.validate(self.move,self.obs)
        direct.validate({'action_id':'wait','orders':[]},self.obs)
    def test_ownership_bounds_duplicates(self):
        for change in ({'units':[8]},{'units':[True]},{'x':1000},{'z':-1},{'units':[3,3]},{'x':2.5}):
            p=copy.deepcopy(self.move);p['orders'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):direct.validate(p,self.obs)
    def test_visibility_capability(self):
        for command,target,actor in [('attack',7,3),('repair',8,1),('repair',1,3),('reclaim',10,1)]:
            p={'action_id':'direct_economy' if command=='reclaim' else 'direct_combat','orders':[{'command':command,'units':[actor],'target':target}]}
            with self.subTest(command=command,target=target),self.assertRaises(ValueError):direct.validate(p,self.obs)
    def test_build_menu_and_production(self):
        p={'action_id':'direct_production','orders':[{'command':'produce','units':[2],'unit_type':'tank','count':3}]}
        direct.validate(p,self.obs)
        for change in ({'count':4},{'units':[1]},{'unit_type':'unknown'}):
            q=copy.deepcopy(p);q['orders'][0].update(change)
            with self.assertRaises(ValueError):direct.validate(q,self.obs)
        p={'action_id':'direct_economy','orders':[{'command':'build','units':[1],'unit_type':'solar','x':250,'z':250,'facing':0}]}
        direct.validate(p,self.obs)
        p['action_id']='direct_combat'
        with self.assertRaises(ValueError):direct.validate(p,self.obs)
    def test_coordinator_preserves_parameters(self):
        plans={'economy':{'action_id':'direct_economy','reason_code':'production','orders':[{'command':'build','units':[1],'unit_type':'solar','x':250,'z':250,'facing':0}]},
               'production':{'action_id':'direct_production','reason_code':'production','orders':[{'command':'produce','units':[2],'unit_type':'tank','count':2}]},'combat':self.move}
        def infer(obs,*args,role_instruction=None):
            if obs.get('proposal_selection'):return {'action_id':'proposal_combat','reason_code':'scouting'},{}
            role=next(r for r in plans if r.upper() in role_instruction)
            return copy.deepcopy(plans[role]),{}
        choice,result=SwarmController(infer,'test').decide(self.obs)
        self.assertEqual(choice,self.move)
        self.assertEqual(result['swarm']['selected_roles'],['combat'])
    def test_schema_limits_roles_actors_and_targets(self):
        schemas=direct.schema(['wait','direct_economy','direct_production','direct_combat'],['wait'],self.obs)['anyOf']
        economy=next(s for s in schemas if s['properties']['action_id']['enum']==['direct_economy'])
        options=economy['properties']['orders']['items']['anyOf']
        self.assertEqual({s['properties']['command']['enum'][0] for s in options},{'build','reclaim'})
        for s in options:self.assertEqual(s['properties']['units']['items']['enum'],[1])
        production=next(s for s in schemas if s['properties']['action_id']['enum']==['direct_production'])
        option=production['properties']['orders']['items']['anyOf'][0]['properties']
        self.assertEqual(option['unit_type']['enum'],['tank'])
        self.assertEqual(option['units']['items']['enum'],[2])

if __name__=='__main__':unittest.main()
