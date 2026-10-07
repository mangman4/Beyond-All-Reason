"""Three specialist proposals and optional model arbitration, one executable order.

One local model is reused sequentially. No heuristic strategic fallback. All
specialists see the same snapshot; only their legal action subset differs.
"""
from __future__ import annotations
import copy
import os
import time
from typing import TypedDict
import network
import direct

ROLES = ('economy', 'production', 'combat')
INSTRUCTIONS = {
    'economy': 'You are the ECONOMY specialist. Propose the most useful economic action or wait. Consider metal, energy, income balance and ongoing expenditure. You do not execute orders.',
    'production': 'You are the PRODUCTION specialist. Propose factory construction or a unit to produce, or wait. Consider available resources, current production and the army composition. You do not execute orders.',
    'combat': 'You are the COMBAT specialist. Propose scouting, attack, defense, retreat, repair or wait. Consider only known enemies and your own units. You do not execute orders.',
    'coordinator': 'You coordinate the three specialists. Choose ONE proposed action or wait from candidates, using their proposals and the shared state. Balance their competing needs; do not invent another action. Your reason_code must explain your final selection.'}

def owner(action):
    if action.startswith('direct_'):return action.removeprefix('direct_')
    if action in ('expand_metal','build_energy') or action.startswith('reclaim_'):return 'economy'
    if action in ('build_factory','build_air_factory') or action.startswith('produce_'):return 'production'
    if action!='wait':return 'combat'
    return None

class GraphState(TypedDict):
    observation: dict
    proposals: list
    choice: dict
    selection: str

class SwarmController:
    def __init__(self, infer, model, timeout=45, clock=time.monotonic):
        # Keep graph execution local even if a shell has tracing enabled.
        os.environ['LANGSMITH_TRACING']='false'
        os.environ['LANGCHAIN_TRACING_V2']='false'
        from langgraph.graph import StateGraph, START, END
        self.infer,self.model,self.timeout,self.clock=infer,model,timeout,clock
        graph=StateGraph(GraphState)
        for role in ROLES:graph.add_node(role,lambda state,r=role:self.propose(state,r))
        graph.add_node('coordinator',self.coordinate)
        graph.add_edge(START,'economy');graph.add_edge('economy','production')
        graph.add_edge('production','combat');graph.add_edge('combat','coordinator');graph.add_edge('coordinator',END)
        self.graph=graph.compile()
        self.trace=[]

    def emit(self,record):
        value=copy.deepcopy(record)
        if self.progress:self.progress(value)
        if value['phase']=='done':self.trace.append(value)

    def call(self,view,role):
        remaining=self.deadline-self.clock()
        if (self.cancel is not None and self.cancel.is_set()) or remaining<=.05:
            record={'role':role,'phase':'done','called':False,'status':'cancelled' if remaining>0 else 'budget_exhausted'}
            self.emit(record);return record
        self.emit({'role':role,'phase':'running','called':False,'status':'thinking'})
        start=self.clock()
        record={'role':role,'phase':'done','called':True,'status':'error'}
        try:
            choice,result=self.infer(view,self.model,'local','',min(remaining,15 if role=='coordinator' else 12),self.cancel,role_instruction=INSTRUCTIONS[role])
            # Defense in depth also applies to injected/test inference providers.
            if choice.get('action_id') not in [c['id'] for c in view['candidates']]:
                raise network.InferenceError('Invalid role action')
            if view.get('control_mode')=='direct' and not view.get('proposal_selection'):direct.validate(choice,view)
            record.update(status='ok',choice=choice,input_tokens=result.get('prompt_eval_count'),output_tokens=result.get('eval_count'),timing=result.get('_timing'))
        except Exception as exc:
            cancelled=isinstance(exc,network.DecisionDeadline) and getattr(exc,'metrics',{}).get('timeout_kind')=='cancelled'
            record.update(status='cancelled' if cancelled else 'timeout' if isinstance(exc,network.DecisionDeadline) else 'error',error_kind=type(exc).__name__)
            record.update({k:v for k,v in getattr(exc,'metrics',{}).items() if k in ('input_tokens','output_tokens','timing')})
        record['role_latency']=round(self.clock()-start,3)
        self.emit(record);return record

    def propose(self,state,role):
        view=copy.deepcopy(state['observation'])
        view['candidates']=[c for c in view['candidates'] if c['id']=='wait' or owner(c['id'])==role]
        if len(view['candidates'])<=1:
            record={'role':role,'phase':'done','called':False,'status':'no_available_action'}
            self.emit(record)
        else:record=self.call(view,role)
        return {'proposals':state['proposals']+[record]}

    def coordinate(self,state):
        proposals=[p for p in state['proposals'] if p['status']=='ok']
        if not proposals:return {'choice':{},'selection':'no_valid_proposals'}
        ids={p['choice']['action_id'] for p in proposals}
        if len(ids)==1:
            return {'choice':proposals[0]['choice'],'selection':'agreement' if len(proposals)>1 else 'sole_valid_proposal'}
        view=copy.deepcopy(state['observation'])
        if view.get('control_mode')=='direct':
            view['proposal_selection']=True
            plans={'proposal_'+p['role']:p['choice'] for p in proposals}
            view['candidates']=[{'id':'wait','description':'Keep orders'}]+[{'id':k,'description':v} for k,v in plans.items()]
            view['role_proposals']=[{'role':p['role'],**p['choice']} for p in proposals]
            result=self.call(view,'coordinator')
            if result['status']!='ok':return {'choice':{},'selection':'arbitration_failed'}
            chosen=result['choice']
            plan=copy.deepcopy(plans.get(chosen['action_id'],{'action_id':'wait','orders':[]}))
            plan['reason_code']=chosen['reason_code']
            return {'choice':plan,'selection':'llm_arbitration'}
        view['candidates']=[c for c in view['candidates'] if c['id'] in ids or c['id']=='wait']
        view['role_proposals']=[{'role':p['role'],**p['choice']} for p in proposals]
        result=self.call(view,'coordinator')
        return {'choice':result.get('choice',{}),'selection':'llm_arbitration' if result['status']=='ok' else 'arbitration_failed'}

    def decide(self,obs,cancel=None,progress=None):
        # One controller belongs to one team's single in-flight decision.
        self.cancel,self.progress=cancel,progress
        self.trace=[];self.deadline=self.clock()+self.timeout
        state=self.graph.invoke({'observation':copy.deepcopy(obs),'proposals':[],'choice':{},'selection':''},config={'callbacks':[],'recursion_limit':10})
        if cancel is not None and cancel.is_set():state.update(choice={},selection='cancelled')
        called=[x for x in self.trace if x.get('called')]
        usage={name:sum(x.get(name) or 0 for x in called) for name in ('input_tokens','output_tokens')}
        trace={'steps':self.trace,'selection':state['selection'],'choice':state['choice'],
               'model_calls':len(called),'unknown_usage_calls':sum(x.get('input_tokens') is None or x.get('output_tokens') is None for x in called),
               'role_errors':sum(x['status'] in ('error','timeout') for x in called),
               'selected_roles':[p['role'] for p in state['proposals'] if p.get('choice',{}).get('action_id')==state['choice'].get('action_id') and p['status']=='ok']}
        metrics={**usage,'swarm':trace}
        if not state['choice']:
            exc=network.DecisionDeadline('swarm_deadline',metrics) if self.clock()>=self.deadline or (cancel is not None and cancel.is_set()) else network.InferenceError('군집에서 유효한 최종 명령을 만들지 못했습니다.',metrics)
            raise exc
        return state['choice'],{'prompt_eval_count':usage['input_tokens'],'eval_count':usage['output_tokens'],'swarm':trace}
