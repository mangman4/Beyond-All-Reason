-- Local research mutator: identical mechanics for both LLM-controlled teams.
function gadget:GetInfo()
  return {name='LLM Duel Bridge',desc='Local two-team experiment',author='Research kit',layer=100000,enabled=true}
end
local json=VFS.Include('common/luautilities/json.lua')
local opts=Spring.GetModOptions()
if tostring(opts.llm_duel)~='1' then return false end
local prefix='LLMDUEL:'
if gadgetHandler:IsSyncedCode() then
  local tactics=VFS.Include('luarules/gadgets/include/llm_tactics.lua')
  local direct=VFS.Include('luarules/gadgets/include/llm_direct.lua')
  local spots, lastRequest={}, {}
  local ended=false
  local function pos(u) local x,y,z=Spring.GetUnitPosition(u); return x,y,z end
  local function idle(u)
    local ud=UnitDefs[Spring.GetUnitDefID(u)]
    if ud.isFactory then return (Spring.GetFactoryCommands(u,0) or 0)==0 end
    return (Spring.GetUnitCommandCount(u) or 0)==0
  end
  local function complete(u) local _,_,_,_,p=Spring.GetUnitHealth(u); return p and p>=1 end
  local function allowed(u,d)
    for _,id in ipairs(UnitDefs[Spring.GetUnitDefID(u)].buildOptions or {}) do if id==d then return true end end
    return false
  end
  local function buildsite(d,x,z)
    for r=96,640,64 do for k=0,15 do
      local a=k*math.pi/8; local px=math.floor((x+math.cos(a)*r)/16)*16
      local pz=math.floor((z+math.sin(a)*r)/16)*16
      if px>64 and pz>64 and px<Game.mapSizeX-64 and pz<Game.mapSizeZ-64 then
        local py=Spring.GetGroundHeight(px,pz)
        if py>0 and Spring.TestBuildOrder(d,px,py,pz,0)==2 then return {px,py,pz,0} end
      end
    end end
  end
  local function observation(team)
    local obs={team=team,frame=Spring.GetGameFrame(),units={},completed={},candidates={{id='wait',description='Keep existing orders'}},enemies={},map={x=Game.mapSizeX,z=Game.mapSizeZ}}
    local metal,ms,_,mi,me=Spring.GetTeamResources(team,'metal')
    local energy,es,_,ei,ee=Spring.GetTeamResources(team,'energy')
    obs.resources={metal=math.floor(metal or 0),energy=math.floor(energy or 0),metal_income=mi,metal_spend=me,energy_income=ei,energy_spend=ee}
    local orders={wait={}}
    local builders,factories,army={},{},{}
    for _,u in ipairs(Spring.GetTeamUnits(team)) do
      local ud=UnitDefs[Spring.GetUnitDefID(u)]
      obs.units[ud.name]=(obs.units[ud.name] or 0)+1
      if complete(u) then
        obs.completed[ud.name]=(obs.completed[ud.name] or 0)+1
        if ud.isFactory and idle(u) then factories[#factories+1]=u
        elseif ud.isBuilder and idle(u) then builders[#builders+1]=u
        elseif not ud.isBuilder and not ud.isBuilding and ud.canAttack then army[#army+1]=u end
      end
    end
    table.sort(builders);table.sort(factories);table.sort(army)
    obs.idle_builders=#builders;obs.army=#army
    if #army>0 then
      local sx,sz=0,0
      for _,u in ipairs(army) do local x,_,z=pos(u);sx=sx+x;sz=sz+z end
      obs.army_center={x=math.floor(sx/#army),z=math.floor(sz/#army)}
    end
    local ally=select(6,Spring.GetTeamInfo(team,false))
    for _,u in ipairs(Spring.GetAllUnits()) do
      if not Spring.AreTeamsAllied(team,Spring.GetUnitTeam(u)) then
        local los=Spring.GetUnitLosState(u,ally,true)
        -- Only currently visible enemies; neither spectator vision nor radar identities leak.
        if los and los%2==1 then
          local x,_,z=pos(u);obs.enemies[#obs.enemies+1]={id=u,x=math.floor(x),z=math.floor(z),type=UnitDefs[Spring.GetUnitDefID(u)].name}
          if #obs.enemies>=24 then break end
        end
      end
    end
    local function add(id,description,list) orders[id]=list;obs.candidates[#obs.candidates+1]={id=id,description=description} end
    for _,spec in ipairs({{'energy','armsolar'},{'factory','armvp'},{'defense','armllt'},{'radar','armrad'}}) do
      local d=UnitDefNames[spec[2]] and UnitDefNames[spec[2]].id
      if d then for _,u in ipairs(builders) do if allowed(u,d) then
        local x,_,z=pos(u);local p=buildsite(d,x,z)
        if p then add('build_'..spec[1], 'Build '..spec[2]..' with idle constructor',{{u=u,cmd=-d,p=p}});break end
      end end end
    end
    local mex=UnitDefNames.armmex.id
    local best,dist
    for _,u in ipairs(builders) do if allowed(u,mex) then
      local x,_,z=pos(u)
      for _,s in ipairs(spots) do
        local dd=(x-s.x)^2+(z-s.z)^2
        if (not dist or dd<dist) and Spring.TestBuildOrder(mex,s.x,s.y,s.z,0)==2 then
          local occupied=false
          for _,near in ipairs(Spring.GetUnitsInCylinder(s.x,s.z,110,team)) do
            if UnitDefs[Spring.GetUnitDefID(near)].extractsMetal>0 then occupied=true;break end
          end
          if not occupied then best={u=u,cmd=-mex,p={s.x,s.y,s.z,0}};dist=dd end
        end
      end
    end end
    if best then add('expand_metal','Build metal extractor at nearest available deposit',{best}) end
    for _,spec in ipairs({{'tank','armstump'},{'scout','armfav'},{'constructor','armcv'}}) do
      local d=UnitDefNames[spec[2]].id
      for _,u in ipairs(factories) do if allowed(u,d) then
        add('produce_'..spec[1],'Produce '..spec[2],{{u=u,cmd=-d,p={}}});break
      end end
    end
    if #army>0 then
      local x,y,z=Spring.GetTeamStartPosition(team)
      local target=obs.enemies[1]
      local tx,tz=target and target.x or Game.mapSizeX-x,target and target.z or Game.mapSizeZ-z
      local attack,retreat,scout={},{},{}
      for i=1,math.min(60,#army) do
        attack[#attack+1]={u=army[i],cmd=CMD.FIGHT,p={tx,Spring.GetGroundHeight(tx,tz),tz}}
        retreat[#retreat+1]={u=army[i],cmd=CMD.MOVE,p={x,y,z}}
        scout[#scout+1]={u=army[i],cmd=CMD.FIGHT,p={Game.mapSizeX/2,Spring.GetGroundHeight(Game.mapSizeX/2,Game.mapSizeZ/2),Game.mapSizeZ/2}}
      end
      add('attack','Attack visible enemy or explore opposite start area',attack)
      add('retreat','Return army to own start area',retreat)
      add('scout_center','Move army toward center',scout)
    end
    tactics.enrich(obs,orders)
    if tostring(opts.llm_direct)=='1' then direct.enrich(obs,spots) end
    if tostring(opts.llm_assisted)=='1' then obs.control_mode='assisted' end
    obs.alive=next(obs.units)~=nil
    return obs,orders
  end
  function gadget:GameFrame(f)
    if f==1 then
      Spring.SetGameRulesParam('ainame_0','Cloud GLM')
      Spring.SetGameRulesParam('ainame_1','Local Qwen')
      if tostring(opts.llm_fixture)=='1' then
        for team=0,1 do
          local x,_,z=Spring.GetTeamStartPosition(team)
          local sign=team==0 and 1 or -1
          for i,name in ipairs({'armvp','armcv','armstump','armstump','armstump'}) do
            local px=x+sign*200;local pz=z+(i-3)*140
            local uid=Spring.CreateUnit(name,px,Spring.GetGroundHeight(px,pz),pz,0,team)
            if uid and i==3 then local _,max=Spring.GetUnitHealth(uid);Spring.SetUnitHealth(uid,max*.4) end
          end
          if FeatureDefNames.armstump_dead then Spring.CreateFeature('armstump_dead',x+sign*150,Spring.GetGroundHeight(x+sign*150,z+350),z+350,0,team) end
        end
        Spring.Echo('LLMDUEL TEST FIXTURE: not a normal LLM match')
      end
      -- Terrain is public information. Cluster positive metal cells into deposits.
      for x=16,Game.mapSizeX-16,32 do for z=16,Game.mapSizeZ-16,32 do
        local _,_,m=Spring.GetGroundInfo(x,z)
        if m and m>0 then
          local found
          for _,s in ipairs(spots) do if (s.x-x)^2+(s.z-z)^2<128^2 then found=s;break end end
          if found then found.sx=found.sx+x;found.sz=found.sz+z;found.n=found.n+1;found.x=found.sx/found.n;found.z=found.sz/found.n
          else spots[#spots+1]={x=x,z=z,sx=x,sz=z,n=1} end
        end
      end end
      for _,s in ipairs(spots) do s.x=math.floor(s.x/16)*16;s.z=math.floor(s.z/16)*16;s.y=Spring.GetGroundHeight(s.x,s.z) end
      Spring.Echo('LLMDUEL metal deposits',#spots)
    end
    if f==900 and opts.llm_victorytest~=nil then
      local loser=tonumber(opts.llm_victorytest)
      for _,u in ipairs(Spring.GetTeamUnits(loser)) do if UnitDefs[Spring.GetUnitDefID(u)].customParams.iscommander then Spring.DestroyUnit(u,false,true) end end
      Spring.Echo('LLMDUEL TEST: eliminated commander for termination validation')
    end
    if ended or f%30~=0 then return end
    for team=0,1 do
      local obs=observation(team)
      SendToUnsynced('llm_snapshot',json.encode(obs))
    end
  end
  function gadget:RecvLuaMsg(msg,player)
    if msg:sub(1,#prefix)~=prefix or player~=0 or ended then return end
    local ok,v=pcall(json.decode,msg:sub(#prefix+1))
    if not ok or type(v)~='table' or (v.team~=0 and v.team~=1) or type(v.request)~='number' or type(v.frame)~='number' or type(v.action)~='string' then return end
    if v.request%1~=0 or v.frame%1~=0 or v.request<1 or v.request>1000000000 then return end
    if v.request<=(lastRequest[v.team] or 0) then return end
    lastRequest[v.team]=v.request
    local status,details='stale',nil
    if Spring.GetGameFrame()-v.frame<=1800 and v.frame<=Spring.GetGameFrame() then
      if tostring(opts.llm_direct)=='1' then
        status,details=direct.apply(v.team,v.action,v.orders)
      else
      local _,orders=observation(v.team);local list=orders[v.action]
      status='unavailable'
      if list then
        local accepted=0
        for _,o in ipairs(list) do
          if Spring.ValidUnitID(o.u) and Spring.GetUnitTeam(o.u)==v.team and Spring.GiveOrderToUnit(o.u,o.cmd,o.p,0) then accepted=accepted+1 end
        end
        status=#list==0 and 'wait' or (accepted>0 and 'accepted' or 'rejected')
      end
      end
    end
    SendToUnsynced('llm_snapshot',json.encode({ack=true,team=v.team,request=v.request,status=status,frame=Spring.GetGameFrame(),action=v.action,details=details}))
  end
  function gadget:GameOver(winners)
    for team=0,1 do SendToUnsynced('llm_snapshot',json.encode((observation(team)))) end
    ended=true;SendToUnsynced('llm_snapshot',json.encode({gameover=true,winners=winners,frame=Spring.GetGameFrame()}))
  end
  function gadget:UnitDestroyed(u,def,team) tactics.lost(team) end
  function gadget:AllowFeatureBuildStep(builder,team,feature,def,part) tactics.reclaim(team,feature,part);return true end
else
  local function push(_,payload)
    if Script.LuaUI('LLMDuelSnapshot') then Script.LuaUI.LLMDuelSnapshot(payload) end
  end
  function gadget:Initialize() gadgetHandler:AddSyncAction('llm_snapshot',push) end
  function gadget:Shutdown() gadgetHandler:RemoveSyncAction('llm_snapshot') end
end
