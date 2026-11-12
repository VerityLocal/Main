"""Start the Verity Local backend on this computer."""

import argparse
import os
from pathlib import Path
import secrets
import sys

from backend.config import PROJECT_ROOT, Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extension-id', default=os.getenv('PDF_AI_EXTENSION_ID'))
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if sys.platform == 'win32':
        parser.error('Run the backend in WSL 2 on Windows. See https://veritylocal.github.io/#setup')
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    local = PROJECT_ROOT / '.local'
    local.mkdir(mode=0o700, exist_ok=True)
    token_path = local / 'backend-token'
    if not os.getenv('PDF_AI_AUTH_TOKEN'):
        if not token_path.exists():
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(secrets.token_urlsafe(48))
        os.environ['PDF_AI_AUTH_TOKEN'] = token_path.read_text().strip()
    if args.extension_id:
        os.environ['PDF_AI_EXTENSION_ID'] = args.extension_id
    extraction = PROJECT_ROOT / '.venv-extraction/bin/python'
    tesseract = PROJECT_ROOT / '.tools-ocr/bin/tesseract'
    tessdata = PROJECT_ROOT / '.tools-ocr/share/tessdata'
    if extraction.is_file():
        os.environ.setdefault('PDF_AI_EXTRACTION_PYTHON', str(extraction))
    if tesseract.is_file():
        os.environ.setdefault('PDF_AI_TESSERACT_COMMAND', str(tesseract))
    if tessdata.is_dir():
        os.environ.setdefault('PDF_AI_TESSDATA_DIR', str(tessdata))
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
    settings = Settings.from_env()
    print(f'Verity Local backend: http://127.0.0.1:{args.port}', flush=True)
    print(f'Token file (not printed): {token_path}', flush=True)
    print(f'Authorized extension: {settings.extension_id or "not configured"}', flush=True)
    import uvicorn
    from backend.app import create_app
    uvicorn.run(create_app(settings), host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
