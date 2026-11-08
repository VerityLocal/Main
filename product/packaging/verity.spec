# Build natively on each target OS/architecture. Never cross-freeze an executable.
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = Path(SPECPATH).parents[1]
bundle = Path(os.environ['VERITY_BUNDLE']).resolve()
datas = [(str(item), 'bundle/' + item.name if item.is_dir() else 'bundle') for item in bundle.iterdir() if item.name != 'browsers']
datas += [(str(root / 'product/engine/calibration.json'), 'product/engine')]
binaries = []
hiddenimports = ['product.desktop.acceptance']
for package in ['transformers', 'sentence_transformers', 'docling_parse', 'docling_core', 'playwright', 'sentencepiece', 'tokenizers']:
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
for name in ['torch', 'transformers', 'sentence-transformers', 'accelerate', 'safetensors', 'tokenizers', 'numpy', 'huggingface-hub', 'tqdm', 'regex', 'requests', 'packaging', 'filelock', 'pyyaml', 'docling-parse', 'docling-core', 'playwright']:
    datas += copy_metadata(name)

a = Analysis([str(root / 'verity.py')], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
    excludes=['samecode', 'product.engine.server', 'product.engine.native_host', 'product.engine.model_setup', 'product.installer', 'tensorflow', 'jax', 'IPython', 'notebook', 'pytest', 'matplotlib', 'torchaudio', 'torchvision'],
    noarchive=False, optimize=1)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Verity', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Verity')
if sys.platform == 'darwin':
    app = BUNDLE(collection, name='Verity.app', bundle_identifier='org.veritylocal.desktop',
        info_plist={'CFBundleDisplayName': 'Verity', 'CFBundleShortVersionString': '0.3.0', 'CFBundleVersion': '0.3.0.1',
                    'NSHighResolutionCapable': True, 'NSRequiresAquaSystemAppearance': False})
