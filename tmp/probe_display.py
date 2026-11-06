import sys
import ctypes
from importlib.metadata import version
print('Python:', sys.executable)
print('Remote session:', bool(ctypes.windll.user32.GetSystemMetrics(0x1000)))
print('PsychoPy:', version('psychopy'), 'pyglet:', version('pyglet'))
import pyglet
pyglet.options['shadow_window'] = False
from pyglet import gl
try:
    display = pyglet.display.get_display() if hasattr(pyglet, 'display') else pyglet.canvas.get_display()
    print('Screens:', [(s.x, s.y, s.width, s.height) for s in display.get_screens()])
    win = pyglet.window.Window(width=64, height=64, visible=False)
    try:
        print('GL vendor:', gl.gl_info.get_vendor())
        print('GL renderer:', gl.gl_info.get_renderer())
        print('GL version:', gl.gl_info.get_version())
    finally:
        win.close()
except Exception as exc:
    print('GL probe failed:', repr(exc))
