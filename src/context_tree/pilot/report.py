"""What real use of the pilot measured (goals 2, 5 and 6 of goals-and-method): the user's corrections by block, whether relays were
enough, how executors stopped, waiting time and cost. Read-only over a CTM directory's records; nothing is changed.

  python -m context_tree.pilot.report --root <CTM directory> [--since 2026-11-23] [--judge]

--judge asks the light model, for each user message, whether it corrects CTM or the executor (a semantic judgment, so by a model);
the messages it flags, and those the user corrected in the page, are listed as candidates for block evaluations.
"""
import argparse
import datetime
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

# page operations that correct something CTM did, and the block (goals-and-method 3.4) whose judgment they correct
CORRECTIONS = {
    'redirect': '1 delivery', 'reattach': '3 memory (message placement)',
    'move': '2 work relations', 'merge': '2 work relations', 'split': '2 work relations', 'rename': '2 work relations (naming)', 'purpose': '2 work relations (purpose)',
    'status': '7 status',
    'move_constraint': '3 memory (level)', 'drop_inherited': '3 memory (level)', 'constraint_kind': '3 memory (kind)',
    'edit_root': '3 memory (root)', 'add_preference': '3 memory (root)',
    'edit_doc': '5 result write-back (documents)',
}

JUDGE = '''The user is talking with an assistant (CTM); CTM passes the user's words to executors working in the background, relays their results to the user, and records the user's requirements.
Below are the latest few messages of the conversation before this user message, and this user message. Judge whether this message corrects something:
- ctm_delivery: CTM gave the words to the wrong work or in the wrong way;
- ctm_memory: CTM recorded the user's requirement wrongly, missed it, or recorded it too widely (for example taking this one change for a lasting rule);
- ctm_relay: CTM's relay missed something, got something wrong, or could not be understood;
- executor: the executor did something wrong, too much or too little, or went against the user's requirements;
- none: not a correction (a new request, an answer to a question, a follow-up, an approval).
Output JSON only: {"of":"ctm_delivery|ctm_memory|ctm_relay|executor|none","what":"what is corrected, one sentence"}'''


def _read(path):
    if not path.exists(): return []
    out = []
    for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        try: out.append(json.loads(line))
        except Exception: pass
    return out


def _t(e):
    try: return float(e.get('t') or 0)
    except Exception: return 0.0


def _pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0


def report(root, since=None, judge=False, model='gemini-3.8-flash'):
    root = Path(root)
    t0 = datetime.datetime.fromisoformat(since).timestamp() if since else 0
    ev = [e for e in _read(root / 'events.jsonl') if _t(e) >= t0]
    conv = [c for c in _read(root / 'conversation.jsonl') if _t(c) >= t0]
    kind = lambda e: e.get('kind') or e.get('type')
    by = defaultdict(list)
    for e in ev: by[kind(e)].append(e)
    lines = [f"# Usage report: {root} (since {since or 'the start'})", '']

    msgs = by['message']
    secs = [float(m.get('seconds') or 0) for m in msgs]; disp = [float(m.get('dispatch_seconds') or 0) for m in msgs if m.get('dispatch_seconds')]
    tok = defaultdict(int)
    for m in msgs:
        for u in (m.get('usage') or []) if isinstance(m.get('usage'), list) else []:
            tok[u.get('role')] += int(u.get('in') or 0) + int(u.get('out') or 0)
    lines += ['## Messages and waiting', f"- Your messages: {len(msgs)}; delivered as: {dict(Counter(m.get('to') for m in msgs))}",
              f"- CTM handling a message: median {statistics.median(secs) if secs else 0:.1f} s, 90% {_pct(secs, .9):.1f} s; until the executor starts: median {statistics.median(disp) if disp else 0:.1f} s",
              f"- Model tokens per message (input + output, by role): { {k: v // max(1, len(msgs)) for k, v in sorted(tok.items(), key=lambda kv: -kv[1])} }", '']

    ui = by['ui']
    corr = Counter(CORRECTIONS[u.get('op')] for u in ui if u.get('op') in CORRECTIONS)
    lines += ['## Your corrections on the page (each is one error of a CTM block)', f"- Total {sum(corr.values())}: {dict(corr) or 'none'}",
              f"- Other page actions: {dict(Counter(u.get('op') for u in ui if u.get('op') not in CORRECTIONS)) or 'none'}", '']

    replies = by['reply']; ctl = by['control']
    stops = Counter(f"{(c.get('stop') or {}).get('type')}/{(c.get('stop') or {}).get('action')}" for c in ctl if isinstance(c.get('stop'), dict))
    to_user = Counter((c.get('to_ctm') or {}).get('kind') for c in ctl if isinstance(c.get('to_ctm'), dict))
    proxy = sum(1 for c in ctl if isinstance(c.get('answer'), dict) and c['answer'].get('by') == 'ctm')
    cost = sum(float(r.get('cost') or 0) for r in replies)
    lines += ['## Executors', f"- Replies: {len(replies)} (aborted {sum(1 for r in replies if r.get('aborted') in (True, 'True'))}); executor cost in total {cost:.2f}",
              f"- Stops (kind/handling): {dict(stops) or 'none'}; passed to you: {dict(to_user) or 'none'}; answered by CTM from memory: {proxy}", '']

    relays = [c for c in conv if c.get('kind') == 'ctm' and not c.get('query')]
    views = by['view_record']
    lines += ['## Relays', f"- Relays: {len(relays)}; you opened an executor's original reply {len(views)} times (opening it often means the relays are not enough)", '']

    md = Counter(e.get('action') for e in by['ctm_md'])           # CTM's own records (concept 1.1, 3.5)
    props = Counter()
    if (root / 'ctm.sqlite').exists():
        import sqlite3
        db = sqlite3.connect(f"file:{(root / 'ctm.sqlite').as_posix()}?mode=ro", uri=True)
        for (d,) in db.execute("select data from items where type='pending' and at >= ? and data like ?", (t0, '%propose_annotation%')).fetchall():
            props[json.loads(d).get('status', 'open')] += 1          # patches rewrite the item: its data is the current state
        db.close()
    lines += ["## CTM's own records and proposals", f"- ctm.md: {md.get('written', 0)} entries written, {md.get('removed', 0)} removed",
              f"- Proposals to write source comments: {dict(props) or 'none'} (answered = you answered, superseded = the rule was replaced first, open = not answered yet; many open ones are a burden)", '']

    errs = Counter(str(e.get('where')) + ': ' + str(e.get('error'))[:60] for e in by['error'])
    lines += ['## Errors', f"- {sum(errs.values())} times" + (''.join(f"\n  - {k} ({v})" for k, v in errs.most_common(8)) if errs else ''), '']

    cands = [f"near turn {u.get('turn') or '?'}: page action {u.get('op')} ({CORRECTIONS[u.get('op')]})" for u in ui if u.get('op') in CORRECTIONS]
    if judge and msgs:
        from context_tree.ctm2.model import ask
        flagged = Counter()
        for m in msgs:
            before = [c for c in conv if _t(c) < _t(m)][-4:]
            recent = [{'kind': c.get('kind'), 'text': (c.get('text') or '')[:800]} for c in before]
            try:
                out, _ = ask(JUDGE, {'recent': recent, 'message': (m.get('text') or '')[:2000]}, model=model, effort='low', max_out=400, role='report-judge')
            except Exception as e:
                out = {'of': 'none', 'what': f'judgment failed: {e}'}
            if out.get('of') and out['of'] != 'none':
                flagged[out['of']] += 1
                cands.append(f"turn {m.get('turn')}: {(m.get('text') or '')[:60]} -> {out['of']}: {out.get('what', '')}")
        lines += ['## Your corrections in messages (judged by a model)', f"- {dict(flagged) or 'none'}", '']
    lines += ['## Messages worth turning into evaluation cases', *(f'- {c}' for c in cands)] if cands else ['## Messages worth turning into evaluation cases', '- none']
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description='What real use of the pilot measured (read-only).')
    ap.add_argument('--root', required=True); ap.add_argument('--since'); ap.add_argument('--judge', action='store_true')
    a = ap.parse_args()
    print(report(a.root, a.since, a.judge))


if __name__ == '__main__':
    main()
