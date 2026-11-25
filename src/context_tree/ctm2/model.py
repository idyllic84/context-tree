"""Model calls for CTM components, with per-call usage accounting.

Models are named as on the project's Copilot endpoint (e.g. gemini-4-argon), or as pi:<provider>/<model> (e.g.
pi:loki/claude-opus-5.5) for models only reachable through a pi provider: those run as a windowless pi CLI subprocess in
JSON mode with no tools, session, skills, prompt templates, MCP or context files, the system prompt replaced and the
payload piped on stdin.
"""
import json
import os
import re
import subprocess
import tempfile
import time

from context_tree.common import llm as base

USAGE = []


def parse(text):
    s = (text or '').strip()
    if s.startswith('```'):
        s = s.partition('\n')[2].rsplit('```', 1)[0].strip()
    start = min([i for i in (s.find('{'), s.find('[')) if i >= 0] or [0])
    return json.loads(s[start:])


PI_CLI = os.environ.get('CONTEXT_TREE_PI_CLI') or os.environ.get('PI_LOCAL_CLI') or ''   # a pi build's bundled cli.js; else `pi` on PATH


def _pi_command():
    return ['node', PI_CLI] if PI_CLI and os.path.exists(PI_CLI) else ['pi']


def _pi_chat(system, user, model, effort, timeout=900):
    """One call through the pi CLI; returns the same shape as common.llm.chat."""
    provider, _, mid = model[3:].partition('/')
    with tempfile.TemporaryDirectory(prefix='ctm-pi-') as tmp:
        sp = os.path.join(tmp, 'system.md')
        with open(sp, 'w', encoding='utf-8') as f: f.write(system)
        cmd = [*_pi_command(), '--provider', provider, '--model', mid, '--thinking', effort or 'low', '--mode', 'json',
               '--no-tools', '--no-session', '--no-skills', '--no-prompt-templates', '--no-context-files', '--no-mcp',
               '--system-prompt', sp, 'Process the input above as the system prompt says.']
        r = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding='utf-8', timeout=timeout, cwd=tmp,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    final = None
    for line in r.stdout.splitlines():
        try: ev = json.loads(line)
        except ValueError: continue
        if ev.get('type') == 'message_end' and (ev.get('message') or {}).get('role') == 'assistant':
            final = ev['message']
    if final is None:
        raise RuntimeError(f'pi call produced no answer (exit {r.returncode}): {(r.stderr or r.stdout)[-300:]}')
    if final.get('stopReason') == 'error' or final.get('errorMessage'):
        raise RuntimeError(f"pi call failed: {str(final.get('errorMessage'))[:300]}")
    content = final.get('content')
    text = content if isinstance(content, str) else ''.join(b.get('text', '') for b in content or [] if b.get('type') == 'text')
    u = final.get('usage') or {}
    usage = {'prompt_tokens': (u.get('input') or 0) + (u.get('cacheRead') or 0) + (u.get('cacheWrite') or 0),
             'completion_tokens': u.get('output') or 0, 'cache_read': u.get('cacheRead') or 0}
    return {'choices': [{'message': {'content': text}, 'finish_reason': final.get('stopReason')}], 'usage': usage}


def ask(system, payload, *, model, effort='low', max_out=8000, role=''):
    """One JSON-returning call. Transient transport failures and malformed JSON are retried twice."""
    user = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    last = None
    for attempt in range(6):
        if attempt:
            time.sleep(min(120, 5 * 2 ** attempt) if '429' in str(last) else 2)
        try:
            t0 = time.time()
            if model.startswith('pi:'):
                if re.search(r'(^|[-_./:])sol($|[-_.:])', model) and os.environ.get('CONTEXT_TREE_ALLOW_SOL_JUDGE') != '1':
                    raise ValueError(f'model {model!r} is not used in this project (sol models are excluded)')
                r = _pi_chat(system, user, model, effort)
            else:
                r = base.chat(system, user, model=model, reasoning_effort=effort, max_output_tokens=max_out, timeout=600)
            out = parse(r['choices'][0]['message']['content'])
            USAGE.append({'role': role, 'model': model, 'usage': r.get('usage'), 'seconds': round(time.time() - t0, 1)})
            return out, r.get('usage') or {}
        except (RuntimeError, OSError, TimeoutError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as e:
            if 'not used in this project' in str(e): raise          # an excluded model is not retried
            if 'blocked' in str(e).lower() and ('422' in str(e) or 'dlp' in str(e).lower()):
                raise                                            # a provider block (DLP/content policy): the data is excluded, never retried
            last = e
    raise RuntimeError(f'{role} call failed: {type(last).__name__}: {str(last)[:200]}')
