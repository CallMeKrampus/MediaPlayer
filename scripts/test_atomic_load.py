import os
import sys
import time
from PyQt6.QtWidgets import QApplication, QWidget

os.environ['PATH'] = r'C:\Program Files\Topaz Labs LLC\Topaz Video;' + os.environ.get('PATH', '')
os.add_dll_directory(r'C:\Program Files\Topaz Labs LLC\Topaz Video')
import mpv
mpv.MPV.mpv_version_tuple = property(lambda self: (0, 39, 0))

app = QApplication(sys.argv)
w = QWidget()
w.resize(800, 450)
w.show()

pic = os.path.abspath(r'Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV\Ramayana_TLR-2D_HI_EPQ_QCM_4K-reel-1-jp2k.mxf')
snd = os.path.abspath(r'Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV\Ramayana_TLR-2D_HI_EPQ_QCM_4K-reel-1-pcm.mxf')

p = mpv.MPV(wid=str(int(w.winId())), vo='gpu-next', hwdec='auto-safe')
# Pass audio-file parameter at loadfile time
p.command('loadfile', pic, 'replace', f'audio-file={snd}')

for i in range(25):
    time.sleep(0.1)
    app.processEvents()

print('Tracks after atomic loadfile:')
for t in (p.track_list or []):
    print(' ', t.get('type'), t.get('id'), t.get('codec'), 'selected:', t.get('selected'), 'external:', t.get('external'))

w.close()
