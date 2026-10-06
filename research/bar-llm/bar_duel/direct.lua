-- Parameterized orders: authoritative validation before any order is issued.
local M={}
local function integer(n)return type(n)=='number' and n==math.floor(n) and n<1000000000 and n>=0 end
local function role(d)
  if d.isFactory or d.isBuilder then return 'production' end
  if #(d.weapons or {})>0 or (d.radarRadius or 0)>0 then return 'combat' end
  return 'economy'
end
local function allowed(u,d)
  for _,id in ipairs(UnitDefs[Spring.GetUnitDefID(u)].buildOptions or {}) do if id==d then return true end end
  return false
end
function M.enrich(obs,spots)
  obs.control_mode='direct';obs.own_units={};obs.catalog={};obs.build_menus={};obs.visible_features={};obs.metal_deposits={}
  local all=Spring.GetTeamUnits(obs.team);table.sort(all)
  local n=#all;local offset=n>48 and math.floor(obs.frame/300)*48%n or 0
  local defs={};local roles={combat=false,economy=false,production=false}
  for i=1,math.min(n,48) do
    local u=all[(offset+i-1)%n+1];local d=UnitDefs[Spring.GetUnitDefID(u)]
    local x,_,z=Spring.GetUnitPosition(u);local h,max,_,_,p=Spring.GetUnitHealth(u)
    obs.own_units[#obs.own_units+1]={id=u,type=d.name,x=math.floor(x),z=math.floor(z),health=math.floor(h/max*100),complete=p>=1,builder=d.isBuilder,factory=d.isFactory,mobile=not d.isBuilding,attack=#(d.weapons or {})>0,command=Spring.GetUnitCurrentCommand(u) or 0}
    if p>=1 then
      roles.combat=true
      if d.isBuilder and not d.isFactory then roles.economy=true end
      if d.buildOptions and #d.buildOptions>0 then
        local menu={}
        for _,id in ipairs(d.buildOptions) do
          local b=UnitDefs[id];menu[#menu+1]=b.name
          if not defs[id] then defs[id]=true;obs.catalog[#obs.catalog+1]={name=b.name,metal=math.floor(b.metalCost),energy=math.floor(b.energyCost),role=role(b)} end
          roles[d.isFactory and 'production' or role(b)]=true
        end
        obs.build_menus[d.name]=menu
      end
    end
  end
  obs.own_units_total=n;obs.own_units_truncated=n>48
  local ally=select(6,Spring.GetTeamInfo(obs.team,false))
  for _,id in ipairs(Spring.GetAllFeatures()) do
    local x,y,z=Spring.GetFeaturePosition(id)
    if Spring.IsPosInLos(x,y,z,ally) then
      local m=Spring.GetFeatureResources(id)
      if m and m>1 then obs.visible_features[#obs.visible_features+1]={id=id,x=math.floor(x),z=math.floor(z),metal=math.floor(m)};if #obs.visible_features>=16 then break end end
    end
  end
  for _,s in ipairs(spots) do obs.metal_deposits[#obs.metal_deposits+1]={x=s.x,z=s.z} end
  obs.candidates={{id='wait',description='Keep current orders'}}
  for _,r in ipairs({'economy','production','combat'}) do if roles[r] then obs.candidates[#obs.candidates+1]={id='direct_'..r,description='Choose your own units, targets and parameters for '..r} end end
end
function M.apply(team,action,orders)
  if type(orders)~='table' or #orders>3 then return 'invalid_orders' end
  if action=='wait' then return #orders==0 and 'wait' or 'invalid_orders' end
  local selected=action:match('^direct_(%a+)$')
  if selected~='economy' and selected~='production' and selected~='combat' then return 'invalid_role' end
  if #orders<1 then return 'invalid_orders' end
  local seen,plan={},{};local ally=select(6,Spring.GetTeamInfo(team,false))
  for _,o in ipairs(orders) do
    if type(o)~='table' or type(o.units)~='table' or #o.units<1 or #o.units>8 then return 'invalid_units' end
    local cmd,params,count=nil,{},1
    local c=o.command
    if c=='move' or c=='fight' or c=='build' then
      if not integer(o.x) or not integer(o.z) or o.x>=Game.mapSizeX or o.z>=Game.mapSizeZ then return 'out_of_bounds' end
      params={o.x,Spring.GetGroundHeight(o.x,o.z),o.z}
    end
    if c=='move' then cmd=CMD.MOVE elseif c=='fight' then cmd=CMD.FIGHT elseif c=='stop' then cmd=CMD.STOP
    elseif c=='attack' or c=='repair' then
      if not integer(o.target) or not Spring.ValidUnitID(o.target) or Spring.GetUnitIsDead(o.target) then return 'invalid_target' end
      if c=='attack' then
        local los=Spring.GetUnitLosState(o.target,ally,true)
        if Spring.AreTeamsAllied(team,Spring.GetUnitTeam(o.target)) or not los or los%2~=1 then return 'target_not_visible_enemy' end
        cmd=CMD.ATTACK
      else
        if Spring.GetUnitTeam(o.target)~=team then return 'target_not_owned' end
        cmd=CMD.REPAIR
      end
      params={o.target}
    elseif c=='reclaim' then
      if not integer(o.target) then return 'invalid_target' end
      local x,y,z=Spring.GetFeaturePosition(o.target)
      if not x or not Spring.IsPosInLos(x,y,z,ally) then return 'target_not_visible_feature' end
      cmd=CMD.RECLAIM;params={o.target+((Engine.FeatureSupport and Engine.FeatureSupport.noOffsetForFeatureID) and 0 or Game.maxUnits)}
    elseif c=='build' or c=='produce' then
      local d=type(o.unit_type)=='string' and UnitDefNames[o.unit_type]
      if not d or #o.units~=1 then return 'invalid_build_type' end
      if c=='build' then
        if selected~=role(d) or not integer(o.facing) or o.facing>3 then return 'invalid_role_or_facing' end
        params[4]=o.facing
        if Spring.TestBuildOrder(d.id,params[1],params[2],params[3],o.facing)~=2 then return 'blocked_build_site' end
      else
        if selected~='production' or not integer(o.count) or o.count<1 or o.count>3 then return 'invalid_count' end
        count=o.count
      end
      cmd=-d.id
    else return 'invalid_command' end
    if c~='build' and c~='produce' and selected~=(c=='reclaim' and 'economy' or 'combat') then return 'invalid_role' end
    for _,u in ipairs(o.units) do
      if not integer(u) or not Spring.ValidUnitID(u) or Spring.GetUnitIsDead(u) or Spring.GetUnitTeam(u)~=team then return 'unit_not_owned' end
      if seen[u] then return 'duplicate_unit' end;seen[u]=true
      local d=UnitDefs[Spring.GetUnitDefID(u)];local _,_,_,_,progress=Spring.GetUnitHealth(u)
      if not progress or progress<1 then return 'unit_unfinished' end
      if (c=='move' or c=='fight') and d.isBuilding then return 'unit_cannot_move' end
      if (c=='attack' or c=='fight') and #(d.weapons or {})==0 then return 'unit_cannot_attack' end
      if (c=='repair' or c=='reclaim' or c=='build') and (not d.isBuilder or d.isFactory) then return 'unit_cannot_build' end
      if c=='produce' and not d.isFactory then return 'unit_not_factory' end
      if cmd<0 and not allowed(u,-cmd) then return 'type_not_buildable' end
      plan[#plan+1]={u=u,cmd=cmd,p=params,count=count}
    end
  end
  local accepted,total=0,0
  for _,o in ipairs(plan) do for i=1,o.count do total=total+1;if Spring.GiveOrderToUnit(o.u,o.cmd,o.p,0) then accepted=accepted+1 end end end
  return accepted==total and 'accepted' or accepted>0 and 'partial' or 'rejected',{accepted=accepted,total=total}
end
return M
