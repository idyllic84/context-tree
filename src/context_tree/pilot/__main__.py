"""Start the pilot: python -m context_tree.pilot --root <CTM directory> [--port 8765] [--open]

CTM decides each work's working directory; works that belong to no project get a scratch directory under --root.
The CTM directory (--root) holds the memory, the conversation, the event records, the pi sessions and scratch work; the
same root keeps CTM's memory across days. (Later `ctm` becomes a global command whose root is the directory it starts in.)"""
import argparse
import os
import time
import webbrowser
from pathlib import Path

from .app import Pilot
from .server import serve


def main():
    ap = argparse.ArgumentParser(prog='python -m context_tree.pilot')
    ap.add_argument('--root', required=True,
                    help='the CTM directory: memory, records, executor sessions, scratch work (keep the same one to keep the memory)')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--open', action='store_true', help='open the page in the browser')
    a = ap.parse_args()
    pilot = Pilot(a.root)
    (Path(a.root) / 'server.pid').write_text(str(os.getpid()), encoding='utf-8')   # stop by this Windows pid; executors exit with it
    httpd = serve(pilot, port=a.port)
    url = f'http://127.0.0.1:{a.port}/'
    print(f'CTM pilot: {url}  CTM directory: {a.root}', flush=True)
    if a.open: webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        pilot.shutdown()


if __name__ == '__main__':
    main()
