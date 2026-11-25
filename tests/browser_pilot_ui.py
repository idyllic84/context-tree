"""Browser check of the pilot page (tree view, menus, dialogs, pinning, drag and drop with undo).

Not part of the offline suite: it needs Microsoft Edge and Playwright (pip install playwright; it drives the installed Edge),
and it changes data (moves a node and moves it back, pins and unpins). Run it only against a copy:
    python -m context_tree.pilot --root <copy of a CTM directory> --port 8799
    python tests/browser_pilot_ui.py            # screenshots go to the directory in CTM_UI_SHOTS (default: a temp dir)
"""
import os
import tempfile
import json, sys, time, urllib.request
from playwright.sync_api import sync_playwright
BASE = os.environ.get('CTM_UI_BASE', 'http://127.0.0.1:8799')
SHOTS = os.environ.get('CTM_UI_SHOTS') or tempfile.mkdtemp(prefix='ctm-ui-')
SHOTS = SHOTS.rstrip('/') + '/'
os.makedirs(SHOTS, exist_ok=True)
api = lambda p: json.load(urllib.request.urlopen(BASE + p))
results = []
def check(name, ok, info=''):
    results.append((name, bool(ok))); print(('PASS ' if ok else 'FAIL ') + name + (('  ' + str(info)) if info else ''), flush=True)
with sync_playwright() as p:
    b = p.chromium.launch(channel='msedge', headless=True)
    pg = b.new_page(viewport={'width': 1500, 'height': 900})
    errors = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    pg.goto(BASE); pg.wait_for_selector('#tree .ti[data-id^="N"]')
    pg.evaluate("localStorage.clear()"); pg.reload(); pg.wait_for_selector('#tree .ti[data-id^="N"]')
    check('an empty conversation says how it is used', pg.locator('#conv .hint').count() == 1 or pg.locator('#conv .it:not(.notice)').count() > 0)
    w0 = pg.evaluate("document.querySelector('#right').getBoundingClientRect().width")
    bx = pg.locator('#split2').bounding_box(); pg.mouse.move(bx['x'] + 2, bx['y'] + 300); pg.mouse.down(); pg.mouse.move(bx['x'] - 80, bx['y'] + 300, steps=4); pg.mouse.up()
    w1 = pg.evaluate("document.querySelector('#right').getBoundingClientRect().width")
    check('the right panel widens with its divider', w1 > w0 + 40, (round(w0), round(w1)))
    pg.locator('#split2').dblclick(); time.sleep(0.1)
    check('double-click restores the right panel', abs(pg.evaluate("document.querySelector('#right').getBoundingClientRect().width") - w0) < 2)
    check('no buttons inside tree rows', pg.locator('#tree .ti button').count() == 0)
    first = pg.locator('#tree .ti[data-id^="N"]').first
    first.hover(); time.sleep(0.2)
    check('hover shows no toolbar', pg.locator('#tree .ti button, #tree .acts').count() == 0)
    sel0 = api('/api/tree')['selection']
    first.click(); pg.wait_for_selector('#panel .actbar')
    nid = first.get_attribute('data-id')
    check('click opens the page with an action bar', pg.locator('#panel h3').inner_text().strip() != '')
    check('click marks the row viewed', first.get_attribute('aria-selected') == 'true')
    check('click does not change where messages go', api('/api/tree')['selection'] == sel0, sel0)
    pg.screenshot(path=SHOTS + '1-main.png')
    first.click(button='right'); pg.wait_for_selector('.menu')
    items = pg.locator('.menu button').all_inner_texts()
    check('context menu has the node actions', any('Move to' in x for x in items) and any('Rename' in x for x in items), items)
    pg.screenshot(path=SHOTS + '2-context-menu.png')
    pg.keyboard.press('Escape'); time.sleep(0.1)
    check('Esc closes the menu', pg.locator('.menu').count() == 0)
    # keyboard: a parent row expands and collapses with the arrows
    parent = pg.locator('#tree .ti[aria-expanded]').first
    pid = parent.get_attribute('data-id')
    parent.focus()
    if parent.get_attribute('aria-expanded') == 'true': pg.keyboard.press('ArrowLeft'); time.sleep(0.2)
    check('ArrowLeft collapses', pg.locator(f'#ti-{pid}').get_attribute('aria-expanded') == 'false')
    pg.keyboard.press('ArrowRight'); time.sleep(0.2)
    check('ArrowRight expands', pg.locator(f'#ti-{pid}').get_attribute('aria-expanded') == 'true')
    pg.keyboard.press('ArrowDown'); time.sleep(0.1)
    fid = pg.evaluate("document.activeElement.dataset.id")
    check('ArrowDown moves focus to the first child', fid and api('/api/tree') and fid != pid, fid)
    old = pg.locator(f'#ti-{fid} .title').inner_text()
    pg.keyboard.press('F2'); pg.wait_for_selector('#tree input.rename')
    check('F2 starts an inline rename', pg.locator('#tree input.rename').count() == 1)
    pg.keyboard.press('Escape'); time.sleep(0.3)
    check('Esc cancels the rename', pg.locator(f'#ti-{fid} .title').inner_text() == old)
    # filter
    pg.keyboard.press('/'); pg.keyboard.type(os.environ.get('CTM_UI_FILTER') or old[:2] or 'a'); time.sleep(0.3)
    n_rows = pg.locator('#tree .ti').count()
    check('filter narrows the tree and marks matches', pg.locator('#tree mark').count() > 0 and n_rows > 1, n_rows)
    pg.screenshot(path=SHOTS + '3-filter.png')
    pg.keyboard.press('Escape'); time.sleep(0.2)
    # move picker from the action bar
    first.click(); pg.wait_for_selector('#panel .actbar')
    pg.click('#panel [data-act="move"]'); pg.wait_for_selector('dialog[open] .picklist')
    pg.keyboard.type(os.environ.get('CTM_UI_FILTER') or old[:2] or 'a'); time.sleep(0.2)
    check('move picker lists and filters works', pg.locator('dialog[open] .pick').count() > 0)
    pg.screenshot(path=SHOTS + '4-move-picker.png')
    pg.keyboard.press('Escape'); time.sleep(0.2)
    check('Esc closes the picker without a change', pg.locator('dialog[open]').count() == 0)
    # status menu
    pg.click('#panel [data-act="status"]'); pg.wait_for_selector('.menu')
    check('status menu marks the current status', any(x.startswith('✓') for x in pg.locator('.menu button').all_inner_texts()))
    pg.keyboard.press('Escape')
    # pin and unpin
    pg.click('#panel [data-act="pin"]'); time.sleep(0.6)
    check('pin: next message goes here', api('/api/tree')['selection'] == nid and pg.locator('#target .chip.pinned').count() == 1)
    check('pinned row shows a badge', pg.locator(f'#ti-{nid} .badge.pin').count() == 1)
    pg.screenshot(path=SHOTS + '5-pinned.png')
    pg.click('#target [data-unpin]'); time.sleep(0.6)
    check('unpin', api('/api/tree')['selection'] is None)
    # new-work form opens and cancels
    pg.click('#btn-new'); pg.wait_for_selector('dialog[open] form')
    check('new work opens a form', pg.locator('dialog[open] input[name="title"]').count() == 1)
    pg.screenshot(path=SHOTS + '6-new-form.png')
    pg.keyboard.press('Escape'); time.sleep(0.2)
    # drag a leaf onto another work, then undo from the toast
    leaf = pg.locator('#tree .ti[data-id^="N"]:not([aria-expanded])').first
    lid = leaf.get_attribute('data-id')
    before = [n for n in api('/api/tree')['nodes'] if n['id'] == lid][0]['parent']
    target = pg.locator(f'#tree .ti[data-id^="N"][aria-level="1"]:not([data-id="{before}"])').first
    tid = target.get_attribute('data-id')
    leaf.drag_to(target); time.sleep(0.8)
    after = [n for n in api('/api/tree')['nodes'] if n['id'] == lid][0]['parent']
    check('drag and drop moves the work', after == tid, (before, after, tid))
    pg.screenshot(path=SHOTS + '7-after-drop.png')
    pg.click('.toast button'); time.sleep(0.8)
    back = [n for n in api('/api/tree')['nodes'] if n['id'] == lid][0]['parent']
    check('undo moves it back', back == before, back)
    # the root row opens the global page
    pg.click('#ti-ROOT'); pg.wait_for_selector('#panel [data-act="addpref"]')
    check('root row opens the global page', True)
    check('no page errors', not errors, errors[:3])
    b.close()
print(f"{sum(ok for _, ok in results)}/{len(results)} passed")
