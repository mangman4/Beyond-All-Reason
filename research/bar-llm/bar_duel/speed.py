"""Dashboard speed requests; only the runner thread writes to the game socket."""
import json
import secrets
from http.server import BaseHTTPRequestHandler

class SpeedControl:
    def __init__(self):
        self.state={'requested':1,'actual':None,'engine_speed':None,'paused':False,'pending':False,'error':None}
        self.sequence=0
        self.command=None
        self.sent_at=None
        self.target=None

    def request(self,value):
        if type(value) not in (int,float) or value not in (1,2,4):
            raise ValueError('배속은 1, 2, 4 중 하나여야 합니다.')
        if self.state['pending']:raise RuntimeError('이전 배속 요청을 확인 중입니다.')
        self.sequence+=1;self.target=value
        self.command={'control':'speed','speed':value,'request':self.sequence}
        self.state.update(pending=True,error=None)

    def dispatch(self,now):
        command=self.command;self.command=None
        if command:self.sent_at=now
        return command

    def observe(self,value):
        for key in ('requested','actual','engine_speed','paused'):
            self.state[key]=value[key]
        if self.state['pending'] and value.get('request')==self.sequence and value['requested']==self.target:
            self.state.update(pending=False,error=None);self.sent_at=None

    def expire(self,now):
        if self.sent_at is not None and now-self.sent_at>10:
            self.state.update(pending=False,error='엔진의 배속 적용 확인 시간이 초과됐습니다. 다시 시도하세요.')
            self.sent_at=None

def handler(state,lock,control,dashboard,port):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def reply(self,code,value):
            data=json.dumps(value,ensure_ascii=False).encode()
            self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path=='/state':
                with lock:data=json.dumps(state,ensure_ascii=False).encode()
                typ='application/json'
            elif self.path=='/':
                data=dashboard.read_text(encoding='utf-8').replace('__SPEED_TOKEN__',token).encode();typ='text/html; charset=utf-8'
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',typ);self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
        def do_POST(self):
            if self.path!='/speed':self.send_error(404);return
            if self.headers.get('X-Speed-Token')!=token or self.headers.get('Origin') not in (None,f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
                self.reply(403,{'error':'허용되지 않은 요청입니다.'});return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=128:raise ValueError('잘못된 요청 크기입니다.')
                value=json.loads(self.rfile.read(length))
                if not isinstance(value,dict):raise ValueError('잘못된 요청입니다.')
                with lock:
                    if state['status']!='running':raise RuntimeError('경기 진행 중에만 배속을 바꿀 수 있습니다.')
                    control.request(value.get('speed'))
            except (ValueError,UnicodeError) as exc:self.reply(400,{'error':str(exc)});return
            except RuntimeError as exc:self.reply(409,{'error':str(exc)});return
            self.reply(202,{'queued':True})
        def log_message(self,*a):pass
    return Handler
