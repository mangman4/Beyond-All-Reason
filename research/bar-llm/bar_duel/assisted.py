"""Compact observations for the shared, engine-validated macro action interface.

This is explicit assistance, not direct unit control or an inference fallback.
The model still selects every strategic action, including wait.
"""
import copy

PROMPT='''You command a BAR team. Win by destroying the enemy commander.
Choose ONE exact action_id from candidates. Return only JSON action_id and reason_code.
The engine chooses legal units and build positions for the selected action.
Build metal extractors and energy production, a factory, then an army. Adjust to
resources and threats. Use idle builders and factories for useful work. Existing
jobs continue: do not duplicate factories unnecessarily. Wait only when continuing
existing work is preferable. Candidate descriptions explain what each action does.
Reason codes: economy, energy, production, military, pressure, defense, scouting,
repair, reclaim, wait. Do not output coordinates, orders, explanations or analysis.'''

def compact(obs):
    result={k:copy.deepcopy(obs[k]) for k in ('frame','resources','completed','production','army','force','threat','candidates') if k in obs}
    result['jobs']=[{k:v for k,v in job.items() if k in ('type','complete_percent','factory','queued')} for job in obs.get('jobs',[])[:6]]
    result['visible_enemies']={}
    for e in obs.get('enemies',[]):
        name=e.get('type','unknown');result['visible_enemies'][name]=result['visible_enemies'].get(name,0)+1
    result['recent_actions']=[{k:e[k] for k in ('action','status') if k in e} for e in obs.get('recent_actions',[])[:3]]
    if 'role_proposals' in obs:result['role_proposals']=copy.deepcopy(obs['role_proposals'])
    return result
