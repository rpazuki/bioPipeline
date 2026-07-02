"""Small, dependency-light process functions for YAML pipelines."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any
import io
import logging
import shutil
import sys
import urllib.parse
import urllib.request
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

log = logging.getLogger(__name__)

def download_temp_file(url:str) -> Path | None:
    """Download a temp file from a URL. It never overrides an existing file, 
    so it can be used in multiple steps without redownloading."""
    # url = "http://bigg.ucsd.edu/static/models/iML1515.xml"
    temp_dir = Path(tempfile.gettempdir())
    # Take the basename off a URL (/) or a Windows path (\) alike; a plain
    # url.split("/") would swallow a whole "C:\...\file.xml" as the filename.
    filename = PureWindowsPath(url).name
    output_path = temp_dir / filename

    if output_path.exists():
        logging.info(f"The file already exists at {output_path}")
        return output_path

    logging.info(f"Downloading file from {url}...")
    try:
        urllib.request.urlretrieve(url, output_path)
        logging.info(f"File saved to {output_path}")
        return output_path
    except Exception as e:
        logging.error(f"Failed to download file: {e}")
        return None
    
def download_file_to(url:str, to_path: str):
    """Materialise a file into ``to_path`` and return its path.

    ``url`` may be a real http(s) URL *or* an already-local file path (e.g. an
    input a run workspace staged into ``inputs/``). Either way the file is
    written to ``to_path/<basename>`` so it becomes part of the step's output
    directory and travels with the results instead of being left behind. It
    never overrides an existing destination file, so repeated steps don't
    refetch/recopy."""
    to_dir = Path(to_path)
    to_dir.mkdir(parents=True, exist_ok=True)
    # Take the basename off a URL (/) or a Windows path (\) alike; a plain
    # url.split("/") would swallow a whole "C:\...\file.xml" as the filename.
    filename = PureWindowsPath(url).name
    output_path = to_dir / filename

    if output_path.exists():
        logging.info(f"The file already exists at {output_path}")
        return output_path

    # A local source (a staged input) is copied in, not downloaded, so the model
    # file lands in the output dir rather than being stranded under inputs/.
    if urllib.parse.urlparse(str(url)).scheme not in ("http", "https"):
        source = Path(url)
        if not source.is_file():
            logging.error(f"Source file not found: {source}")
            return None
        if source.resolve() == output_path.resolve():
            logging.info(f"The file already exists at {output_path}")
            return output_path
        try:
            shutil.copyfile(source, output_path)
            logging.info(f"File copied to {output_path}")
            return output_path
        except OSError as e:
            logging.error(f"Failed to copy file: {e}")
            return None

    logging.info(f"Downloading file from {url}...")
    try:
        # Download the file once, then decide how to write it.
        with urllib.request.urlopen(url) as response:
            payload = response.read()

        if filename.endswith(".json"):
            import json
            text = payload.decode("utf-8")
            with output_path.open("w", encoding="utf-8") as handle:
                # Parse and re-dump JSON so objects/arrays stay structured.
                json.dump(json.loads(text), handle, ensure_ascii=False, indent=4)
        elif filename.endswith(".xml"):
            # Keep XML as text so downstream parsers can read the exact document.
            text = payload.decode("utf-8")
            with output_path.open("w", encoding="utf-8") as handle:
                handle.write(text)
        else:
            output_path.write_bytes(payload)
        logging.info(f"File saved to {output_path}")
        return output_path
    except Exception as e:
        logging.error(f"Failed to download file: {e}")
        return None
    
def ensure_list(value: Any) -> list[Any]:
    """Return value as a list so downstream steps can rely on list semantics."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def sequence(start: int, stop: int, step: int = 1) -> list[int]:
    """Build an integer sequence for synthetic or test payload generation."""
    return list(range(start, stop, step))


def format_message(message: str, prefix: str = "", suffix: str = "") -> str:
    """Create a formatted message string for logs, labels, or text outputs."""
    return f"{prefix}{message}{suffix}"


def log_value(message: object, prefix: str = "") -> str:
    """Print a value to stdout and return the rendered text."""
    rendered = f"{prefix}{message}"
    print(rendered, flush=True)
    return rendered


def save_text(text: str, path: str, append: bool = False, encoding: str = "utf-8") -> str:
    """Write text to disk and return the resolved file path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with target.open(mode, encoding=encoding) as handle:
        handle.write(text)
    return str(target.resolve())
