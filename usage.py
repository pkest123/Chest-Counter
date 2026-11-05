"""Small, nonblocking Windows CPU/RAM sampler. No subprocesses or dependencies."""
import ctypes
from ctypes import wintypes
import os
import time


class MemoryStatus(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
        (name, ctypes.c_ulonglong) for name in
        ('total_physical', 'available_physical', 'total_pagefile', 'available_pagefile',
         'total_virtual', 'available_virtual', 'available_extended_virtual')]


class ProcessMemory(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('page_faults', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in
        ('peak_working_set', 'working_set', 'peak_paged_pool', 'paged_pool',
         'peak_nonpaged_pool', 'nonpaged_pool', 'pagefile', 'peak_pagefile')]


class UsageMonitor:
    def __init__(self):
        self.kernel = ctypes.windll.kernel32
        self.psapi = ctypes.windll.psapi
        self.kernel.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)]*3
        self.kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
        self.kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
        self.previous_system = self.system_times()
        self.previous_clock = time.monotonic()
        self.previous_process = time.process_time()

    def system_times(self):
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not self.kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            raise OSError('CPU usage is unavailable')
        value = lambda item: (item.dwHighDateTime << 32) | item.dwLowDateTime
        return value(idle), value(kernel)+value(user)

    def sample(self):
        idle, total = self.system_times()
        old_idle, old_total = self.previous_system
        system_cpu = 100*(1-(idle-old_idle)/max(1, total-old_total))
        self.previous_system = idle, total
        now, process = time.monotonic(), time.process_time()
        app_cpu = 100*(process-self.previous_process)/max(.001, now-self.previous_clock)/max(1, os.cpu_count() or 1)
        self.previous_clock, self.previous_process = now, process
        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if not self.kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise OSError('PC memory usage is unavailable')
        app_memory = ProcessMemory()
        app_memory.size = ctypes.sizeof(app_memory)
        if not self.psapi.GetProcessMemoryInfo(self.kernel.GetCurrentProcess(), ctypes.byref(app_memory), app_memory.size):
            raise OSError('Counter memory usage is unavailable')
        return dict(pc_cpu=max(0, min(100, system_cpu)), app_cpu=max(0, min(100, app_cpu)),
                    ram_used=memory.total_physical-memory.available_physical,
                    ram_total=memory.total_physical, ram_percent=memory.load,
                    app_ram=app_memory.working_set)
