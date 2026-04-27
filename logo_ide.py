#!/usr/bin/env python3
"""
Turtle Logo IDE
A graphical development environment for the Logo programming language.
Requires Python 3 + tkinter (standard library on Ubuntu: python3-tk).
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont
import threading
import queue
import time
import math
import os
from typing import Optional

from logo_interpreter import LogoInterpreter, LogoError


# --- Constants ----------------------------------------------------------------

APP_TITLE   = "Turtle Logo IDE"
CANVAS_W    = 600
CANVAS_H    = 600
EDITOR_W    = 480

# Syntax highlighting colours
SH = {
    'keyword':   '#0055aa',   # TO END
    'control':   '#8800aa',   # REPEAT IF IFELSE WHILE FOR FOREVER
    'motion':    '#007700',   # FORWARD RIGHT etc.
    'pen':       '#005555',   # PENUP SETPENCOLOR etc.
    'screen':    '#aa5500',   # CLEARSCREEN HOME etc.
    'output':    '#555500',   # PRINT SHOW TYPE
    'variable':  '#cc6600',   # :var
    'quoted':    '#aa3300',   # "word
    'number':    '#7700aa',
    'comment':   '#888888',
    'operator':  '#333333',
}

KEYWORDS_KEYWORD = {'TO', 'END', 'OUTPUT', 'OP', 'STOP', 'LOCAL', 'LOCALMAKE',
                    'MAKE', 'NAME'}
KEYWORDS_CONTROL = {'REPEAT', 'FOREVER', 'IF', 'IFELSE', 'IFTRUE', 'IFFALSE',
                    'IFT', 'IFF', 'WHILE', 'UNTIL', 'FOR', 'RUN'}
KEYWORDS_MOTION  = {'FORWARD', 'FD', 'BACKWARD', 'BACK', 'BK',
                    'RIGHT', 'RT', 'LEFT', 'LT',
                    'SETHEADING', 'SETH', 'HOME', 'SETXY', 'SETX', 'SETY', 'ARC'}
KEYWORDS_PEN     = {'PENUP', 'PU', 'PENDOWN', 'PD', 'PENSIZE', 'SETPENSIZE',
                    'SETPENCOLOR', 'SETPC', 'PC',
                    'SETFILLCOLOR', 'SETFC', 'FILL',
                    'SETBACKGROUND', 'SETBG', 'BG', 'SETBGCOLOR'}
KEYWORDS_SCREEN  = {'CLEARSCREEN', 'CS', 'CLEAN', 'HIDETURTLE', 'HT',
                    'SHOWTURTLE', 'ST', 'WRAP', 'WINDOW', 'FENCE'}
KEYWORDS_OUTPUT  = {'PRINT', 'PR', 'SHOW', 'TYPE', 'NEWLINE'}


# --- Canvas widget ------------------------------------------------------------

class TurtleCanvas(tk.Canvas):
    """Canvas that draws Logo turtle graphics."""

    TURTLE_SIZE = 13

    def __init__(self, parent, **kw):
        kw.setdefault('bg', 'white')
        kw.setdefault('width', CANVAS_W)
        kw.setdefault('height', CANVAS_H)
        super().__init__(parent, **kw)

        self._bg_color   = 'white'
        self._drawing    = []          # drawing commands (Logo coords) for redraw
        self._turtle_id  = None        # canvas item id for turtle shape
        self._last_turtle = (0, 0, 0, True)   # last known turtle state
        self._redrawing  = False       # True while _on_resize is replaying

        # Use fixed defaults; updated by <Configure> before any drawing occurs
        self._width  = CANVAS_W
        self._height = CANVAS_H

        self.bind('<Configure>', self._on_resize)

    # -- Coordinate mapping ---------------------------------------------------

    def _cx(self, lx: float) -> float:
        return self._width  / 2 + lx

    def _cy(self, ly: float) -> float:
        return self._height / 2 - ly

    # -- Public drawing API (called from IDE) ----------------------------------

    def handle(self, cmd, *args):
        """Dispatch a draw command from the interpreter."""
        if cmd == 'LINE':
            ox, oy, nx, ny, color, size = args
            x0, y0 = self._cx(ox), self._cy(oy)
            x1, y1 = self._cx(nx), self._cy(ny)
            self.create_line(x0, y0, x1, y1,
                             fill=color, width=size,
                             capstyle=tk.ROUND)
            if not self._redrawing:
                self._drawing.append(('LINE', ox, oy, nx, ny, color, size))
            self._bring_turtle_to_front()

        elif cmd == 'MOVE':
            if not self._redrawing:
                self._drawing.append(('MOVE', *args))

        elif cmd == 'ARC':
            lx, ly, heading, angle, radius, color, size = args
            if color is None:
                return
            cx, cy = self._cx(lx), self._cy(ly)
            steps = max(4, int(abs(angle)))
            rad0 = math.radians(heading - 90)
            x_prev = cx + math.cos(rad0) * radius
            y_prev = cy + math.sin(rad0) * radius
            for i in range(1, steps + 1):
                a = math.radians(heading - 90 + angle * i / steps)
                x_cur = cx + math.cos(a) * radius
                y_cur = cy + math.sin(a) * radius
                self.create_line(x_prev, y_prev, x_cur, y_cur,
                                 fill=color, width=size)
                x_prev, y_prev = x_cur, y_cur
            if not self._redrawing:
                self._drawing.append(('ARC', *args))
            self._bring_turtle_to_front()

        elif cmd == 'TURTLE':
            lx, ly, heading, visible = args
            self._last_turtle = (lx, ly, heading, visible)
            self._draw_turtle(lx, ly, heading, visible)

        elif cmd in ('CLEARSCREEN', 'CLEAN'):
            bg = args[0] if args else 'white'
            self._bg_color = bg
            self.configure(bg=bg)
            self.delete('all')
            if not self._redrawing:
                self._drawing.clear()
            self._turtle_id = None
            self._last_turtle = (0, 0, 0, True)
            self._draw_turtle(0, 0, 0, True)

        elif cmd == 'BACKGROUND':
            bg = args[0]
            self._bg_color = bg
            self.configure(bg=bg)

        elif cmd == 'FILL':
            pass  # flood fill not trivial in tkinter - skip

    def _draw_turtle(self, lx: float, ly: float, heading: float, visible: bool):
        if self._turtle_id is not None:
            self.delete(self._turtle_id)
            self._turtle_id = None

        if not visible:
            return

        cx, cy = self._cx(lx), self._cy(ly)
        s = self.TURTLE_SIZE
        h = math.radians(heading)

        tip_x  = cx + math.sin(h)       * s
        tip_y  = cy - math.cos(h)       * s
        left_x = cx + math.sin(h + 2.4) * s * 0.55
        left_y = cy - math.cos(h + 2.4) * s * 0.55
        right_x= cx + math.sin(h - 2.4) * s * 0.55
        right_y= cy - math.cos(h - 2.4) * s * 0.55

        self._turtle_id = self.create_polygon(
            tip_x, tip_y, left_x, left_y, right_x, right_y,
            fill='green2', outline='dark green', width=1,
            tags='turtle'
        )

    def _bring_turtle_to_front(self):
        if self._turtle_id:
            self.tag_raise(self._turtle_id)

    def _on_resize(self, event):
        """Redraw everything when the canvas is resized."""
        self._width  = event.width
        self._height = event.height
        self.delete('all')
        self._turtle_id = None
        self.configure(bg=self._bg_color)

        # Replay drawing commands using stored Logo coordinates
        self._redrawing = True
        try:
            for cmd in self._drawing:
                self.handle(*cmd)
        finally:
            self._redrawing = False

        # Restore turtle
        self._draw_turtle(*self._last_turtle)


# --- Code editor with line numbers --------------------------------------------

class CodeEditor(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)

        self._font = tkfont.Font(family='Courier', size=11)

        # Line number gutter
        self.lineno = tk.Text(
            self, width=4, state='disabled', takefocus=False,
            relief='flat', bd=0, bg='#f0f0f0', fg='#888888',
            font=self._font, cursor='arrow'
        )
        self.lineno.pack(side='left', fill='y')

        # Scrollbar
        self._vsb = ttk.Scrollbar(self, orient='vertical')
        self._vsb.pack(side='right', fill='y')

        # Main text area
        self.text = tk.Text(
            self, wrap='none', undo=True,
            font=self._font, relief='flat', bd=4,
            bg='#1e1e2e', fg='#cdd6f4',
            insertbackground='#cdd6f4',
            selectbackground='#45475a',
            tabs=(self._font.measure('    '),),
            yscrollcommand=self._on_text_scroll
        )
        self.text.pack(side='left', fill='both', expand=True)

        self._vsb.config(command=self._scroll_both)
        self.text.bind('<<Modified>>', self._on_modified)
        self.text.bind('<Key>', lambda e: self.after(1, self._update_linenos))
        self.text.bind('<Return>', lambda e: self.after(1, self._update_linenos))

        self._setup_tags()
        self._update_linenos()

    def _setup_tags(self):
        t = self.text
        t.tag_configure('keyword',  foreground='#89b4fa', font=self._font)
        t.tag_configure('control',  foreground='#cba6f7', font=self._font)
        t.tag_configure('motion',   foreground='#a6e3a1', font=self._font)
        t.tag_configure('pen',      foreground='#89dceb', font=self._font)
        t.tag_configure('screen',   foreground='#fab387', font=self._font)
        t.tag_configure('output',   foreground='#f9e2af', font=self._font)
        t.tag_configure('variable', foreground='#f38ba8', font=self._font)
        t.tag_configure('quoted',   foreground='#f9e2af', font=self._font)
        t.tag_configure('number',   foreground='#f2cdcd', font=self._font)
        t.tag_configure('comment',  foreground='#585b70',
                        font=tkfont.Font(family='Courier', size=11,
                                         slant='italic'))
        t.tag_configure('error_line', background='#3d1515')
        t.tag_configure('current_line', background='#2a2a3e')

    def _scroll_both(self, *args):
        self.text.yview(*args)
        self.lineno.yview(*args)

    def _on_text_scroll(self, first, last):
        self._vsb.set(first, last)
        self.lineno.yview_moveto(first)

    def _on_modified(self, _event):
        self.text.edit_modified(False)
        self._update_linenos()
        self._highlight()

    def _update_linenos(self):
        self.lineno.config(state='normal')
        self.lineno.delete('1.0', 'end')
        last_line = int(self.text.index('end-1c').split('.')[0])
        self.lineno.insert('end', '\n'.join(str(i) for i in range(1, last_line + 1)))
        self.lineno.config(state='disabled')

    def _highlight(self):
        t = self.text
        src = t.get('1.0', 'end')

        # Remove all tags
        for tag in ('keyword', 'control', 'motion', 'pen', 'screen',
                    'output', 'variable', 'quoted', 'number', 'comment'):
            t.tag_remove(tag, '1.0', 'end')

        import re
        # Comments
        for m in re.finditer(r';[^\n]*', src):
            t.tag_add('comment', f'1.0+{m.start()}c', f'1.0+{m.end()}c')

        # Quoted words
        for m in re.finditer(r'"[^ \t\r\n\[\]()]*', src):
            t.tag_add('quoted', f'1.0+{m.start()}c', f'1.0+{m.end()}c')

        # Variables
        for m in re.finditer(r':[A-Za-z_][A-Za-z0-9_.]*', src):
            t.tag_add('variable', f'1.0+{m.start()}c', f'1.0+{m.end()}c')

        # Numbers
        for m in re.finditer(r'\b-?\d+\.?\d*(?:[eE][+-]?\d+)?\b', src):
            t.tag_add('number', f'1.0+{m.start()}c', f'1.0+{m.end()}c')

        # Named keywords  (whole word, case insensitive)
        for m in re.finditer(r'\b([A-Za-z_?!][A-Za-z0-9_?!.]*)\b', src):
            word = m.group(1).upper()
            if word in KEYWORDS_KEYWORD:   tag = 'keyword'
            elif word in KEYWORDS_CONTROL: tag = 'control'
            elif word in KEYWORDS_MOTION:  tag = 'motion'
            elif word in KEYWORDS_PEN:     tag = 'pen'
            elif word in KEYWORDS_SCREEN:  tag = 'screen'
            elif word in KEYWORDS_OUTPUT:  tag = 'output'
            else:                          continue
            t.tag_add(tag, f'1.0+{m.start()}c', f'1.0+{m.end()}c')

    # -- Public helpers -------------------------------------------------------

    def get_code(self) -> str:
        return self.text.get('1.0', 'end-1c')

    def set_code(self, code: str):
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', code)
        self._update_linenos()
        self._highlight()

    def clear_error_marks(self):
        self.text.tag_remove('error_line', '1.0', 'end')

    def mark_error_line(self, lineno: int):
        if lineno > 0:
            self.text.tag_add('error_line', f'{lineno}.0', f'{lineno}.end')
            self.text.see(f'{lineno}.0')


# --- Console output pane ------------------------------------------------------

class ConsolePane(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._font = tkfont.Font(family='Courier', size=10)

        vsb = ttk.Scrollbar(self, orient='vertical')
        vsb.pack(side='right', fill='y')

        self.text = tk.Text(
            self, state='disabled', wrap='word', height=6,
            font=self._font,
            bg='#11111b', fg='#cdd6f4',
            relief='flat', bd=4,
            yscrollcommand=vsb.set
        )
        self.text.pack(fill='both', expand=True)
        vsb.config(command=self.text.yview)

        self.text.tag_configure('error',   foreground='#f38ba8')
        self.text.tag_configure('success', foreground='#a6e3a1')
        self.text.tag_configure('info',    foreground='#89dceb')

    def write(self, text: str, tag: str = ''):
        self.text.config(state='normal')
        if tag:
            self.text.insert('end', text, tag)
        else:
            self.text.insert('end', text)
        self.text.see('end')
        self.text.config(state='disabled')

    def clear(self):
        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        self.text.config(state='disabled')

    def write_error(self, text: str):
        self.write('[ERROR] ' + text + '\n', 'error')

    def write_success(self, text: str):
        self.write('[DONE]  ' + text + '\n', 'success')

    def write_info(self, text: str):
        self.write('[INFO]  ' + text + '\n', 'info')


# --- Example programs ---------------------------------------------------------

EXAMPLES = {
    "Square": """\
; Draw a simple square
REPEAT 4 [
  FORWARD 100
  RIGHT 90
]
""",

    "Star": """\
; A five-pointed star
REPEAT 5 [
  FORWARD 150
  RIGHT 144
]
""",

    "Spiral": """\
; Expanding square spiral
HIDETURTLE
FOR [i 1 80] [
  FORWARD :i * 2
  RIGHT 91
]
""",

    "Colourful Polygon": """\
; Rotating polygon with changing colours
HIDETURTLE
FOR [i 0 35] [
  SETPENCOLOR :i * 4
  REPEAT 6 [
    FORWARD 80
    RIGHT 60
  ]
  RIGHT 10
]
""",

    "Recursive Tree": """\
; Recursive tree using a procedure
TO TREE :SIZE
  IF :SIZE < 5 [STOP]
  FORWARD :SIZE
  LEFT 30
  TREE :SIZE * 0.7
  RIGHT 60
  TREE :SIZE * 0.7
  LEFT 30
  BACKWARD :SIZE
END

PENUP
SETY -150
PENDOWN
SETHEADING 0
SETPENCOLOR "green
TREE 80
""",

    "Koch Snowflake": """\
; Koch snowflake - fractal curve
TO KOCH :SIZE :DEPTH
  IF :DEPTH = 0 [
    FORWARD :SIZE
    STOP
  ]
  KOCH :SIZE / 3 :DEPTH - 1
  LEFT 60
  KOCH :SIZE / 3 :DEPTH - 1
  RIGHT 120
  KOCH :SIZE / 3 :DEPTH - 1
  LEFT 60
  KOCH :SIZE / 3 :DEPTH - 1
END

TO SNOWFLAKE :SIZE :DEPTH
  REPEAT 3 [
    KOCH :SIZE :DEPTH
    RIGHT 120
  ]
END

HIDETURTLE
PENUP
SETXY -120 80
PENDOWN
SETPENCOLOR "blue
SNOWFLAKE 240 4
""",

    "Spirograph": """\
; Spirograph-style pattern
HIDETURTLE
FOR [i 0 359] [
  PENUP
  HOME
  PENDOWN
  RIGHT :i
  SETPENCOLOR :i / 25
  FORWARD 150
  RIGHT 89
  FORWARD 150
]
""",

    "Hilbert Curve": """\
; Hilbert space-filling curve (order 3)
TO HILBERT :SIZE :RULE :DEPTH
  IF :DEPTH = 0 [STOP]
  IF :RULE = 1 [
    LEFT 90
    HILBERT :SIZE 2 :DEPTH - 1
    FORWARD :SIZE
    RIGHT 90
    HILBERT :SIZE 1 :DEPTH - 1
    FORWARD :SIZE
    HILBERT :SIZE 1 :DEPTH - 1
    RIGHT 90
    FORWARD :SIZE
    HILBERT :SIZE 2 :DEPTH - 1
    LEFT 90
  ]
  IF :RULE = 2 [
    RIGHT 90
    HILBERT :SIZE 1 :DEPTH - 1
    FORWARD :SIZE
    LEFT 90
    HILBERT :SIZE 2 :DEPTH - 1
    FORWARD :SIZE
    HILBERT :SIZE 2 :DEPTH - 1
    LEFT 90
    FORWARD :SIZE
    HILBERT :SIZE 1 :DEPTH - 1
    RIGHT 90
  ]
END

HIDETURTLE
PENUP
SETXY -120 -120
PENDOWN
SETPENCOLOR "purple
HILBERT 30 1 4
""",

    "Flower": """\
; Colourful flower petals
TO PETAL :SIZE
  REPEAT 2 [
    FORWARD :SIZE
    RIGHT 90
    FORWARD :SIZE
    RIGHT 90
  ]
END

HIDETURTLE
FOR [i 0 11] [
  SETPENCOLOR :i
  PETAL 60
  RIGHT 30
]
""",
}


# --- Main IDE window ----------------------------------------------------------

class LogoIDE(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry('1180x720')
        self.minsize(800, 540)

        self._current_file: Optional[str] = None
        self._modified = False
        self._running  = False

        # Thread / queue for async execution
        self._draw_queue: queue.Queue = queue.Queue()
        self._exec_thread: threading.Thread | None = None

        # Speed: seconds of sleep per draw call (0 = max speed)
        self._speed = tk.DoubleVar(value=0.0)

        # Build interpreter
        self._interp = LogoInterpreter(
            draw_callback=self._on_draw,
            print_callback=self._on_print
        )

        self._build_ui()
        self._build_menus()
        self._load_welcome()

        # Start queue processor
        self._process_queue()

        self.protocol('WM_DELETE_WINDOW', self._on_close)

    # -- UI construction ------------------------------------------------------

    def _build_ui(self):
        # -- Toolbar ---------------------------------------------------------
        toolbar = tk.Frame(self, bd=1, relief='raised', bg='#313244')
        toolbar.pack(side='top', fill='x')

        btn_style = dict(bg='#45475a', fg='#cdd6f4', activebackground='#585b70',
                         activeforeground='white', relief='flat', padx=8, pady=4,
                         font=('Sans', 10))

        tk.Button(toolbar, text='New',   command=self._cmd_new,  **btn_style).pack(side='left', padx=2, pady=3)
        tk.Button(toolbar, text='Open',  command=self._cmd_open, **btn_style).pack(side='left', padx=2, pady=3)
        tk.Button(toolbar, text='Save',  command=self._cmd_save, **btn_style).pack(side='left', padx=2, pady=3)

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)

        self._btn_run  = tk.Button(toolbar, text='[ Run ]',  command=self._cmd_run,
                                   bg='#a6e3a1', fg='#1e1e2e', activebackground='#94e2d5',
                                   relief='flat', padx=10, pady=4,
                                   font=('Sans', 10, 'bold'))
        self._btn_run.pack(side='left', padx=2, pady=3)

        self._btn_stop = tk.Button(toolbar, text='[ Stop ]', command=self._cmd_stop,
                                   bg='#f38ba8', fg='#1e1e2e', activebackground='#eba0ac',
                                   relief='flat', padx=10, pady=4,
                                   font=('Sans', 10, 'bold'), state='disabled')
        self._btn_stop.pack(side='left', padx=2, pady=3)

        tk.Button(toolbar, text='Clear Canvas', command=self._cmd_clear, **btn_style).pack(side='left', padx=2, pady=3)

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)

        tk.Label(toolbar, text='Speed:', bg='#313244', fg='#cdd6f4',
                 font=('Sans', 10)).pack(side='left')
        spd = ttk.Scale(toolbar, from_=0.0, to=0.05, variable=self._speed,
                        orient='horizontal', length=120)
        spd.pack(side='left', padx=4)
        tk.Label(toolbar, text='Slow', bg='#313244', fg='#888888',
                 font=('Sans', 9)).pack(side='left')

        # Status bar (right side of toolbar)
        self._status_var = tk.StringVar(value='Ready')
        tk.Label(toolbar, textvariable=self._status_var,
                 bg='#313244', fg='#a6adc8', font=('Mono', 9)).pack(side='right', padx=8)

        # -- Main paned window ------------------------------------------------
        paned = tk.PanedWindow(self, orient='horizontal', sashwidth=5,
                               bg='#181825', sashrelief='flat')
        paned.pack(fill='both', expand=True)

        # -- Left: editor + console -------------------------------------------
        left_frame = tk.Frame(paned, bg='#1e1e2e')
        paned.add(left_frame, minsize=300, width=EDITOR_W)

        editor_label = tk.Label(left_frame, text=' Editor',
                                bg='#313244', fg='#a6adc8',
                                font=('Sans', 10), anchor='w')
        editor_label.pack(fill='x')

        self._editor = CodeEditor(left_frame, bg='#1e1e2e')
        self._editor.pack(fill='both', expand=True)

        console_label = tk.Label(left_frame, text=' Console Output',
                                 bg='#313244', fg='#a6adc8',
                                 font=('Sans', 10), anchor='w')
        console_label.pack(fill='x')

        self._console = ConsolePane(left_frame, bg='#11111b')
        self._console.pack(fill='x')

        # -- Right: canvas ----------------------------------------------------
        right_frame = tk.Frame(paned, bg='#181825')
        paned.add(right_frame, minsize=300)

        canvas_label = tk.Label(right_frame, text=' Canvas',
                                bg='#313244', fg='#a6adc8',
                                font=('Sans', 10), anchor='w')
        canvas_label.pack(fill='x')

        self._canvas = TurtleCanvas(right_frame, bg='white',
                                    highlightthickness=0)
        self._canvas.pack(fill='both', expand=True, padx=4, pady=4)

        # Show turtle position on mouse move
        self._canvas.bind('<Motion>', self._on_canvas_mouse)

    def _build_menus(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # File
        m = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label='File', menu=m)
        m.add_command(label='New',        accelerator='Ctrl+N', command=self._cmd_new)
        m.add_command(label='Open...',      accelerator='Ctrl+O', command=self._cmd_open)
        m.add_command(label='Save',       accelerator='Ctrl+S', command=self._cmd_save)
        m.add_command(label='Save As...',                         command=self._cmd_save_as)
        m.add_separator()
        m.add_command(label='Save Canvas as PNG...', accelerator='Ctrl+Shift+P', command=self._cmd_save_canvas_png)
        m.add_separator()
        m.add_command(label='Exit',                             command=self._on_close)

        # Edit
        m = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label='Edit', menu=m)
        m.add_command(label='Undo',   accelerator='Ctrl+Z', command=lambda: self._editor.text.event_generate('<<Undo>>'))
        m.add_command(label='Redo',   accelerator='Ctrl+Y', command=lambda: self._editor.text.event_generate('<<Redo>>'))
        m.add_separator()
        m.add_command(label='Cut',    accelerator='Ctrl+X', command=lambda: self._editor.text.event_generate('<<Cut>>'))
        m.add_command(label='Copy',   accelerator='Ctrl+C', command=lambda: self._editor.text.event_generate('<<Copy>>'))
        m.add_command(label='Paste',  accelerator='Ctrl+V', command=lambda: self._editor.text.event_generate('<<Paste>>'))
        m.add_separator()
        m.add_command(label='Select All', accelerator='Ctrl+A',
                      command=lambda: self._editor.text.event_generate('<<SelectAll>>'))
        m.add_command(label='Clear Console', command=self._console.clear)

        # Run
        m = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label='Run', menu=m)
        m.add_command(label='Run Program', accelerator='F5',   command=self._cmd_run)
        m.add_command(label='Stop',        accelerator='F6',   command=self._cmd_stop)
        m.add_command(label='Clear Canvas',accelerator='F7',   command=self._cmd_clear)
        m.add_separator()
        m.add_command(label='Reset Everything', command=self._cmd_reset)

        # Examples
        m = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label='Examples', menu=m)
        for name in EXAMPLES:
            m.add_command(label=name,
                          command=lambda n=name: self._load_example(n))

        # Help
        m = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label='Help', menu=m)
        m.add_command(label='Logo Command Reference', command=self._show_help)
        m.add_command(label='About',                  command=self._show_about)

        # Keyboard shortcuts
        self.bind('<F5>',      lambda e: self._cmd_run())
        self.bind('<F6>',      lambda e: self._cmd_stop())
        self.bind('<F7>',      lambda e: self._cmd_clear())
        self.bind('<Control-n>', lambda e: self._cmd_new())
        self.bind('<Control-o>', lambda e: self._cmd_open())
        self.bind('<Control-s>', lambda e: self._cmd_save())
        self.bind('<Control-Shift-P>', lambda e: self._cmd_save_canvas_png())

    # -- Welcome / examples ---------------------------------------------------

    def _load_welcome(self):
        welcome = """\
; --------------------------------------------------------------
;  Welcome to Turtle Logo IDE!
;
;  Press F5 or click [ Run ] to execute the code.
;  Browse the Examples menu for more programs.
; --------------------------------------------------------------

; Koch snowflake
TO KOCH :SIZE :DEPTH
  IF :DEPTH = 0 [FORWARD :SIZE STOP]
  KOCH :SIZE / 3 :DEPTH - 1
  LEFT 60
  KOCH :SIZE / 3 :DEPTH - 1
  RIGHT 120
  KOCH :SIZE / 3 :DEPTH - 1
  LEFT 60
  KOCH :SIZE / 3 :DEPTH - 1
END

HIDETURTLE
SETPENCOLOR "blue
PENUP  SETXY -140 60  PENDOWN
REPEAT 3 [KOCH 280 4  RIGHT 120]
"""
        self._editor.set_code(welcome)

    def _load_example(self, name: str):
        if self._modified:
            if not messagebox.askyesno('Unsaved changes',
                                       'Discard current changes and load example?'):
                return
        self._editor.set_code(EXAMPLES[name])
        self._current_file = None
        self._set_modified(False)
        self._console.clear()
        self.title(f'{name} - {APP_TITLE}')

    # -- Interpreter callbacks (called from worker thread) --------------------

    def _on_draw(self, *args):
        """Put a draw command into the queue. Called from interpreter thread."""
        self._draw_queue.put(args)
        # Speed throttle
        delay = self._speed.get()
        if delay > 0:
            time.sleep(delay)

    def _on_print(self, text: str):
        """Put a print event into the queue."""
        self._draw_queue.put(('__PRINT__', text))

    # -- Queue processor (runs on main thread via after()) --------------------

    def _process_queue(self):
        try:
            for _ in range(200):          # process up to 200 items per tick
                item = self._draw_queue.get_nowait()
                if item[0] == '__DONE__':
                    error = item[1]
                    self._on_exec_done(error)
                elif item[0] == '__PRINT__':
                    self._console.write(item[1])
                else:
                    try:
                        self._canvas.handle(*item)
                    except tk.TclError as e:
                        # Tkinter rejected a value (e.g. unknown colour name).
                        # Stop execution and show a friendly message in the
                        # console instead of crashing the callback chain.
                        self._interp.stop()
                        self._on_exec_done(f"Display error: {e}")
        except queue.Empty:
            pass
        self.after(16, self._process_queue)  # ~60 fps

    # -- Execution ------------------------------------------------------------

    def _cmd_run(self):
        if self._running:
            return
        code = self._editor.get_code()
        if not code.strip():
            return
        self._editor.clear_error_marks()
        self._console.clear()

        # Reset turtle to origin and clear canvas for a fresh run
        t = self._interp.turtle
        t.x = t.y = 0.0
        t.heading = 0.0
        t.pen_down = True
        t.visible = True
        self._canvas.handle('CLEARSCREEN', t.bg_color)

        self._console.write_info('Running...')
        self._set_running(True)
        self._exec_thread = threading.Thread(
            target=self._run_in_thread, args=(code,), daemon=True)
        self._exec_thread.start()

    def _run_in_thread(self, code: str):
        error = self._interp.run(code)
        self._draw_queue.put(('__DONE__', error))

    def _on_exec_done(self, error: Optional[str]):
        self._set_running(False)
        if error:
            self._console.write_error(error)
            # Try to highlight error line
            import re
            m = re.search(r'line (\d+)', error)
            if m:
                self._editor.mark_error_line(int(m.group(1)))
        else:
            self._console.write_success('Done.')

    def _cmd_stop(self):
        self._interp.stop()

    def _cmd_clear(self):
        self._interp.turtle.x = 0
        self._interp.turtle.y = 0
        self._interp.turtle.heading = 0
        self._canvas.handle('CLEARSCREEN', self._interp.turtle.bg_color)

    def _cmd_reset(self):
        self._interp.reset()
        self._canvas.handle('CLEARSCREEN', 'white')
        self._console.write_info('Interpreter reset (variables and procedures cleared).')

    def _set_running(self, state: bool):
        self._running = state
        self._btn_run.config(state='disabled' if state else 'normal')
        self._btn_stop.config(state='normal'   if state else 'disabled')
        self._status_var.set('Running...' if state else 'Ready')

    # -- File operations ------------------------------------------------------

    def _cmd_new(self):
        if self._modified:
            if not messagebox.askyesno('Unsaved changes',
                                       'Discard current changes?'):
                return
        self._editor.set_code('')
        self._current_file = None
        self._set_modified(False)
        self.title(APP_TITLE)

    def _cmd_open(self):
        if self._modified:
            if not messagebox.askyesno('Unsaved changes',
                                       'Discard current changes and open file?'):
                return
        path = filedialog.askopenfilename(
            defaultextension='.logo',
            filetypes=[('Logo files', '*.logo *.lgo *.txt'), ('All files', '*.*')],
            initialdir=os.path.expanduser('~')
        )
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self._editor.set_code(f.read())
                self._current_file = path
                self._set_modified(False)
                self.title(f'{os.path.basename(path)} - {APP_TITLE}')
            except OSError as e:
                messagebox.showerror('Open failed', str(e))

    def _cmd_save(self):
        if self._current_file:
            self._write_file(self._current_file)
        else:
            self._cmd_save_as()

    def _cmd_save_as(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.logo',
            filetypes=[('Logo files', '*.logo'), ('All files', '*.*')],
            initialdir=os.path.expanduser('~')
        )
        if path:
            self._write_file(path)
            self._current_file = path
            self.title(f'{os.path.basename(path)} - {APP_TITLE}')

    def _write_file(self, path: str):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._editor.get_code())
            self._set_modified(False)
            self._console.write_info(f'Saved to {path}')
        except OSError as e:
            messagebox.showerror('Save failed', str(e))

    def _cmd_save_canvas_png(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.png',
            filetypes=[('PNG image', '*.png'), ('All files', '*.*')],
            initialdir=os.path.expanduser('~'),
            title='Save Canvas as PNG',
        )
        if not path:
            return
        try:
            import io
            from PIL import Image
            ps = self._canvas.postscript(colormode='color')
            img = Image.open(io.BytesIO(ps.encode('latin-1')))
            img.save(path, 'PNG')
            self._console.write_info(f'Canvas saved to {path}')
        except Exception as e:
            messagebox.showerror('Save PNG failed', str(e))

    def _set_modified(self, val: bool):
        self._modified = val

    # -- Status bar updates ---------------------------------------------------

    def _on_canvas_mouse(self, event):
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        lx = event.x - w / 2
        ly = h / 2 - event.y
        self._status_var.set(
            f'Canvas ({lx:.0f}, {ly:.0f})  '
            f'Turtle ({self._interp.turtle.x:.1f}, {self._interp.turtle.y:.1f})  '
            f'Heading {self._interp.turtle.heading:.1f} deg'
        )

    # -- Help / About ---------------------------------------------------------

    def _show_help(self):
        win = tk.Toplevel(self)
        win.title('Logo Command Reference')
        win.geometry('660x520')

        txt = tk.Text(win, wrap='word', font=('Courier', 10),
                      bg='#1e1e2e', fg='#cdd6f4', relief='flat', bd=8)
        vsb = ttk.Scrollbar(win, command=txt.yview)
        txt.config(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        txt.pack(fill='both', expand=True)

        HELP_TEXT = """\
TURTLE MOTION
  FORWARD n  (FD n)       Move forward n steps
  BACKWARD n (BK n)       Move backward n steps
  RIGHT n    (RT n)       Turn right n degrees
  LEFT n     (LT n)       Turn left n degrees
  SETHEADING n (SETH n)   Set heading to n degrees (0=North)
  HOME                    Move to centre, heading 0
  SETXY x y               Jump to position (x, y)
  SETX x                  Set x coordinate
  SETY y                  Set y coordinate
  ARC angle radius        Draw arc of given angle/radius

PEN CONTROL
  PENUP   (PU)            Lift pen (stop drawing)
  PENDOWN (PD)            Put pen down (start drawing)
  PENSIZE n               Set pen width to n pixels
  SETPENCOLOR c  (SETPC c, PC c)
                          Set colour: name, number 0-255, or [r g b]
  SETFILLCOLOR c (SETFC c)
  SETBACKGROUND c (SETBG c)
                          Colour number 0-255 follows the xterm-256 palette:
                           0-15   system colours (0=black 15=white)
                           16-231 6x6x6 RGB cube
                           232-255 greyscale ramp

TURTLE VISIBILITY
  HIDETURTLE (HT)         Hide the turtle
  SHOWTURTLE (ST)         Show the turtle

SCREEN
  CLEARSCREEN (CS)        Clear screen, home turtle
  CLEAN                   Clear screen, keep turtle position

VARIABLES
  MAKE "name value        Set variable   (e.g. MAKE "x 5)
  :name                   Get variable   (e.g. FORWARD :x)
  LOCAL "name             Declare local variable
  LOCALMAKE "name value   Declare and set local

CONTROL FLOW
  REPEAT n [block]
  FOREVER [block]
  IF condition [block]
  IFELSE condition [true] [false]
  WHILE [condition] [body]
  UNTIL [condition] [body]
  FOR [var start end] [body]
  FOR [var start end step] [body]

PROCEDURES
  TO name :param1 :param2
    ...body...
  END

  OUTPUT value            Return value from procedure (OP value)
  STOP                    Exit procedure without returning

OUTPUT
  PRINT value  (PR value) Print value + newline
  TYPE value              Print value (no newline)
  SHOW value              Print value + newline (same as PRINT)

MATH REPORTERS
  SUM a b       DIFFERENCE a b   PRODUCT a b   QUOTIENT a b
  REMAINDER a b POWER a b        MINUS n        ABS n
  SQRT n        SIN n   COS n   TAN n   ARCTAN n
  INT n         ROUND n  FLOOR n  CEILING n
  MAX a b       MIN a b          RANDOM n       PI

COMPARISON / LOGIC
  EQUAL? a b    LESS? a b    GREATER? a b
  AND a b       OR a b       NOT a

INFIX OPERATORS  (use spaces around them)
  + - * /   = < > <= >= <>

LIST / WORD
  FIRST v   LAST v   BUTFIRST v (BF)   BUTLAST v (BL)
  COUNT v   ITEM n v   MEMBER item v
  LIST a b  SENTENCE a b (SE)   FPUT item list   LPUT item list
  WORD a b

TYPE PREDICATES
  NUMBER? v   WORD? v   LIST? v   EMPTY? v   ZERO? v

TURTLE STATE REPORTERS
  XCOR   YCOR   HEADING   PENDOWNP

COMMENTS
  ; This is a comment
"""
        txt.insert('1.0', HELP_TEXT)
        txt.config(state='disabled')

    def _show_about(self):
        messagebox.showinfo(
            'About Turtle Logo IDE',
            f'{APP_TITLE}\n\n'
            'A Logo language interpreter and IDE built with Python + tkinter.\n\n'
            'Supports a substantial subset of UCBLogo / MSWLogo:\n'
            '- Turtle graphics\n'
            '- User-defined recursive procedures\n'
            '- Variables, loops, conditionals\n'
            '- Syntax highlighting\n'
            '- Multiple example programs\n'
        )

    def _on_close(self):
        if self._modified:
            if not messagebox.askyesno('Quit', 'Discard unsaved changes and quit?'):
                return
        self.destroy()


# --- Entry point --------------------------------------------------------------

def main():
    app = LogoIDE()
    app.mainloop()


if __name__ == '__main__':
    main()
