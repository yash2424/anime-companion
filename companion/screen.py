"""Knows which window you're using and can capture it (Windows only).

A background thread remembers the last foreground window that isn't the companion itself, so typing
into the companion (or pressing its hotkeys) still refers to the app you were actually using.
"""
import base64
import ctypes
import ctypes.wintypes as wt
import io
import logging
import os
from pathlib import Path
import threading
import time

from .config import ROOT

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi

try:  # Real pixel coordinates on scaled (125%/150%) displays.
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    user32.SetProcessDPIAware()

HWND = wt.HWND
user32.GetForegroundWindow.restype = HWND
user32.GetWindowTextLengthW.argtypes = [HWND]
user32.GetWindowTextW.argtypes = [HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wt.DWORD)]
user32.IsWindow.argtypes = [HWND]
user32.IsWindowVisible.argtypes = [HWND]
user32.IsIconic.argtypes = [HWND]
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowDC.argtypes = [HWND]
user32.GetWindowDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [HWND, wt.HDC]
user32.PrintWindow.argtypes = [HWND, wt.HDC, wt.UINT]
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
dwmapi.DwmGetWindowAttribute.argtypes = [HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]

SHELL_CLASSES = {'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'Progman', 'WorkerW', 'NotifyIconOverflowWindow',
                 'Windows.UI.Core.CoreWindow', 'XamlExplorerHostIslandWindow', 'TopLevelWindowForOverflowXamlIsland'}
OWN_TITLE_MARKER = 'anime companion'   # the web UI's <title> contains this
ROOT_STR = str(ROOT).lower()


def _title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _process(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    path = ''
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            path = buf.value
        kernel32.CloseHandle(handle)
    return pid.value, path


def _friendly_app(path):
    names = {'chrome.exe': 'Google Chrome', 'msedge.exe': 'Microsoft Edge', 'firefox.exe': 'Firefox',
             'code.exe': 'Visual Studio Code', 'explorer.exe': 'File Explorer', 'discord.exe': 'Discord',
             'spotify.exe': 'Spotify', 'winword.exe': 'Word', 'excel.exe': 'Excel', 'powerpnt.exe': 'PowerPoint',
             'windowsterminal.exe': 'Windows Terminal', 'notepad.exe': 'Notepad', 'steam.exe': 'Steam',
             'vlc.exe': 'VLC', 'obs64.exe': 'OBS', 'brave.exe': 'Brave', 'opera.exe': 'Opera'}
    exe = Path(path).name
    return names.get(exe.lower(), Path(exe).stem or 'an app')


def _is_own(hwnd, title, path, pid):
    return (pid == os.getpid() or path.lower().startswith(ROOT_STR)
            or OWN_TITLE_MARKER in title.lower())


def _rect(hwnd):
    rect = wt.RECT()
    # Extended frame bounds exclude the invisible resize borders of Windows 10/11 windows.
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


class Shot:
    def __init__(self, title, app, image=None, note=''):
        self.title, self.app, self.image, self.note = title, app, image, note

    def label(self):
        return f'{self.app} — "{self.title}"' if self.title else self.app

    def tool_text(self):
        if self.image:
            return f'Screenshot of the user\'s current window: {self.label()}.'
        return f'Could not capture the window ({self.label()}): {self.note}'


class Tracker:
    def __init__(self):
        self.last = None   # (hwnd, title, path, time)
        self.enabled = True
        threading.Thread(target=self._loop, daemon=True, name='window-tracker').start()

    def _loop(self):
        while True:
            try:
                if self.enabled:
                    self._poll()
            except Exception:
                logging.exception('Window tracker error')
            time.sleep(0.5)

    def _poll(self):
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return
        cls = _class(hwnd)
        title = _title(hwnd)
        pid, path = _process(hwnd)
        if _is_own(hwnd, title, path, pid):
            return
        if cls in SHELL_CLASSES:
            self.last = (None, 'Desktop', 'explorer.exe', time.time())
        else:
            self.last = (hwnd, title, path, time.time())

    def current(self):
        """(title, app name) of the window the user is working in, or None."""
        if not self.last:
            return None
        hwnd, title, path, _ = self.last
        if hwnd and not user32.IsWindow(hwnd):
            return None
        return title, _friendly_app(path)

    def capture(self, max_width=1280, quality=70):
        if not self.last:
            return Shot('', 'unknown', note='no window has been active yet')
        hwnd, title, path, _ = self.last
        app = _friendly_app(path)
        if not hwnd:
            return self._grab_screen(title, app, max_width, quality)
        if not user32.IsWindow(hwnd):
            return Shot(title, app, note='the window was closed')
        if user32.IsIconic(hwnd):
            return Shot(title, app, note='the window is minimized')
        left, top, right, bottom = _rect(hwnd)
        width, height = right - left, bottom - top
        if width < 20 or height < 20:
            return Shot(title, app, note='the window is too small')
        image = _print_window(hwnd, width, height)
        if image is None or _mostly_black(image):
            # Some apps (games, hardware video) don't render into PrintWindow; grab the pixels instead.
            from PIL import ImageGrab
            image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
        return Shot(title, app, _encode(image, max_width, quality))

    def _grab_screen(self, title, app, max_width, quality):
        from PIL import ImageGrab
        return Shot(title, app, _encode(ImageGrab.grab(), max_width, quality))


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wt.DWORD), ('biWidth', wt.LONG), ('biHeight', wt.LONG), ('biPlanes', wt.WORD),
                ('biBitCount', wt.WORD), ('biCompression', wt.DWORD), ('biSizeImage', wt.DWORD),
                ('biXPelsPerMeter', wt.LONG), ('biYPelsPerMeter', wt.LONG), ('biClrUsed', wt.DWORD),
                ('biClrImportant', wt.DWORD)]


def _print_window(hwnd, width, height):
    from PIL import Image
    window_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, mem_dc, 2):  # PW_RENDERFULLCONTENT
            return None
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0):
            return None
        return Image.frombuffer('RGB', (width, height), buffer, 'raw', 'BGRX', 0, 1)
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, window_dc)


def _mostly_black(image):
    small = image.convert('L').resize((32, 32))
    return max(small.getdata()) < 12


def _encode(image, max_width, quality):
    image = image.convert('RGB')
    if image.width > max_width:
        image = image.resize((max_width, round(image.height * max_width / image.width)))
    out = io.BytesIO()
    image.save(out, 'JPEG', quality=quality)
    return base64.b64encode(out.getvalue()).decode('ascii')


def fingerprint(b64):
    """Tiny grayscale thumbnail used to tell whether the screen changed since the last glance."""
    from PIL import Image
    image = Image.open(io.BytesIO(base64.b64decode(b64))).convert('L').resize((24, 16))
    return list(image.getdata())


def similar(a, b, threshold=6.0):
    if not a or not b:
        return False
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a) < threshold
