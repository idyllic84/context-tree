"""One pi executor session in RPC mode (pi --mode rpc): a windowless child process controlled by JSONL commands on stdin,
emitting session events on stdout (pi docs: rpc.md, rpc-commands.md, json.md, rpc-extension-ui.md).

The pilot keeps one PiSession per CTM run. A turn is one prompt until `agent_settled`; the session collects the assistant
text and the tool calls of the turn and reports them through `on_settled`."""
import json
import os
import subprocess
import threading
import time
import uuid

CREATE_NO_WINDOW = 0x08000000
READONLY_TOOLS = 'read,grep,find,ls'


def pi_command():
    """How to start pi: node + a build's bundled CLI (CONTEXT_TREE_PI_CLI or PI_LOCAL_CLI), else `pi` on PATH."""
    cli = os.environ.get('CONTEXT_TREE_PI_CLI') or os.environ.get('PI_LOCAL_CLI') or ''
    if cli and os.path.exists(cli):
        return ['node', cli]
    return ['pi']


class PiSession:
    """A pi RPC child process. Callbacks run on the reader thread: on_event(session, event) for every event (streaming
    display), on_settled(session, turn_result) when a prompt's run has settled, on_dialog(session, request) for
    extension dialogs that need an answer, on_exit(session, code)."""

    def __init__(self, *, cwd, session_dir, name='', session_file=None, fork_from=None, readonly=False, log_path=None,
                 on_event=None, on_settled=None, on_dialog=None, on_exit=None, command=None):
        args = (command or pi_command()) + ['--mode', 'rpc']
        if session_file:
            args += ['--session', session_file]
        else:
            args += ['--session-dir', session_dir]
            if fork_from: args += ['--fork', fork_from]
        if name and not session_file: args += ['--name', name[:60]]
        if readonly: args += ['--tools', READONLY_TOOLS]
        self.args, self.cwd, self.readonly = args, cwd, readonly
        self.on_event, self.on_settled, self.on_dialog, self.on_exit = on_event, on_settled, on_dialog, on_exit
        self.log = open(log_path, 'ab') if log_path else subprocess.DEVNULL
        self.proc = subprocess.Popen(args, cwd=cwd or None, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                     creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self._lock = threading.Lock()
        self._waiting = {}                       # command id -> [Event, response]
        self.busy = False
        self.session_file = session_file
        self.turn = None                         # the CTM turn whose prompt is running
        self._text = {}                          # contentIndex -> text of the current assistant message
        self._last_text = ''
        self.tools = []                          # tool calls of the current turn: {name, args, path, success}
        self.usage = {}
        threading.Thread(target=self._read, daemon=True).start()

    # ---- commands --------------------------------------------------------------------------------------------------
    def send(self, cmd, wait=True, timeout=60.0):
        cid = cmd.get('id') or uuid.uuid4().hex[:12]
        cmd = dict(cmd, id=cid)
        slot = [threading.Event(), None]
        if wait: self._waiting[cid] = slot
        data = (json.dumps(cmd, ensure_ascii=False) + '\n').encode('utf-8')
        with self._lock:
            self.proc.stdin.write(data); self.proc.stdin.flush()
        if not wait: return None
        if not slot[0].wait(timeout):
            self._waiting.pop(cid, None)
            raise TimeoutError(f'pi did not answer {cmd.get("type")}')
        return slot[1]

    def prompt(self, text, turn):
        """Start a run with this text, or steer the running one."""
        if self.busy:
            return self.send({'type': 'prompt', 'message': text, 'streamingBehavior': 'steer'})
        self.turn, self.busy = turn, True
        self._text, self._last_text, self.tools = {}, '', []
        r = self.send({'type': 'prompt', 'message': text})
        if r and not r.get('success'):
            self.busy = False
        elif r and (r.get('data') or {}).get('disposition') == 'handled':
            self.busy = False
        return r

    def abort(self):
        return self.send({'type': 'abort'}, timeout=30.0)

    def state(self):
        r = self.send({'type': 'get_state'})
        d = (r or {}).get('data') or {}
        if d.get('sessionFile'): self.session_file = d['sessionFile']
        return d

    def stats(self):
        return ((self.send({'type': 'get_session_stats'}) or {}).get('data') or {})

    def answer_dialog(self, request_id, **answer):
        self.send({'type': 'extension_ui_response', 'id': request_id, **answer}, wait=False)

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()

    @property
    def alive(self):
        return self.proc.poll() is None

    # ---- events ----------------------------------------------------------------------------------------------------
    def _read(self):
        buf = b''
        out = self.proc.stdout
        while True:
            chunk = out.read1(65536) if hasattr(out, 'read1') else out.read(1)
            if not chunk: break
            buf += chunk
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                line = line.rstrip(b'\r')
                if not line: continue
                try:
                    ev = json.loads(line.decode('utf-8'))
                except ValueError:
                    continue
                try:
                    self._handle(ev)
                except Exception as e:                 # a display callback must not kill the reader
                    try: self.log.write(f'[pilot] event handler error: {e}\n'.encode('utf-8'))
                    except Exception: pass
        code = self.proc.wait()
        if self.on_exit: self.on_exit(self, code)

    def _handle(self, ev):
        t = ev.get('type')
        if t == 'response':
            slot = self._waiting.pop(ev.get('id'), None)
            if slot: slot[1] = ev; slot[0].set()
            return
        if t == 'extension_ui_request':
            if ev.get('method') in ('select', 'confirm', 'input', 'editor'):
                if self.on_dialog: self.on_dialog(self, ev)
                else: self.answer_dialog(ev['id'], cancelled=True)
            return
        if t == 'message_update':
            u = ev.get('assistantMessageEvent') or {}
            if u.get('type') == 'text_delta':
                i = u.get('contentIndex', 0); self._text[i] = self._text.get(i, '') + (u.get('delta') or '')
            elif u.get('type') == 'text_end':
                self._text[u.get('contentIndex', 0)] = u.get('content') or ''
            if ev.get('usage'): self.usage = ev['usage']
        elif t == 'message_end':
            m = ev.get('message') or {}
            if m.get('role') == 'assistant':
                txt = ''.join(c.get('text', '') for c in (m.get('content') or []) if isinstance(c, dict) and c.get('type') == 'text')
                if txt.strip(): self._last_text = txt
                self._text = {}
        elif t == 'tool_execution_start':
            a = ev.get('args') or {}
            self.tools.append({'id': ev.get('toolCallId'), 'name': ev.get('toolName'), 'args': a,
                               'path': a.get('path') or a.get('file_path') or a.get('filePath'), 'success': None})
        elif t == 'tool_execution_end':
            for x in reversed(self.tools):
                if x['id'] == ev.get('toolCallId'):
                    x['success'] = not ev.get('isError'); break
        if self.on_event: self.on_event(self, ev)
        if t == 'agent_settled':
            self.busy = False
            result = {'turn': self.turn, 'reply': self._last_text, 'tools': list(self.tools), 'aborted': bool(ev.get('aborted')),
                      'usage': self.usage, 'at': time.time()}
            if self.on_settled: self.on_settled(self, result)
