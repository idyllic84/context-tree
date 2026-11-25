import sys
sys.path.insert(0, 'src')
from context_tree.ctm2.store import Store
from context_tree.ctm2.tree import StoreTree
from context_tree.ctm2 import candidates as K
from context_tree.ctm2 import documents as D
from context_tree.ctm2 import execution as X


def stub_embed(texts):
    # bag of characters: enough to make similar strings close, never used for identifiers
    out = []
    for t in texts:
        v = [0.0] * 64
        for ch in t.lower(): v[ord(ch) % 64] += 1
        out.append(v)
    return out


def setup():
    s = Store(); t = StoreTree(s)
    a = t.add('Update the latency query guide', 'Add concurrent queries to the guide', None, None, 0, 0.0)
    b = t.add('Fix the routing regression', 'Fix the external model routing', None, None, 1, 10.0)
    run, _, _ = X.executor_for(s, a, at=1.0, turn=0)
    D.record_file_versions(s, run=run, task=a, at=1.0, working_dir='D:/work/acme',
                           tools=[{'name': 'copilot_applyPatch', 'path': '{"file:///d%3A/work/acme/app/docs/svc/svc-latency-query-guide.md": {"$mid": 1}}'}])
    return s, t, a, b


def test_identifier_identical_and_typo():
    s, t, a, b = setup()
    ref = {'modes': ['named'], 'entities': [{'said': r'D:\work\acme\app\docs\svc\svc-latency-query-guide.md', 'type': 'identifier', 'role': 'target'}]}
    m = K.object_matches(s, ref, at=100.0, embed=stub_embed)
    assert m[0][0] == a and 'same identifier' in m[0][2]
    ref['entities'][0]['said'] = 'svc-latncy-query-guide.md'          # one character missing
    m = K.object_matches(s, ref, at=100.0, embed=stub_embed)
    assert m[0][0] == a and 'similar identifier' in m[0][2]


def test_quotas_keep_every_source():
    s, t, a, b = setup()
    ref = {'modes': ['continue'], 'entities': [{'said': 'svc-latency-query-guide.md', 'type': 'identifier', 'role': 'target'}]}
    c = dict(K.candidates(s, at=100.0, ref=ref, recent=[b], live=[b], embed=stub_embed))
    assert b in c and a in c and any(t.startswith('objects') for t in c[a])                  # a wrong "continue" still lets the named object in


def test_mentions_in_the_users_words_find_the_work():
    s, t, a, b = setup()
    K.record_mentions(s, b, {'entities': [{'said': 'region-x', 'resolved': 'external model routing in region-x', 'type': 'object', 'role': 'target'},
                                          {'said': 'TurnCoordinator.cs', 'resolved': 'TurnCoordinator.cs', 'type': 'identifier', 'role': 'target'}]}, turn=1, at=10.0)
    m = K.object_matches(s, {'modes': ['named'], 'entities': [{'said': 'TurnCoordinatr.cs', 'type': 'identifier', 'role': 'target'}]}, at=100.0, embed=stub_embed)
    assert m[0][0] == b and 'similar identifier' in m[0][2]
    kinds = {o['kind'] for o in K.object_index(s)}
    assert kinds == {'file', 'mention'}


if __name__ == '__main__':
    for name, f in list(globals().items()):
        if name.startswith('test_'):
            f(); print('PASS', name)
