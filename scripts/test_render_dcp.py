import os
import sys
import time
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt

os.environ['PATH'] = r'C:\Program Files\Topaz Labs LLC\Topaz Video;' + os.environ.get('PATH', '')
os.add_dll_directory(r'C:\Program Files\Topaz Labs LLC\Topaz Video')
import mpv
mpv.MPV.mpv_version_tuple = property(lambda self: (0, 39, 0))

app = QApplication(sys.argv)
win = QMainWindow()
win.resize(1024, 576)
w = QWidget(win)
win.setCentralWidget(w)
win.show()

pic = os.path.abspath(r'Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV\Ramayana_TLR-2D_HI_EPQ_QCM_4K-reel-1-jp2k.mxf')
snd = os.path.abspath(r'Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV\Ramayana_TLR-2D_HI_EPQ_QCM_4K-reel-1-pcm.mxf')

# Initialize mpv with gpu-next, NO custom shader
p = mpv.MPV(
    wid=str(int(w.winId())),
    vo='gpu-next',
    hwdec='auto-safe',
    target_prim='bt.709',
    target_trc='srgb',
    tone_mapping='bt.2390'
)

p.command('loadfile', pic, 'replace')

# Wait for file to load before adding audio
for i in range(20):
    time.sleep(0.1)
    app.processEvents()

print('File loaded, duration:', p.duration)
print('Video params:', p.video_params)

# Now attach audio
try:
    p.command('audio-add', snd, 'select')
    p['aid'] = 1
    print('Audio added successfully! Aid:', p['aid'])
except Exception as e:
    print('Audio add error:', e)

for i in range(30):
    time.sleep(0.1)
    app.processEvents()

print('Playback time:', p.time_pos)
print('Tracks:', [(t.get('type'), t.get('id'), t.get('codec'), t.get('selected')) for t in (p.track_list or [])])
win.close()
