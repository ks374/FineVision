"""Editable degree targets and positive least-squares point weights."""
import math
import numpy as np

DEFAULT_POINTS = [dict(x_deg=0., y_deg=0., weight=1.),
                  dict(x_deg=-4., y_deg=0., weight=1.),
                  dict(x_deg=0., y_deg=3., weight=1.)]


def normalize_points(points):
    result = [{key: float(point[key]) for key in ('x_deg', 'y_deg', 'weight')}
              for point in points]
    if len(result) < 3:
        raise ValueError('At least 3 points are required / 至少保留3个点')
    if any(not math.isfinite(v) for p in result for v in p.values()):
        raise ValueError('Coordinates and weights must be finite / 坐标与权重必须为有限数')
    if any(p['weight'] <= 0 for p in result):
        raise ValueError('Weights must be positive / 权重必须大于0')
    if any(abs(p[k]) >= 90 for p in result for k in ('x_deg', 'y_deg')):
        raise ValueError('Target angles must be between -90 and 90 degrees')
    design = [[1., p['x_deg'], p['y_deg']] for p in result]
    if np.linalg.matrix_rank(design) < 3:
        raise ValueError('Points must not all lie on one line / 校准点不能全部共线')
    return result


def edit_points(points, validator, title='RAW calibration points / RAW校准点'):
    """Scrollable modal editor; Cancel returns None without activating hardware."""
    import tkinter as tk
    from tkinter import ttk, messagebox
    root = tk.Tk(); root.title(title); root.geometry('590x510')
    result = {'points': None}; rows = []
    ttk.Label(root, text='X、Y：相对屏幕中心的角度（右、上为正）。权重用于加权拟合。').pack(pady=10)
    holder = ttk.Frame(root); holder.pack(fill='both', expand=True, padx=12)
    canvas = tk.Canvas(holder, highlightthickness=0)
    scroll = ttk.Scrollbar(holder, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
    body = ttk.Frame(canvas); window = canvas.create_window((0, 0), window=body, anchor='nw')
    body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
    canvas.bind_all('<MouseWheel>', lambda e: canvas.yview_scroll(-int(e.delta/120), 'units'))
    def render():
        for child in body.winfo_children(): child.destroy()
        for col, label in enumerate(('#', 'X (deg)', 'Y (deg)', 'Weight / 权重', '')):
            ttk.Label(body, text=label).grid(row=0, column=col, padx=6, pady=5)
        for i, variables in enumerate(rows):
            ttk.Label(body, text=str(i+1)).grid(row=i+1, column=0)
            for j, var in enumerate(variables):
                ttk.Entry(body, textvariable=var, width=12).grid(row=i+1, column=j+1, padx=5, pady=4)
            ttk.Button(body, text='删除', command=lambda index=i: remove(index)).grid(row=i+1, column=4)
    def add(point=None):
        p = point or dict(x_deg=0., y_deg=0., weight=1.)
        rows.append([tk.StringVar(root, str(p[k])) for k in ('x_deg','y_deg','weight')]); render()
    def remove(index):
        if len(rows) <= 3:
            messagebox.showerror('Points', '至少保留3个点', parent=root); return
        rows.pop(index); render()
    def accept():
        try:
            ps = normalize_points([dict(zip(('x_deg','y_deg','weight'), [v.get() for v in row])) for row in rows])
            validator(ps)
        except (ValueError, TypeError, KeyError) as exc:
            messagebox.showerror('Invalid points / 点参数无效', str(exc), parent=root); return
        result['points'] = ps; close()
    def close():
        canvas.unbind_all('<MouseWheel>')
        root.destroy()
    controls = ttk.Frame(root); controls.pack(fill='x', padx=12, pady=12)
    ttk.Button(controls, text='+', width=4, command=add).pack(side='left')
    ttk.Button(controls, text='开始采集', command=accept).pack(side='right', padx=6)
    ttk.Button(controls, text='取消', command=close).pack(side='right')
    root.protocol('WM_DELETE_WINDOW', close)
    root.bind('<Escape>', lambda e: close())
    for point in points: add(point)
    root.mainloop()
    return result['points']
