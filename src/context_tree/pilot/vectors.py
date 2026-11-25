"""Embedding vectors kept on disk, so that CTM's object candidates (thousands of names after an import) are not
recomputed after every restart. embed(texts) returns vectors in order, computing only the missing ones."""
import hashlib
import sqlite3
import struct
import threading


class VectorCache:
    def __init__(self, path, compute=None):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute('create table if not exists v (h text primary key, n integer, data blob)')
        self.lock = threading.Lock()
        self.compute = compute
        self.mem = {}

    @staticmethod
    def _h(t):
        return hashlib.sha1(t.encode('utf-8')).hexdigest()

    def embed(self, texts):
        if self.compute is None:
            from context_tree.common import llm as base
            self.compute = base.embeddings
        out = {}
        need = []
        with self.lock:
            for t in dict.fromkeys(texts):
                if t in self.mem: out[t] = self.mem[t]; continue
                r = self.db.execute('select n, data from v where h=?', (self._h(t),)).fetchone()
                if r: out[t] = self.mem[t] = list(struct.unpack(f'{r[0]}f', r[1]))
                else: need.append(t)
        for i in range(0, len(need), 96):
            part = need[i:i + 96]
            vecs = self.compute(part)
            with self.lock:
                for t, v in zip(part, vecs):
                    out[t] = self.mem[t] = list(v)
                    self.db.execute('insert or replace into v values(?,?,?)', (self._h(t), len(v), struct.pack(f'{len(v)}f', *v)))
                self.db.commit()
        return [out[t] for t in texts]
