import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional


def extract_number_from_filename(filename: str) -> Optional[int]:
    if not filename:
        return None
    match = re.search(r'\d+', filename)
    return int(match.group()) if match else None


def find_files(directory: str, keyword: str) -> list[Path]:
    return [f for f in Path(directory).rglob("*") if f.is_file() and keyword in f.name]


def copy_subtitle_files(input_dir: str, output_dir: str, suffix: str = "subtitle.srt"):
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for sub_dir in input_path.iterdir():
        if not sub_dir.is_dir():
            continue
        for file in sub_dir.iterdir():
            if file.is_file() and file.name.endswith(suffix):
                shutil.copy(file, output_path / file.name)


def zip_files(file_paths: list[Path], zip_path: Path) -> None:
    """将多个本地文件打包为 zip。"""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in file_paths:
            zf.write(p, p.name)


def unzip_file(zip_path: Path, dest_dir: Path) -> None:
    """将 zip 解压到目标目录。"""
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
