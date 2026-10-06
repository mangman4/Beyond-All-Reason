"""Ollama Cloud controller for the real, pinned OpenFront engine. Stdlib only."""
from __future__ import annotations
import argparse
import json
import os
import sys
import queue
import multiprocessing
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class InferenceError(RuntimeError):
    def __init__(self, message, metrics=None, retryable=True):
        super().__init__(message)
        self.metrics = metrics or {}
        self.retryable = retryable


class DecisionDeadline(RuntimeError):
    def __init__(self, kind, metrics):
        super().__init__('AI 요청 제한 시간 초과: ' + kind)
        self.metrics = metrics


def _cloud_worker(connection, payload, key, timeout):
    """Disposable network process; never send response text or credentials on errors."""
    try:
        result = cloud_response(payload, key, timeout,
                                progress=lambda event: connection.send(('progress', event)))
        connection.send(('result', result))
    except Exception as exc:
        safe = str(exc).replace(key, '[REDACTED]') if key else str(exc)
        # Known cloud errors are already sanitized. Unexpected errors are type-only.
        connection.send(('error', {'message': safe if isinstance(exc, RuntimeError) else type(exc).__name__,
            'retryable': getattr(exc, 'retryable', True)}))
    finally:
        connection.close()


def bounded_cloud_response(payload, key, timeout, cancel=None, worker_target=None,
                           first_output_limit=6.0, idle_limit=4.0):
    """Wall-clock deadlines cover connect, headers, reads AND trickling streams."""
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe(duplex=False)
    worker = context.Process(target=worker_target or _cloud_worker,
                             args=(child, payload, key, timeout), daemon=True)
    started = time.monotonic()
    first_output = None
    first_answer = None
    last_output = started
    phase = 'connecting'
    worker.start()
    child.close()
    try:
        while True:
            now = time.monotonic()
            elapsed = now-started
            kind = None
            if cancel is not None and cancel.is_set():
                kind = 'cancelled'
            elif elapsed >= timeout:
                kind = 'total_deadline'
            elif first_output is None and elapsed >= first_output_limit:
                kind = 'first_output_deadline'
            elif first_output is not None and now-last_output >= idle_limit:
                kind = 'stream_idle_deadline'
            if kind:
                raise DecisionDeadline(kind, {'timeout_kind': kind, 'last_phase': phase,
                    'latency_seconds': round(elapsed, 3), 'first_output_seconds': first_output,
                    'first_answer_seconds': first_answer, 'input_tokens': None, 'output_tokens': None,
                    'usage_complete': False})
            if not parent.poll(0.02):
                continue
            try:
                event, value = parent.recv()
            except EOFError:
                raise RuntimeError('AI 네트워크 작업이 응답 없이 종료됐습니다.') from None
            if event == 'result':
                return value
            if event == 'error':
                raise InferenceError(value['message'], {'latency_seconds': round(elapsed, 3),
                    'usage_complete': False}, value['retryable'])
            if event == 'progress':
                phase = value['phase']
                if value.get('output'):
                    last_output = time.monotonic()
                    if first_output is None:
                        first_output = round(last_output-started, 3)
                    if phase == 'answer' and first_answer is None:
                        first_answer = round(last_output-started, 3)
    finally:
        # A blocked socket cannot outlive this request and occupy later decisions.
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=0.5)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=0.5)
        if worker.is_alive():
            raise RuntimeError('AI 작업 종료 실패: 중복 요청을 막기 위해 중단했습니다.')
        parent.close()
        worker.close()
def cloud_response(payload, key, timeout, progress=None):
    local = payload.get('_backend') == 'local'
    headers = {'Content-Type': 'application/json'}
    if not local:
        headers['Authorization'] = 'Bearer ' + key
    request = urllib.request.Request('http://127.0.0.1:11434/api/chat' if local else 'https://ollama.com/api/chat',
        data=json.dumps({k:v for k,v in payload.items() if not k.startswith('_')}).encode(), headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})).open if local else urllib.request.urlopen
    started = time.monotonic()
    timing = {'first_output_seconds': None, 'first_answer_seconds': None}
    answer = []
    thinking_returned = False
    result = None
    try:
        with opener(request, timeout=timeout) as response:
            if progress:
                progress({'phase': 'headers', 'output': False})
            for line in response:
                if time.monotonic() - started > timeout:
                    raise TimeoutError()
                if not line.strip():
                    continue
                part = json.loads(line)
                if not isinstance(part, dict) or 'error' in part:
                    detail = str(part.get('error', '')) .lower() if isinstance(part, dict) else ''
                    category = next((label for token, label in [
                        ('token repeat limit', '반복 토큰 생성으로 서버가 중단함'),
                        ('memory', '메모리 부족'), ('context', '문맥 처리 실패'),
                        ('grammar', '출력 형식 처리 실패'), ('decode', '출력 생성 실패'),
                        ('runner', '모델 실행기 오류'), ('load', '모델 로딩 실패')]
                        if token in detail), '서버 스트림 오류')
                    raise InferenceError('Ollama: ' + category + ' (응답 원문 미저장)')
                message = part.get('message') or {}
                if not isinstance(message, dict):
                    raise RuntimeError('Ollama 메시지 형식이 올바르지 않습니다.')
                content = message.get('content') or ''
                if not isinstance(content, str):
                    raise RuntimeError('Ollama 답변 형식이 올바르지 않습니다.')
                thinking = bool(message.get('thinking'))
                thinking_returned |= thinking
                if progress and (content or thinking):
                    progress({'phase': 'answer' if content else 'thinking', 'output': True})
                elapsed = round(time.monotonic()-started, 3)
                if (content or thinking) and timing['first_output_seconds'] is None:
                    timing['first_output_seconds'] = elapsed
                if content and timing['first_answer_seconds'] is None:
                    timing['first_answer_seconds'] = elapsed
                answer.append(content)
                if part.get('done'):
                    # Preserve only usage metadata, never reasoning text.
                    result = {k: part[k] for k in ('model', 'prompt_eval_count', 'eval_count', 'eval_duration') if k in part}
                    break
    except urllib.error.HTTPError as exc:
        # Never copy raw upstream bodies or request headers into logs.
        hints = {401: 'API key rejected', 403: 'Model/account access denied', 404: 'Model unavailable; check OLLAMA_MODEL',
                 429: 'Cloud usage or rate limit reached; wait and resume'}
        raise InferenceError(hints.get(exc.code, f'Ollama HTTP {exc.code}'),
                             retryable=exc.code not in (400, 401, 403, 404)) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('Ollama connection failed or timed out; game stopped without a fallback move') from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError('Ollama 서버 응답이 비었거나 JSON 형식이 아닙니다. 잠시 후 다시 실행하세요.') from None
    if result is None:
        raise RuntimeError('Ollama 응답 스트림이 완료 전에 끊겼습니다.')
    timing['total_seconds'] = round(time.monotonic()-started, 3)
    count, duration = result.get('eval_count'), result.get('eval_duration')
    timing['server_tokens_per_second'] = round(count*1e9/duration, 2) if isinstance(count, int) and isinstance(duration, (int, float)) and duration > 0 else None
    result.update(message={'content': ''.join(answer)}, _timing=timing, _thinking_returned=thinking_returned)
    return result


