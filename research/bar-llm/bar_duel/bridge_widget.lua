function widget:GetInfo() return {name='LLM Duel Transport',desc='Local experiment bridge',author='Research kit',layer=100000,enabled=true} end
local opts=Spring.GetModOptions()
if tostring(opts.llm_duel)~='1' then return false end
local prefix='LLMDUEL:'
  local client,server,buffer,out=nil,nil,'',''
  local function push(_,payload) if #out<200000 then out=out..payload..'\n' end end
  function widget:Initialize()
    if not socket then Spring.Echo('LLMDUEL ERROR: socket unavailable');return end
    server=socket.bind('127.0.0.1',tonumber(opts.llm_port) or 18765)
    if not server then Spring.Echo('LLMDUEL ERROR: port occupied');return end
    server:settimeout(0);widgetHandler:RegisterGlobal('LLMDuelSnapshot',function(payload) push(nil,payload) end)
    Spring.Echo('LLMDUEL bridge ready')
  end
  function widget:Update()
    if not server then return end
    if not client then client=server:accept();if client then client:settimeout(0);buffer='';out='' end end
    if not client then return end
    if #out>0 then local sent,err,last=client:send(out);out=out:sub((sent or last or 0)+1);if err=='closed' then client:close();client=nil;return end end
    local data,err,partial=client:receive(4096);buffer=buffer..(data or partial or '')
    if #buffer>16384 then client:close();client=nil;buffer='';return end
    while true do local p=buffer:find('\n',1,true);if not p then break end
      local line=buffer:sub(1,p-1);buffer=buffer:sub(p+1);Spring.SendLuaRulesMsg(prefix..line)
    end
    if err=='closed' then client:close();client=nil end
  end
  function widget:Shutdown()
    widgetHandler:DeregisterGlobal('LLMDuelSnapshot');if client then client:close() end;if server then server:close() end
  end