"""Bounded, parameterized unit control. Validation never rewrites strategy."""
COMMANDS=('move','fight','attack','build','produce','repair','reclaim','stop')
PROMPT='''Direct control mode. Return exactly ONE valid JSON object, no prose or markdown.
Required keys: action_id, reason_code and orders (0 to 3).
You control a BAR team and must defeat the enemy commander. Develop your economy,
produce an army and scout or fight using your observations. Consider useful tasks
for idle units. Wait is appropriate when existing tasks should continue or no useful
order is available; waiting forever with idle units cannot win.
For action_id wait use orders: []. Otherwise choose direct_economy, direct_production
or direct_combat from candidates. All orders must belong to that role.
Each order has command and units (1 to 8 OWN unit IDs). Do not repeat a unit in a plan.
move/fight: x,z coordinates in map bounds. attack: target = CURRENTLY VISIBLE enemy ID.
repair: target = owned unit ID. reclaim: target = visible_features ID (economy).
build: ONE builder, unit_type from its build_menus entry, x,z, facing 0..3.
produce: ONE factory, unit_type from its build_menus entry, count 1..3.
stop: cancel orders of selected units. Movement, combat, repair and stop are combat role.
Build role comes from catalog.role; produce is production. Costs are spent gradually.
Coordinates, actors, types and counts are YOUR decisions. Existing orders keep running.
Only listed own_units can be selected; observation coverage may be partial.
Metal deposits are public terrain, not guaranteed free build sites. Placement may fail.
Use only the listed fields for the selected command. Do not copy example coordinates.
Choose useful orders from the actual observation, or wait if existing tasks should continue.'''

def schema(ids,reasons,obs=None):
    """Constrain grammar to legal capabilities, without selecting strategy."""
    obs=obs or {};own=[u for u in obs.get('own_units',[]) if u['complete']]
    catalog={d['name']:d for d in obs.get('catalog',[])}
    def obj(props):return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
    def enum(values,kind='string'):return {'type':kind,'enum':values}
    alternatives=[]
    for action in ids:
        variants=[];role=action.removeprefix('direct_')
        for command in COMMANDS:
            actors=list(own);props={}
            if command not in ('build','produce') and role!=('economy' if command=='reclaim' else 'combat'):continue
            if command=='produce' and role!='production':continue
            if command in ('move','fight'):actors=[u for u in actors if u['mobile']]
            if command in ('attack','fight'):actors=[u for u in actors if u['attack']]
            if command in ('repair','reclaim','build'):actors=[u for u in actors if u['builder'] and not u['factory']]
            if command=='produce':actors=[u for u in actors if u['factory']]
            if not actors:continue
            if command in ('move','fight','build'):
                props.update({k:{'type':'integer','minimum':0,'maximum':obs['map'][k]-1} for k in ('x','z')})
            if command in ('attack','repair','reclaim'):
                targets=obs.get('enemies',[]) if command=='attack' else own if command=='repair' else obs.get('visible_features',[])
                if not targets:continue
                props['target']=enum([u['id'] for u in targets],'integer')
            groups=[(actors,None)]
            if command in ('build','produce'):
                groups=[]
                for u in actors:
                    names=[n for n in obs.get('build_menus',{}).get(u['type'],[]) if n in catalog and (command=='produce' or catalog[n]['role']==role)]
                    if names:groups.append(([u],names))
                props['facing' if command=='build' else 'count']={'type':'integer','minimum':0 if command=='build' else 1,'maximum':3}
            for units,names in groups:
                fields={'command':enum([command]),'units':{'type':'array','items':enum([u['id'] for u in units],'integer'),'minItems':1,'maxItems':1 if names else 8},**props}
                if names:fields['unit_type']=enum(names)
                variants.append(obj(fields))
        if action=='wait':orders={'type':'array','items':{'type':'object'},'maxItems':0}
        elif variants:orders={'type':'array','minItems':1,'maxItems':3,'items':{'anyOf':variants}}
        else:continue
        alternatives.append(obj({'action_id':enum([action]),'reason_code':enum(reasons),'orders':orders}))
    return {'anyOf':alternatives}

def validate(choice,obs):
    def require(ok,code='invalid_parameters'):
        if not ok:raise ValueError(code)
    def integer(x):return type(x) is int
    orders=choice.get('orders')
    require(isinstance(orders,list) and len(orders)<=3)
    if choice['action_id']=='wait':require(not orders);return
    role=choice['action_id'].removeprefix('direct_')
    require(role in ('economy','production','combat') and 1<=len(orders)<=3)
    own={u['id']:u for u in obs.get('own_units',[])}
    catalog={d['name']:d for d in obs.get('catalog',[])}
    enemies={u['id'] for u in obs.get('enemies',[])}
    features={u['id'] for u in obs.get('visible_features',[])}
    seen=set()
    for o in orders:
        require(isinstance(o,dict))
        command=o.get('command');units=o.get('units')
        require(command in COMMANDS and isinstance(units,list) and 1<=len(units)<=8)
        for u in units:
            require(integer(u) and u in own and u not in seen and own[u]['complete'])
            seen.add(u)
        fields={'command','units'}
        if command in ('move','fight','build'):
            fields|={'x','z'}
            require(integer(o.get('x')) and integer(o.get('z')) and 0<=o['x']<obs['map']['x'] and 0<=o['z']<obs['map']['z'])
        if command in ('attack','repair','reclaim'):
            fields.add('target');require(integer(o.get('target')))
            require(o['target'] in (enemies if command=='attack' else own if command=='repair' else features))
        if command in ('build','produce'):
            fields.add('unit_type');require(len(units)==1 and o.get('unit_type') in catalog)
            actor=own[units[0]];d=catalog[o['unit_type']]
            require(o['unit_type'] in obs['build_menus'].get(actor['type'],[]))
            if command=='produce':
                fields.add('count');require(actor['factory'] and integer(o.get('count')) and 1<=o['count']<=3)
                require(role=='production')
            else:
                fields.add('facing');require(actor['builder'] and not actor['factory'] and integer(o.get('facing')) and 0<=o['facing']<=3)
                require(d['role']==role)
        else:
            require(role==('economy' if command=='reclaim' else 'combat'))
            if command in ('move','fight'):require(all(own[u]['mobile'] for u in units))
            if command in ('attack','fight'):require(all(own[u]['attack'] for u in units))
            if command in ('repair','reclaim'):require(all(own[u]['builder'] and not own[u]['factory'] for u in units))
        require(set(o)==fields,'unexpected_or_missing_fields')

def fixture_choice(obs):
    """TEST ONLY: exercise explicit construction, production, and separate moves."""
    phase=(obs['frame']//300)%3
    if phase==0:
        for u in obs.get('own_units',[]):
            if u['complete'] and u['builder'] and not u['factory'] and 'armsolar' in obs['build_menus'].get(u['type'],[]):
                return {'action_id':'direct_economy','reason_code':'production','orders':[{'command':'build','units':[u['id']],'unit_type':'armsolar','x':u['x']+128,'z':u['z']+480,'facing':0}]},{}
    if phase==1:
        for u in obs.get('own_units',[]):
            if u['complete'] and u['factory'] and 'armstump' in obs['build_menus'].get(u['type'],[]):
                return {'action_id':'direct_production','reason_code':'production','orders':[{'command':'produce','units':[u['id']],'unit_type':'armstump','count':2}]},{}
    mobile=[u for u in obs.get('own_units',[]) if u['mobile'] and not u['builder'] and u['complete']]
    orders=[{'command':'move','units':[u['id']],'x':obs['map']['x']//2,'z':obs['map']['z']//(3 if i==0 else 2)} for i,u in enumerate(mobile[:2])]
    return {'action_id':'direct_combat' if orders else 'wait','reason_code':'scouting' if orders else 'wait','orders':orders},{}
