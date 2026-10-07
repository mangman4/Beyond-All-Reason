-- Shared tactical interface. No strategy fallback and no unseen enemy queries.
local M={}
local seen={[0]={},[1]={}}
local metrics={[0]={lost=0,reclaim_metal_estimate=0},[1]={lost=0,reclaim_metal_estimate=0}}
local function distance(x,z,a,b) return (x-a)^2+(z-b)^2 end
local function rounded(x) return math.floor((x or 0)*10+.5)/10 end
local function position(u) local x,y,z=Spring.GetUnitPosition(u);return x,y,z end
function M.enrich(obs,orders)
  local team,f=obs.team,obs.frame
  local ally=select(6,Spring.GetTeamInfo(team,false))
  local bx,by,bz=Spring.GetTeamStartPosition(team)
  local army,builders,damaged,mexes={},{},{},{}
  local aircraft,fighters,bombers,scouts={},{},{},{}
  obs.jobs={};obs.force={count=0,ground=0,air=0,fighters=0,bombers=0,air_scouts=0,health_percent=100,idle=0,tasks={}}
  obs.production={factories=0,idle_factories=0,builders=0,idle_builders=0}
  local hp,maxhp=0,0
  for _,u in ipairs(Spring.GetTeamUnits(team)) do
    local d=UnitDefs[Spring.GetUnitDefID(u)]
    local h,m,_,_,progress=Spring.GetUnitHealth(u)
    local x,y,z=position(u)
    local command=Spring.GetUnitCurrentCommand(u)
    local queue=d.isFactory and (Spring.GetFactoryCommands(u,0) or 0) or (Spring.GetUnitCommandCount(u) or 0)
    if progress<1 and #obs.jobs<10 then obs.jobs[#obs.jobs+1]={type=d.name,complete_percent=math.floor(progress*100),x=math.floor(x),z=math.floor(z)} end
    if d.isFactory and progress>=1 then
      obs.production.factories=obs.production.factories+1
      if queue==0 then obs.production.idle_factories=obs.production.idle_factories+1 end
      local cmds=Spring.GetFactoryCommands(u,3) or {}
      for _,c in ipairs(cmds) do if c.id<0 and #obs.jobs<10 then obs.jobs[#obs.jobs+1]={type=UnitDefs[-c.id].name,factory=d.name,queued=true} end end
    elseif d.isBuilder and progress>=1 then
      obs.production.builders=obs.production.builders+1
      if queue==0 then builders[#builders+1]=u;obs.production.idle_builders=obs.production.idle_builders+1 end
    elseif not d.isBuilding and (d.canAttack or d.name=='armpeep') and progress>=1 then
      if d.canFly then
        aircraft[#aircraft+1]=u
        if d.name=='armfig' then fighters[#fighters+1]=u
        elseif d.name=='armthund' then bombers[#bombers+1]=u
        elseif d.name=='armpeep' then scouts[#scouts+1]=u end
      else army[#army+1]=u end
      hp=hp+h;maxhp=maxhp+m
      local task=command==CMD.FIGHT and 'fight' or command==CMD.MOVE and 'move' or command==CMD.ATTACK and 'attack' or 'other'
      if queue==0 then task='idle';obs.force.idle=obs.force.idle+1 end
      obs.force.tasks[task]=(obs.force.tasks[task] or 0)+1
    end
    if h<m*.8 and progress>=1 then damaged[#damaged+1]={id=u,x=x,y=y,z=z,h=h/m} end
    if d.extractsMetal>0 then mexes[#mexes+1]={x=x,y=y,z=z} end
  end
  table.sort(army);table.sort(builders);table.sort(damaged,function(a,b)return a.h<b.h end)
  for _,group in ipairs({aircraft,fighters,bombers,scouts}) do table.sort(group) end
  obs.force.ground=#army;obs.force.air=#aircraft
  obs.force.fighters=#fighters;obs.force.bombers=#bombers;obs.force.air_scouts=#scouts
  obs.force.count=#army+#aircraft;obs.army=obs.force.count
  if maxhp>0 then obs.force.health_percent=math.floor(hp/maxhp*100) end
  obs.resources.metal_net=rounded((obs.resources.metal_income or 0)-(obs.resources.metal_spend or 0))
  obs.resources.energy_net=rounded((obs.resources.energy_income or 0)-(obs.resources.energy_spend or 0))
  for _,r in ipairs({'metal','energy'}) do
    local net=obs.resources[r..'_net']
    if net<0 then obs.resources[r..'_depletes_in_seconds']=rounded(obs.resources[r]/-net) end
  end
  local current={};obs.threat={base_visible_enemies=0,expansion_visible_enemies=0,visible_air=0,visible_ground=0}
  for _,e in ipairs(obs.enemies) do
    local def=UnitDefNames[e.type]
    local key=def and def.canFly and 'visible_air' or 'visible_ground'
    obs.threat[key]=obs.threat[key]+1
    if e.id then current[e.id]=true;seen[team][e.id]={id=e.id,type=e.type,x=e.x,z=e.z,last_seen_frame=f} end
    if distance(e.x,e.z,bx,bz)<1000^2 then obs.threat.base_visible_enemies=obs.threat.base_visible_enemies+1 end
    for _,m in ipairs(mexes) do if distance(e.x,e.z,m.x,m.z)<700^2 then obs.threat.expansion_visible_enemies=obs.threat.expansion_visible_enemies+1;break end end
  end
  obs.last_seen_enemies={}
  for id,e in pairs(seen[team]) do
    if f-e.last_seen_frame>3600 or (not current[id] and Spring.IsPosInLos(e.x,Spring.GetGroundHeight(e.x,e.z),e.z,ally)) then seen[team][id]=nil
    elseif not current[id] then obs.last_seen_enemies[#obs.last_seen_enemies+1]={id=id,type=e.type,x=e.x,z=e.z,age_seconds=math.floor((f-e.last_seen_frame)/30)} end
  end
  table.sort(obs.last_seen_enemies,function(a,b)if a.age_seconds==b.age_seconds then return a.x<b.x end return a.age_seconds<b.age_seconds end)
  while #obs.last_seen_enemies>8 do table.remove(obs.last_seen_enemies) end
  local function add(id,description,list,target)
    orders[id]=list;obs.candidates[#obs.candidates+1]={id=id,description=description,target=target}
  end
  local function move(id,description,x,z,command,units)
    local list={};for i=1,math.min(60,#units) do list[#list+1]={u=units[i],cmd=command,p={x,Spring.GetGroundHeight(x,z),z}} end
    if #list>0 then add(id,description,list,{x=math.floor(x),z=math.floor(z)}) end
  end
  -- Targets are ONLY selected from the current team's already-filtered observation.
  local airTarget,groundTarget
  for _,e in ipairs(obs.enemies) do
    local d=UnitDefNames[e.type]
    if d and d.canFly then airTarget=airTarget or e
    else groundTarget=groundTarget or e end
  end
  if airTarget and #fighters>0 then
    local list={}
    for i=1,math.min(60,#fighters) do list[#list+1]={u=fighters[i],cmd=CMD.ATTACK,p={airTarget.id}} end
    add('air_intercept','Fighters: intercept currently visible aircraft',list)
  end
  if groundTarget and #bombers>0 then
    local list={}
    for i=1,math.min(60,#bombers) do list[#list+1]={u=bombers[i],cmd=CMD.ATTACK,p={groundTarget.id}} end
    add('air_bomb','Bombers: attack currently visible ground target',list)
  end
  move('air_defend_base','Fighters: defend own start area',bx,bz,CMD.FIGHT,fighters)
  move('air_scout_north','Air scouts: explore northern central lane',Game.mapSizeX/2,Game.mapSizeZ*.25,CMD.MOVE,scouts)
  move('air_scout_south','Air scouts: explore southern central lane',Game.mapSizeX/2,Game.mapSizeZ*.75,CMD.MOVE,scouts)
  move('air_scout_enemy','Air scouts: explore opposite start area',Game.mapSizeX-bx,Game.mapSizeZ-bz,CMD.MOVE,scouts)
  move('air_retreat','Aircraft: return to own start area; constructors keep working',bx,bz,CMD.MOVE,aircraft)
  local targets={}
  for _,e in ipairs(obs.enemies) do
    local d=UnitDefNames[e.type]
    local category=d and d.extractsMetal>0 and 'metal' or d and d.isFactory and 'factory' or d and d.customParams.iscommander and 'commander' or 'enemy'
    if not targets[category] then targets[category]=e end
  end
  for _,category in ipairs({'metal','factory','commander','enemy'}) do
    local e=targets[category]
    if e then move('attack_'..category..'_'..e.id,'Attack currently visible '..category,e.x,e.z,CMD.FIGHT,army) end
  end
  for i,e in ipairs(obs.last_seen_enemies) do
    if i<=2 then move('investigate_'..e.id,'Check last-seen enemy area (may now be empty)',e.x,e.z,CMD.FIGHT,army) end
  end
  move('scout_north','Scout northern central lane',Game.mapSizeX/2,Game.mapSizeZ*.25,CMD.MOVE,army)
  move('scout_south','Scout southern central lane',Game.mapSizeX/2,Game.mapSizeZ*.75,CMD.MOVE,army)
  move('defend_base','Defend own commander start area',bx,bz,CMD.FIGHT,army)
  table.sort(mexes,function(a,b)return distance(a.x,a.z,bx,bz)>distance(b.x,b.z,bx,bz) end)
  if mexes[1] then move('defend_expansion','Defend outermost owned extractor',mexes[1].x,mexes[1].z,CMD.FIGHT,army) end
  local wounded={};for _,u in ipairs(army) do local h,m=Spring.GetUnitHealth(u);if h/m<.6 then wounded[#wounded+1]=u end end
  move('withdraw_wounded','Withdraw units below 60% health',bx,bz,CMD.MOVE,wounded)
  for _,d in ipairs(damaged) do
    local builder
    for _,u in ipairs(builders) do if u~=d.id then builder=u;break end end
    if builder then add('repair_'..d.id,'Repair most damaged owned unit',{{u=builder,cmd=CMD.REPAIR,p={d.id}}},{x=math.floor(d.x),z=math.floor(d.z)});break end
  end
  if builders[1] then
    local x,_,z=position(builders[1]);local best,bestDist
    for _,feature in ipairs(Spring.GetAllFeatures()) do
      local fx,fy,fz=Spring.GetFeaturePosition(feature)
      if Spring.IsPosInLos(fx,fy,fz,ally) then
        local metal=Spring.GetFeatureResources(feature)
        local safe=true
        for _,e in ipairs(obs.enemies) do if distance(e.x,e.z,fx,fz)<700^2 then safe=false;break end end
        local dd=distance(x,z,fx,fz)
        if safe and metal and metal>1 and dd<1500^2 and (not bestDist or dd<bestDist) then best={id=feature,x=fx,z=fz,metal=metal};bestDist=dd end
      end
    end
    if best then
      local featureTarget=best.id+((Engine.FeatureSupport and Engine.FeatureSupport.noOffsetForFeatureID) and 0 or Game.maxUnits)
      add('reclaim_'..best.id,'Reclaim visible metal-bearing feature; no visible enemy nearby',{{u=builders[1],cmd=CMD.RECLAIM,p={featureTarget}}},{x=math.floor(best.x),z=math.floor(best.z),metal=rounded(best.metal)})
    end
  end
  obs.combat_metrics=metrics[team]
end
function M.lost(team) if metrics[team] then metrics[team].lost=metrics[team].lost+1 end end
function M.reclaim(team,feature,part)
  if metrics[team] and part<0 then
    local remaining,maxMetal=Spring.GetFeatureResources(feature)
    if remaining and maxMetal then metrics[team].reclaim_metal_estimate=rounded(metrics[team].reclaim_metal_estimate+math.min(remaining,maxMetal*-part)) end
  end
end
return M
