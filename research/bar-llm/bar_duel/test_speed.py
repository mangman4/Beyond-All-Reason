import json
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer
from speed import SpeedControl,handler

class SpeedTests(unittest.TestCase):
    def test_allowlist(self):
        for value in (True,None,0,3,8,'2',float('nan'),[]):
            with self.subTest(value=value),self.assertRaises(ValueError):SpeedControl().request(value)
    def test_confirmation_must_match_request_and_target(self):
        c=SpeedControl();c.request(4)
        self.assertEqual(c.dispatch(10),{'control':'speed','request':1,'speed':4})
        self.assertIsNone(c.dispatch(11))
        report=dict(request=0,requested=1,actual=.9,engine_speed=1,paused=False)
        c.observe(report);self.assertTrue(c.state['pending'])
        c.observe({**report,'request':1,'requested':2});self.assertTrue(c.state['pending'])
        c.observe({**report,'request':1,'requested':4});self.assertFalse(c.state['pending'])
        self.assertEqual(c.state['actual'],.9)
    def test_pending_and_timeout_retry(self):
        c=SpeedControl();c.request(2)
        with self.assertRaises(RuntimeError):c.request(4)
        c.dispatch(0);c.expire(11)
        self.assertFalse(c.state['pending']);self.assertTrue(c.state['error'])
        c.request(4);self.assertEqual(c.dispatch(12)['request'],2)
    def test_http_control_boundary(self):
        c=SpeedControl();state={'status':'running','speed':c.state}
        # Port 0 is sufficient for tests with no Origin; explicitly wrong origins are rejected.
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(state,threading.Lock(),c,Path(__file__).with_name('dashboard.html'),0))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            page=opener.open(base).read().decode()
            token=page.split("'X-Speed-Token':'",1)[1].split("'",1)[0]
            self.assertNotEqual(token,'__SPEED_TOKEN__')
            def post(value,secret=token,origin=None):
                headers={'Content-Type':'application/json','X-Speed-Token':secret}
                if origin:headers['Origin']=origin
                req=urllib.request.Request(base+'/speed',data=json.dumps(value).encode(),headers=headers)
                try:return opener.open(req).status
                except urllib.error.HTTPError as e:return e.code
            self.assertEqual(post({'speed':2},secret='wrong'),403)
            self.assertEqual(post({'speed':2},origin='https://example.com'),403)
            self.assertEqual(post({'speed':3}),400)
            self.assertEqual(post({'speed':2}),202)
            self.assertEqual(post({'speed':4}),409)
            state['status']='finished'
            self.assertEqual(post({'speed':1}),409)
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
