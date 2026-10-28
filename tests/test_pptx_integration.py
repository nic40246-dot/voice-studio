import os
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
import win32com.client
from app.core.pptx_service import PowerPointService


def test_pptx_com_audio_embedding(tmp_path):
    # 1. Create a dummy audio file
    sr = 24000
    t = np.linspace(0, 2.0, int(sr * 2.0), endpoint=False)
    audio = 0.3 * np.sin(2 * np.pi * 440 * t)
    audio_wav = tmp_path / "slide1_audio.wav"
    sf.write(str(audio_wav), audio, sr, subtype="PCM_16")

    # 2. Create a test presentation via COM
    test_pptx = tmp_path / "base_presentation.pptx"
    ppt = win32com.client.Dispatch("PowerPoint.Application")
    pres = ppt.Presentations.Add(False)
    slide1 = pres.Slides.Add(1, 12) # ppLayoutBlank
    slide2 = pres.Slides.Add(2, 12)
    pres.SaveAs(str(test_pptx.resolve()))
    pres.Close()

    assert test_pptx.exists()

    # 3. Test PowerPointService slide extraction
    service = PowerPointService()
    slides_info = service.extract_slides_info(test_pptx, generate_thumbnails=False)
    assert len(slides_info) == 2
    assert slides_info[0]["slide_number"] == 1
    assert slides_info[1]["slide_number"] == 2

    # 4. Test Batch Export with autoplay audio embedding
    out_pptx = tmp_path / "narrated_presentation.pptx"
    audio_map = {1: str(audio_wav.resolve())}
    exported = service.batch_export_presentation(
        source_pptx=test_pptx,
        output_pptx=out_pptx,
        slide_audio_map=audio_map,
    )
    assert Path(exported).exists()
    assert os.path.getsize(exported) > os.path.getsize(str(test_pptx))
