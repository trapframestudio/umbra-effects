"""
Drives the Umbra Effects Setup window like a player would, on a fake install (run on
a virtual display; test_setup.TestWindow does that):

    xvfb-run -a python3 dev/build_setup/gui_driver.py <fake ZGO folder> [screenshot.png]

Checks: it finds MO2 / profile / game by itself, experimental boxes start
off, the model list and estimate, Bake with progress, the up-to-date check
before and after a change, Cancel, Remove, and the messages for a wrong
profile and a wrong MO2 folder. Dialogs are answered automatically. Ends with
GUI DRIVER PASSED (exit 0) or a traceback (exit 1).
"""
import os
import shutil
import subprocess
import sys
import time

MOD = os.path.abspath(sys.argv[1])
SHOT = sys.argv[2] if len(sys.argv) > 2 else None
sys.path.insert(0, os.path.join(MOD, 'tools', 'zgo_setup'))
sys.path.insert(0, os.path.join(MOD, 'tools', 'zgo_baker'))

import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402

import setup_core as core  # noqa: E402
import setup_gui  # noqa: E402

ASKED, SHOWN = [], []
messagebox.askyesno = lambda title, msg, **k: ASKED.append(msg) or True
messagebox.showinfo = lambda title, msg, **k: SHOWN.append(('info', msg))
messagebox.showerror = lambda title, msg, **k: SHOWN.append(('error', msg))

root = tk.Tk()
log = core.Log(path=os.devnull)
app = setup_gui.App(root, MOD, None, log)


def wait(cond, what, timeout=300):
    t0 = time.time()
    while not cond():
        root.update()
        time.sleep(0.02)
        if time.time() - t0 > timeout:
            raise AssertionError('timed out waiting for: %s\nlog:\n%s' % (what, log.text()))
    for _ in range(5):
        root.update()


def text(w):
    return str(w.cget('text'))


def idle():
    return app.busy is None and app.job is None and app._plan_after is None


def shot(name):
    if SHOT and shutil.which('import'):
        root.update()
        p = SHOT.replace('.png', '_%s.png' % name)
        subprocess.run(['import', '-window', 'root', p], check=False)
        print('screenshot', p)


mo2 = os.path.dirname(os.path.dirname(MOD))
game = os.path.join(os.path.dirname(mo2), 'game')

# ---- found by itself; experimental parts off
wait(lambda: idle() and app.plan is not None and app.status is not None, 'first plan and check')
assert app.v_mo2.get() == mo2, app.v_mo2.get()
assert app.v_profile.get() == 'P', app.v_profile.get()
assert app.v_game.get() == game, app.v_game.get()
assert app.v_mod.get() == MOD
for k in ('experimental_caps', 'experimental_damage', 'experimental_props'):
    assert not app.v[k].get(), k
for k in ('caps', 'pieces', 'wounds', 'props'):
    assert app.v[k].get(), k
assert text(app.l_problems) == '', text(app.l_problems)
assert app.status.state == 'none' and text(app.l_head) == 'Not baked yet.', text(app.l_head)
# Tk 9 hands a Treeview's values back as strings, Tk 8.6 as numbers
rows = [(app.tree.item(i, 'text'), tuple(str(v) for v in app.tree.item(i, 'values'))) for i in app.tree.get_children()]
assert rows == [('Synth Models', ('3',))], rows
assert text(app.l_estimate).startswith('3 models from 1 source. About '), text(app.l_estimate)
assert 'b' not in app.b_remove.state() and 'disabled' in app.b_remove.state(), 'nothing to remove yet'
assert 'disabled' not in app.b_bake.state()
print('found MO2, profile P and the game; experimental off; 3 models listed')
shot('start')

# ---- bake (without props), progress to the end, then it checks by itself
app.v['props'].set(False)
app.v_jobs.set(2)
app.bake()
assert app.busy == 'bake' and 'disabled' not in app.b_cancel.state()
seen = []
wait(lambda: seen.append(float(app.progress['value'])) or app.job is None, 'the bake')
assert any(0 < v < 1000 for v in seen) or seen[-1] == 1000, seen[-10:]
assert SHOWN and SHOWN[-1][0] == 'info' and 'Baked 4 models' in SHOWN[-1][1], SHOWN
wait(lambda: idle() and app.status is not None and app.status.state == 'ok', 'the check after the bake')
assert text(app.l_head) == 'Your bake is up to date.', text(app.l_head)
assert 'disabled' not in app.b_remove.state()
wait(lambda: idle() and app.plan is not None and app.plan.models == 4, 'the new plan')
print('baked 4 models; the check says up to date')
shot('baked')

# ---- a mod changes a model
src = os.path.join(mo2, 'mods', 'Synth Models', 'gamedata', 'meshes', 'actors', 'synth', 'synth_a.ogf')
with open(src, 'ab') as f:
    f.write(b'\0')
app.status = None
app.check()
wait(lambda: idle() and app.status is not None, 'the check')
assert app.status.state == 'stale', app.status.text()
assert 'Mod "Synth Models" changed 1 model' in text(app.l_reasons), text(app.l_reasons)
print('a changed model is found')
shot('stale')

# ---- cancel at once: nothing changes
before = sorted(os.listdir(os.path.join(MOD, 'gamedata', 'meshes', 'actors', 'synth')))
n = len(SHOWN)
app.bake()
app.cancel()
wait(lambda: app.job is None, 'the cancelled bake')
assert len(SHOWN) == n, SHOWN[n:]
assert any('Cancelled' in l for _, l in log.lines), log.text()
assert sorted(os.listdir(os.path.join(MOD, 'gamedata', 'meshes', 'actors', 'synth'))) == before
wait(idle, 'idle after cancel')
print('cancel leaves the bake as it was')

# ---- remove
app.remove()
wait(lambda: app.job is None, 'remove')
wait(lambda: idle() and app.status is not None and app.status.state == 'none', 'the check after removing')
assert not os.path.exists(os.path.join(MOD, 'zgo_bake_report.json'))
assert 'disabled' in app.b_remove.state()
print('removed')

# ---- another profile (ZGO is not enabled there), then a wrong MO2 folder
app.v_profile.set('Other')
app.paths_changed()
wait(idle, 'plan for Other')
assert 'is not enabled in the MO2 profile "Other"' in text(app.l_problems), text(app.l_problems)
assert 'disabled' not in app.b_bake.state(), 'only a warning'
app.v_mo2.set(os.path.join(mo2, 'nope'))
app.paths_changed()
wait(idle, 'paths changed')
assert "Mod Organizer 2's folder is not set" in text(app.l_problems), text(app.l_problems)
assert 'disabled' in app.b_bake.state() and 'disabled' in app.b_check.state()
print('wrong profile / MO2 folder are explained')
shot('problems')

errors = [l for lv, l in log.lines if lv == 'error']
assert not errors, errors
app.closing = True
root.destroy()
print('GUI DRIVER PASSED')
