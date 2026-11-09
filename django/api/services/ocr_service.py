from __future__ import annotations

import os
import threading

import pymupdf

os.environ.setdefault('OMP_THREAD_LIMIT', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')

from tesserocr import OEM, PSM, PyTessBaseAPI  # noqa: E402


_thread_local = threading.local()


def _get_tesseract_api() -> PyTessBaseAPI:
    api = getattr(_thread_local, 'api', None)
    if api is None:
        tessdata_path = next(
            (
                path
                for path in (
                    os.getenv('TESSDATA_PREFIX'),
                    '/usr/share/tesseract-ocr/5/tessdata',
                    '/usr/share/tesseract-ocr/4.00/tessdata',
                )
                if path and os.path.isdir(path)
            ),
            None,
        )
        argumentos = {
            'lang': os.getenv('TESSERACT_LANG', 'eng'),
            'oem': OEM.LSTM_ONLY,
        }
        if tessdata_path:
            argumentos['path'] = tessdata_path
        api = PyTessBaseAPI(**argumentos)
        api.SetVariable('load_system_dawg', '0')
        api.SetVariable('load_freq_dawg', '0')
        api.SetVariable('classify_enable_learning', '0')
        api.SetVariable('classify_enable_adaptive_matcher', '0')
        api.SetPageSegMode(PSM.SINGLE_BLOCK)
        _thread_local.api = api
    return api


def extract_page_text(page, dpi: int = 150) -> str:
    pixmap = page.get_pixmap(
        dpi=dpi,
        colorspace=pymupdf.csGRAY,
        alpha=False,
    )
    api = _get_tesseract_api()
    api.SetImageBytes(
        bytes(pixmap.samples),
        pixmap.width,
        pixmap.height,
        1,
        pixmap.stride,
    )
    try:
        return api.GetUTF8Text().strip()
    finally:
        api.Clear()
