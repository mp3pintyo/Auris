# Third-party notices

## Windows desktop distribution

The Windows installer is an aggregate of Auris and separately licensed runtime
components. Python is distributed under the PSF license; pywebview under the
BSD-3-Clause license; pythonnet under MIT. Runtime package metadata and license
files are preserved in `runtime/Lib/site-packages`; the exact package versions
are recorded in `runtime-manifest.json`.

- CPython binary/source: https://www.python.org/downloads/release/python-3119/
- pywebview source: https://github.com/r0x0r/pywebview
- pythonnet source: https://github.com/pythonnet/pythonnet
- PyTorch source and notices: https://github.com/pytorch/pytorch
- Microsoft WebView2 is a separately installed Microsoft runtime:
  https://developer.microsoft.com/microsoft-edge/webview2/

Microsoft C++ runtime DLLs retain their Microsoft licenses and copyrights.
CPython provides `vcruntime140.dll` and `vcruntime140_1.dll`; the NumPy wheel
provides the Microsoft-signed `msvcp140.dll`, also placed beside the interpreter
under its original filename so that Torch can load on a fresh Windows system.
https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files

ONNX Runtime is bundled as `onnxruntime-directml` (MIT), which includes
Microsoft's `DirectML.dll`. DirectML retains its Microsoft license terms, which
permit redistribution in Windows applications that use it for machine learning:
https://www.nuget.org/packages/Microsoft.AI.DirectML/1.15.4/license

FFmpeg and ffprobe are separate command-line programs from the Gyan Windows
essentials build, licensed under GPL-3.0. Their license and build information
are included under `tools/`. This distribution does not change Auris's MIT
license. Build/source information is available at
https://www.gyan.dev/ffmpeg/builds/ and https://ffmpeg.org/download.html .
The selected build version and source commit are recorded in the desktop
release's source notices. Voice model weights are downloaded at runtime and
retain their model-specific licenses listed below; they are not embedded in
the installer.

## OmniVoice

The OmniVoice package code is licensed under Apache-2.0. Its pretrained model
weights are licensed under CC-BY-NC, as stated in the publisher's model card:
https://huggingface.co/k2-fsa/OmniVoice#license . Model weights are downloaded
on the user's first run and are not included in the Windows installer.

## LocalText2Voice

Parts of Auris text preparation and audiobook export behavior are derived from
or inspired by LocalText2Voice:

https://github.com/estebanstifli/LocalText2Voice

MIT License

Copyright (c) 2026 Esteban / AndromedaNova.com

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Trafilatura

Auris uses Trafilatura to extract article text and metadata from downloaded
HTML pages:

https://trafilatura.readthedocs.io/

Copyright 2019-2026 Adrien Barbaresi and contributors.

Licensed under the Apache License, Version 2.0:

https://www.apache.org/licenses/LICENSE-2.0

## MOSS-TTS-Nano ONNX runtime (vendored)

`reader/core/vendor/moss_tts_nano_onnx/` contains the unmodified ONNX CPU
runtime and text-normalization modules of MOSS-TTS-Nano:

https://github.com/OpenMOSS/MOSS-TTS-Nano

Copyright OpenMOSS Team. Licensed under the Apache License, Version 2.0; the
full license text is in `reader/core/vendor/moss_tts_nano_onnx/LICENSE`.
The MOSS-TTS, MOSS-TTS-Nano and MOSS Audio Tokenizer model weights are
downloaded from Hugging Face at runtime and are licensed under Apache-2.0.

## Supertonic (vendored helper)

`reader/core/vendor/supertonic/helper.py` is copied unchanged from:

https://github.com/supertone-oss-archive/supertonic

MIT License, Copyright (c) 2025 Supertone Inc. The full text is in
`reader/core/vendor/supertonic/LICENSE`. The Supertonic 3 model weights are
downloaded at runtime from `supertone-oss-archive/supertonic-3` and are
licensed under the BigScience OpenRAIL-M license, which includes use-based
restrictions that users must follow.

## omnivoice-triton kernels (vendored)

`reader/core/vendor/omnivoice_triton/` contains the Triton kernels and
`models/patching.py` of omnivoice-triton 0.1.0 (package-internal imports made
relative):

https://github.com/newgrit1004/omnivoice-triton

Copyright Sewon Kim. Licensed under the Apache License, Version 2.0; the full
text is in `reader/core/vendor/omnivoice_triton/LICENSE`. The optional Triton
compiler (`triton`, or `triton-windows` on Windows, MIT) is installed by the
user from Settings.

## onnx-asr and NVIDIA Parakeet TDT 0.6B v3

Quality control can use the `onnx-asr` package (MIT) to run NVIDIA Parakeet
TDT 0.6B v3. The ONNX export (`istupakov/parakeet-tdt-0.6b-v3-onnx`) is
downloaded from Hugging Face on first use; the model is licensed under
CC-BY-4.0 by NVIDIA.

## 3D-Speaker CAM++ speaker embedding

Speaker-similarity measurement uses the CAM++ speaker-verification model
`iic/speech_campplus_sv_zh_en_16k-common_advanced` from Alibaba's 3D-Speaker
project (Apache-2.0). The ONNX export
`3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx` is downloaded on
first use from `csukuangfj/speaker-embedding-models` (sherpa-onnx model
collection) at a pinned revision and verified by SHA-256.

## Piper and Hungarian Piper voices (optional)

The optional Piper engine uses the `piper-tts` package (piper1-gpl,
GPL-3.0-or-later, bundling espeak-ng, GPL-3.0). Auris does not bundle it; the
user installs it separately from Settings. The Hungarian voices (`anna`,
`berta`, `imre`) are downloaded from `rhasspy/piper-voices`; their training
data is published under CC0.

## HuSpaCy

Hungarian character detection can use the HuSpaCy `hu_core_news_md` model,
installed on request from https://huggingface.co/huspacy. HuSpaCy is licensed
under Apache-2.0; see the model card for the licenses of its training data.

## Pyphen

Pyphen (https://github.com/Kozea/Pyphen) and its Hungarian hyphenation
dictionary are used to tell PDF line-break hyphens from compound hyphens.
Pyphen is licensed under GPL-2.0+/LGPL-2.1+/MPL-1.1; the Hungarian dictionary
is distributed by the LibreOffice project under the same terms.
