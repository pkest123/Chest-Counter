"""Local screen-only chest notification counter. No game process access."""
import csv
import ctypes
from ctypes import wintypes
import json
import queue
import os
import threading
import time
import sys
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import cv2
import mss
import numpy as np
from PIL import Image, ImageTk
from detection import EventGate, chest_notification, automatic_notification, locate_notifications
from notification_focus import FocusBuffer, focus_box
from usage import UsageMonitor

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('LOCALAPPDATA', str(ROOT))) / 'FortniteChestCounter' if getattr(__import__('sys'), 'frozen', False) else ROOT / 'data'
DATA.mkdir(exist_ok=True)
BG, PANEL, TEXT, MUTED, ACCENT = '#101522', '#1a2234', '#edf2ff', '#9aaac5', '#64e4ba'
cv2.setNumThreads(1)


def make_ocr():
    from rapidocr_onnxruntime import RapidOCR
    # Restore the original high-resolution OCR path, before capture optimizations.
    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,
                    det_limit_side_len=1600, det_limit_type='min')


def match_score(frame, template):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    best = 0.0
    for scale in (.9, 1.0, 1.1):
        sample = cv2.resize(template, None, fx=scale, fy=scale)
        h, w = sample.shape
        if h <= gray.shape[0] and w <= gray.shape[1]:
            value = cv2.minMaxLoc(cv2.matchTemplate(gray, sample, cv2.TM_CCOEFF_NORMED))[1]
            best = max(best, value)
    return best


class Picker(tk.Toplevel):
    def __init__(self, parent, frame, callback):
        super().__init__(parent)
        self.title('Drag a rectangle • Escape cancels')
        self.callback = callback
        self.frame = frame
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        self.scale = min(1, (self.winfo_screenwidth()-100)/image.width,
                         (self.winfo_screenheight()-160)/image.height)
        image = image.resize((round(image.width*self.scale), round(image.height*self.scale)))
        self.photo = ImageTk.PhotoImage(image)
        self.canvas = tk.Canvas(self, width=image.width, height=image.height, highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor='nw', image=self.photo)
        self.start = None
        self.rect = None
        self.canvas.bind('<ButtonPress-1>', self.down)
        self.canvas.bind('<B1-Motion>', self.move)
        self.canvas.bind('<ButtonRelease-1>', self.up)
        self.bind('<Escape>', lambda e: self.destroy())
        self.transient(parent)
        self.grab_set()

    def down(self, event):
        self.start = (event.x, event.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(*self.start, *self.start, outline='#64e4ba', width=3)

    def move(self, event):
        if self.start:
            self.canvas.coords(self.rect, *self.start, event.x, event.y)

    def up(self, event):
        if not self.start:
            return
        h, w = self.frame.shape[:2]
        x1, x2 = sorted((self.start[0], event.x))
        y1, y2 = sorted((self.start[1], event.y))
        box = (max(0, int(x1/self.scale)), max(0, int(y1/self.scale)),
               min(w, int(x2/self.scale)), min(h, int(y2/self.scale)))
        if box[2]-box[0] >= 16 and box[3]-box[1] >= 16:
            self.destroy()
            self.callback(box)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Chest Counter • Classic')
        self.geometry('820x850')
        self.minsize(760, 760)
        self.configure(bg=BG)
        self.events = []
        self.config_data = {'monitor': 1, 'roi': None, 'phrase': 'CHEST SEARCHED', 'cooldown': 3.0,
                            'threshold': .90, 'visual': False, 'automatic': True}
        try:
            self.config_data.update(json.loads((DATA/'settings.json').read_text()))
            self.events = json.loads((DATA/'session.json').read_text())
        except (OSError, ValueError):
            pass
        self.running = False
        self.closing = threading.Event()
        self.messages = queue.Queue(maxsize=3)
        self.settings_lock = threading.Lock()
        self.generation = 0
        self.latest_frame = None
        self.ocr = None
        self.template = cv2.imread(str(DATA/'visual.png'), cv2.IMREAD_GRAYSCALE) if (DATA/'visual.png').exists() else None
        with mss.mss() as sct:
            self.monitors = sct.monitors[1:]
        window_monitor = self.config_data.get('window_monitor')
        if '--second-monitor' in sys.argv:
            window_monitor = 2
            self.config_data['window_monitor'] = 2
        if isinstance(window_monitor,int) and 1 <= window_monitor <= len(self.monitors):
            display = self.monitors[window_monitor-1]
            window_width = min(820,display['width']-40)
            window_height = min(850,display['height']-80)
            x = display['left']+max(20,(display['width']-window_width)//2)
            y = display['top']+max(20,(display['height']-window_height)//2)
            self.geometry(f'{window_width}x{window_height}+{x}+{y}')
            self.after(700,self.report_window_position)
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TButton', padding=8, background=PANEL, foreground=TEXT)
        style.configure('TCombobox', padding=5)
        self.label('CHEST COUNTER', 12, ACCENT).pack(pady=(18, 0))
        self.count_label = self.label(str(len(self.events)), 64, TEXT)
        self.count_label.pack()
        self.label('Session total  •  resets only when you choose', 11, MUTED).pack()
        self.label('Notification detection • learns a faster notification area', 10, ACCENT).pack()
        controls = tk.Frame(self, bg=BG)
        controls.pack(pady=15)
        self.start_btn = ttk.Button(controls, text='Start watching', command=self.toggle)
        self.start_btn.pack(side='left', padx=4)
        for name, action in [('Add +1', lambda: self.add('Manual')), ('Undo last', self.undo),
                             ('Reset', self.reset), ('Export CSV', self.export)]:
            ttk.Button(controls, text=name, command=action).pack(side='left', padx=4)
        self.automatic = tk.BooleanVar(value=self.config_data['automatic'])
        tk.Checkbutton(self,text='Automatic chest notification detection • whole display',
            variable=self.automatic,command=self.change_mode,bg=BG,fg=TEXT,
            selectcolor=PANEL,activebackground=BG,activeforeground=TEXT).pack()
        self.label('Press Start watching. The selected display is monitored continuously.\nNo active-window requirement. English game text supported.',11,MUTED).pack(pady=8)
        setup = self.setup = tk.Frame(self, bg=PANEL, padx=16, pady=12)
        self.advanced_btn = ttk.Button(self,text='Show advanced settings',command=self.toggle_advanced)
        self.advanced_btn.pack(pady=4)
        tk.Label(setup, text='Display to watch (all modes)', bg=PANEL, fg=TEXT).grid(row=0,column=0,sticky='w')
        self.monitor = ttk.Combobox(setup, state='readonly', width=26,
            values=[f'Display {i+1} • {m["width"]} × {m["height"]}' for i,m in enumerate(self.monitors)])
        self.monitor.current(min(max(0, self.config_data['monitor']-1), len(self.monitors)-1))
        self.monitor.grid(row=0,column=1,sticky='ew',padx=10)
        self.monitor.bind('<<ComboboxSelected>>', self.change_monitor)
        ttk.Button(setup,text='Manual mode capture area',command=self.select_roi).grid(row=1,column=0,pady=10,sticky='w')
        self.roi_label = tk.Label(setup,text=self.roi_text(),bg=PANEL,fg=MUTED)
        self.roi_label.grid(row=1,column=1,sticky='w',padx=10)
        tk.Label(setup,text='Completion text to count',bg=PANEL,fg=TEXT).grid(row=2,column=0,sticky='w')
        self.phrase = tk.StringVar(value=self.config_data['phrase'])
        entry = ttk.Entry(setup,textvariable=self.phrase,width=28)
        entry.grid(row=2,column=1,sticky='ew',padx=10)
        self.phrase.trace_add('write', lambda *a:self.sync_settings())
        self.visual = tk.BooleanVar(value=self.config_data['visual'])
        tk.Checkbutton(setup,text='Experimental visual event matching (for breaks)',variable=self.visual,
            command=self.sync_settings,bg=PANEL,fg=TEXT,selectcolor=BG,activebackground=PANEL,
            activeforeground=TEXT).grid(row=3,column=0,columnspan=2,sticky='w',pady=(12,0))
        ttk.Button(setup,text='Load & crop event screenshot',command=self.load_template).grid(row=4,column=0,sticky='w',pady=7)
        self.template_label = tk.Label(setup,text='Reference loaded' if self.template is not None else 'No reference loaded',bg=PANEL,fg=MUTED)
        self.template_label.grid(row=4,column=1,sticky='w',padx=10)
        ttk.Button(setup,text='Re-scan full display',command=self.clear_focus).grid(row=5,column=0,sticky='w',pady=4)
        self.label('Counts visible chest XP notifications. Broken chests without a notification\nare not reliably detected. Visual matching is experimental.',10,MUTED).pack(pady=9)
        self.status = self.label('Ready • Press Start watching, then play Fortnite',11,ACCENT)
        self.status.pack()
        usage_panel = tk.Frame(self,bg=PANEL,padx=10,pady=6)
        usage_panel.pack(fill='x',padx=22,pady=(8,0))
        self.pc_usage = tk.Label(usage_panel,text='PC usage: measuring…',bg=PANEL,fg=TEXT,font=('Segoe UI',10))
        self.pc_usage.pack(anchor='w')
        self.app_usage = tk.Label(usage_panel,text='Chest Counter usage: measuring…',bg=PANEL,fg=MUTED,font=('Segoe UI',10))
        self.app_usage.pack(anchor='w')
        try:
            self.usage_monitor = UsageMonitor()
        except (OSError,AttributeError):
            self.usage_monitor = None
        self.last_usage = time.monotonic()
        self.preview = tk.Label(self,bg=PANEL,text='Capture preview appears when watching',fg=MUTED)
        self.preview.pack(fill='both',expand=True,padx=22,pady=9)
        self.debug = self.label('OCR text: —',10,MUTED)
        self.debug.pack()
        self.log = self.label('',10,MUTED)
        self.log.pack(pady=(5,12))
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.sync_settings()
        self.focus_buffer = FocusBuffer(self.closing,self.focus_region)
        self.focus_buffer.thread.start()
        self.thread = threading.Thread(target=self.worker,daemon=True)
        self.thread.start()
        self.poll_timer = self.after(100,self.poll)
        self.start_timer = None

    def label(self,text,size,color):
        return tk.Label(self,text=text,font=('Segoe UI',size),bg=BG,fg=color)

    def report_window_position(self):
        try:
            (DATA/'window-placement.json').write_text(json.dumps(dict(
                x=self.winfo_rootx(),y=self.winfo_rooty(),width=self.winfo_width(),height=self.winfo_height(),
                monitor=self.config_data.get('window_monitor'),time=datetime.now().astimezone().isoformat(timespec='seconds')),indent=2))
        except OSError:
            pass

    def roi_text(self):
        return str(self.config_data['roi']) if self.config_data['roi'] else 'Not selected'

    def focus_region(self):
        if not self.running:
            return None
        with self.settings_lock:
            cfg = dict(self.config_data)
        if not cfg['automatic']:
            return None
        box = cfg.get('notification_roi')
        monitor = self.monitors[cfg['monitor']-1]
        if not isinstance(box,list) or len(box)!=4:
            return None
        x1,y1,x2,y2 = box
        if not (0<=x1<x2<=monitor['width'] and 0<=y1<y2<=monitor['height']):
            return None
        return dict(left=monitor['left']+x1,top=monitor['top']+y1,width=x2-x1,height=y2-y1)

    def clear_focus(self):
        with self.settings_lock:
            self.config_data.pop('notification_roi',None)
        self.sync_settings()

    def sync_settings(self):
        with self.settings_lock:
            self.config_data.update(monitor=self.monitor.current()+1,phrase=self.phrase.get(),visual=self.visual.get(),automatic=self.automatic.get())
            (DATA/'settings.json').write_text(json.dumps(self.config_data,indent=2))

    def change_mode(self):
        self.pause()
        self.sync_settings()

    def toggle_advanced(self):
        if self.setup.winfo_manager():
            self.setup.pack_forget()
            self.advanced_btn.configure(text='Show advanced settings')
        else:
            self.setup.pack(fill='x',padx=22,after=self.advanced_btn)
            self.advanced_btn.configure(text='Hide advanced settings')

    def pause(self):
        self.running = False
        self.generation += 1
        self.start_btn.configure(text='Start watching')
        self.status.configure(text='Paused')
        self.diagnostics(state='paused')

    def diagnostics(self, **values):
        values.update(time=datetime.now().astimezone().isoformat(timespec='seconds'))
        try:
            (DATA/'diagnostics.json').write_text(json.dumps(values,indent=2))
        except OSError:
            pass

    def toggle(self):
        if self.running:
            self.pause()
            return
        if not self.automatic.get() and self.config_data['roi'] is None:
            messagebox.showinfo('Choose area','Select the chest completion notification area first.')
            return
        if not self.automatic.get() and self.visual.get() and self.template is None:
            messagebox.showinfo('Reference needed','Load a screenshot of a distinctive break completion effect first, or disable visual mode.')
            return
        self.generation += 1
        self.running = True
        self.start_btn.configure(text='Pause')
        self.status.configure(text='Starting local OCR…')

    def capture(self):
        with mss.mss() as sct:
            return np.array(sct.grab(self.monitors[self.monitor.current()]))[:,:,:3].copy()

    def change_monitor(self,event=None):
        self.pause()
        self.config_data['roi'] = None
        self.config_data.pop('notification_roi',None)
        self.roi_label.configure(text=self.roi_text())
        self.sync_settings()

    def select_roi(self):
        self.pause()
        self.withdraw()
        def shot():
            try:
                frame = self.capture()
            except Exception as exc:
                self.deiconify()
                messagebox.showerror('Capture failed',str(exc))
                return
            self.deiconify()
            def selected(box):
                self.config_data['roi'] = list(box)
                self.roi_label.configure(text=self.roi_text())
                self.sync_settings()
            Picker(self,frame,selected)
        self.after(400,shot)

    def load_template(self):
        self.pause()
        path = filedialog.askopenfilename(title='Screenshot with chest break completion effect',filetypes=[('Images','*.png *.jpg *.jpeg *.bmp')])
        if not path:
            return
        frame = cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
        if frame is None:
            messagebox.showerror('Image','Could not read image.')
            return
        def selected(box):
            x1,y1,x2,y2 = box
            template = cv2.cvtColor(frame[y1:y2,x1:x2],cv2.COLOR_BGR2GRAY)
            if template.std() < 12:
                messagebox.showerror('Reference','Choose a detailed, distinctive effect rather than a flat area.')
                return
            with self.settings_lock:
                self.template = template
            cv2.imwrite(str(DATA/'visual.png'),template)
            self.template_label.configure(text='Reference loaded')
        Picker(self,frame,selected)

    def post(self,item):
        try:
            self.messages.put(item,timeout=.3)
        except queue.Full:
            pass

    def worker(self):
        seen_generation = -1
        gate = EventGate()
        last_sample = last_full = last_detected = -float('inf')
        try:
            with mss.mss() as sct:
                while not self.closing.is_set():
                    if not self.running:
                        self.closing.wait(.1)
                        continue
                    generation = self.generation
                    if seen_generation != generation:
                        gate = EventGate()
                        seen_generation = generation
                        last_sample = last_full = last_detected = -float('inf')
                    with self.settings_lock:
                        cfg = dict(self.config_data)
                        template = self.template
                    started = time.monotonic()
                    monitor = self.monitors[cfg['monitor']-1]
                    focused_area = self.focus_region()
                    focused = focused_area is not None and not (started-last_full>15 and started-last_detected>5)
                    if focused:
                        capture_area = focused_area
                    elif cfg['automatic']:
                        capture_area = dict(monitor)
                    else:
                        x1,y1,x2,y2 = cfg['roi']
                        capture_area = dict(left=monitor['left']+x1,top=monitor['top']+y1,
                                            width=x2-x1,height=y2-y1)
                    buffered = self.focus_buffer.after(last_sample,capture_area) if focused else None
                    if buffered is not None:
                        captured_at,crop = buffered
                    else:
                        crop = np.array(sct.grab(capture_area))[:,:,:3].copy()
                        captured_at = time.monotonic()
                    last_sample = captured_at
                    if not focused:
                        last_full = captured_at
                    if not crop.size:
                        raise ValueError('Capture area is outside display. Select it again.')
                    if self.ocr is None:
                        self.ocr = make_ocr()
                    ocr_frame = crop
                    if focused:
                        scale = min(2.0,950/max(crop.shape[:2]))
                        ocr_frame = cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
                    elif crop.shape[1] > 1920:
                        ocr_frame = cv2.resize(crop,None,fx=1920/crop.shape[1],fy=1920/crop.shape[1])
                    # Reuse the same model sessions; only change detector sizing.
                    if hasattr(self.ocr,'text_det'):
                        self.ocr.text_det.limit_type = 'max' if focused else 'min'
                        self.ocr.text_det.limit_side_len = 960 if focused else 1600
                    result, _ = self.ocr(ocr_frame,use_cls=False) if focused else self.ocr(ocr_frame)
                    lines = [(r[1],float(r[2])) for r in (result or [])]
                    score = match_score(crop,template) if not cfg['automatic'] and cfg['visual'] and template is not None else 0.0
                    gate.cooldown = .35 if cfg['automatic'] else cfg['cooldown']
                    gate.clear_time = .30 if cfg['automatic'] else .8
                    notifications = locate_notifications(result or []) if cfg['automatic'] else []
                    detected = bool(notifications) if cfg['automatic'] else chest_notification(lines,cfg['phrase'])
                    if detected:
                        last_detected = captured_at
                    if notifications and not focused:
                        box = focus_box(notifications,ocr_frame.shape[1],ocr_frame.shape[0],crop.shape[1],crop.shape[0])
                        if box is not None:
                            with self.settings_lock:
                                self.config_data['notification_roi'] = box
                                try:
                                    (DATA/'settings.json').write_text(json.dumps(self.config_data,indent=2))
                                except OSError:
                                    pass
                    self.diagnostics(state='watching',area=capture_area,recognized_text=[t for t,c in lines],
                                     chest_notification=detected,scan_mode='focused' if focused else 'full',
                                     frame_age_seconds=round(time.monotonic()-captured_at,3),
                                     processing_seconds=round(time.monotonic()-started,3))
                    event = gate.update({'Notification':detected,
                                         'Visual (experimental)':score>=cfg['threshold']},captured_at)
                    preview_scale = min(1,480/crop.shape[1],190/crop.shape[0])
                    preview = cv2.resize(crop,None,fx=preview_scale,fy=preview_scale)
                    elapsed = time.monotonic()-started
                    self.post((generation,event,preview,' | '.join(t for t,c in lines),score))
                    catching_up = focused and time.monotonic()-captured_at>.4
                    self.closing.wait(.005 if catching_up else max(.02,(.18 if focused else .35)-elapsed))
        except Exception as exc:
            self.diagnostics(state='error',error=str(exc))
            self.post(('error',str(exc)))

    def poll(self):
        try:
            while True:
                item = self.messages.get_nowait()
                if item[0]=='error':
                    self.pause()
                    self.start_btn.configure(state='disabled')
                    self.status.configure(text='Capture stopped • restart app after fixing error')
                    messagebox.showerror('Capture stopped',item[1])
                    continue
                generation,event,crop,text,score = item
                if not self.running or generation != self.generation:
                    continue
                if event:
                    self.add(event)
                image = Image.fromarray(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB))
                image.thumbnail((740,190))
                self.photo = ImageTk.PhotoImage(image)
                self.preview.configure(image=self.photo,text='')
                self.debug.configure(text=('OCR text: '+(text or '—'))[:110])
                self.status.configure(text=f'Watching locally • visual match {score:.0%}' if not self.automatic.get() and self.visual.get() else 'Watching • classic notification detection')
        except queue.Empty:
            pass
        if time.monotonic()-self.last_usage >= 1:
            self.last_usage = time.monotonic()
            try:
                if self.usage_monitor is None:
                    raise OSError('Usage is unavailable')
                stats = self.usage_monitor.sample()
                self.pc_usage.configure(text=f'PC: CPU {stats["pc_cpu"]:.0f}%   •   RAM {stats["ram_used"]/1024**3:.1f} / {stats["ram_total"]/1024**3:.1f} GB ({stats["ram_percent"]}%)')
                self.app_usage.configure(text=f'Chest Counter: CPU {stats["app_cpu"]:.1f}%   •   RAM {stats["app_ram"]/1024**2:.0f} MB')
            except (OSError,AttributeError,ValueError):
                self.pc_usage.configure(text='PC usage: unavailable')
                self.app_usage.configure(text='Usage display unavailable; chest detection continues')
        self.poll_timer = self.after(100,self.poll)

    def save_session(self):
        (DATA/'session.json').write_text(json.dumps(self.events,indent=2))
        self.count_label.configure(text=str(len(self.events)))
        self.log.configure(text=('Last: '+self.events[-1]['source']+' • '+self.events[-1]['time']) if self.events else '')

    def add(self,source):
        self.events.append({'time':datetime.now().astimezone().isoformat(timespec='seconds'),'source':source})
        self.save_session()

    def undo(self):
        if self.events:
            self.events.pop()
            self.save_session()

    def reset(self):
        if messagebox.askyesno('Reset count','Clear the current count and event history?'):
            self.pause()
            self.events.clear()
            self.save_session()

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv',initialfile='chest-session.csv',filetypes=[('CSV','*.csv')])
        if path:
            with open(path,'w',newline='',encoding='utf-8') as file:
                writer = csv.DictWriter(file,fieldnames=['time','source'])
                writer.writeheader()
                writer.writerows(self.events)

    def close(self):
        self.running = False
        self.closing.set()
        for timer in (self.poll_timer,self.start_timer):
            if timer is not None:
                self.after_cancel(timer)
        self.destroy()


if __name__=='__main__':
    try:
        # Yield CPU scheduling priority to the game.
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.windll.kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE,wintypes.DWORD]
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),0x4000)
    except (AttributeError,OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError,OSError):
        pass
    application = App()
    if '--resume' in sys.argv:
        application.start_timer = application.after(300,application.toggle)
    application.mainloop()
