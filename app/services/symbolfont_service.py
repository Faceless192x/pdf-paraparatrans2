from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List


_BOOK_FONT_FAMILY_PATTERN = re.compile(r"font-family\s*:\s*([^;\n]+)", re.IGNORECASE)


def _extract_book_font_name(style_value: str) -> str:
    if not style_value:
        return ""

    match = _BOOK_FONT_FAMILY_PATTERN.search(style_value)
    if not match:
        return ""

    family_expr = match.group(1).strip()
    if not family_expr:
        return ""

    primary = family_expr.split(",", 1)[0].strip().strip("'\"")
    if not primary:
        return ""

    # PDF由来の `FontName-BoldItalic` 形式はハイフン以降を落としてフォント名だけ採用
    primary = primary.split("-", 1)[0].strip()
    if not primary:
        return ""

    return re.sub(r"\s+", " ", primary).strip()


@dataclass
class SymbolFontService:
    symbolfonts_dir: str

    def _font_file_path(self, font_name: str) -> str:
        """フォント名に対応するファイルパスを返す。"""
        return os.path.join(self.symbolfonts_dir, font_name + ".txt")

    def list_font_names(self) -> List[str]:
        """symbolfonts/ ディレクトリ内のフォント名一覧を返す。"""
        names: List[str] = []
        try:
            for entry in os.listdir(self.symbolfonts_dir):
                if entry.lower().endswith(".txt") and os.path.isfile(
                    os.path.join(self.symbolfonts_dir, entry)
                ):
                    names.append(entry[:-4])  # strip .txt
        except OSError:
            pass
        return sorted(names)

    def get_registered(self) -> Dict[str, str]:
        """symbolfonts/ 配下の全ファイルを走査して全マッピングを返す。

        戻り値形式: { "FontName.char": "replacement", ... }
        """
        symbols: Dict[str, str] = {}
        try:
            entries = os.listdir(self.symbolfonts_dir)
        except OSError:
            return symbols

        for filename in sorted(entries):
            if not filename.lower().endswith(".txt"):
                continue
            file_path = os.path.join(self.symbolfonts_dir, filename)
            if not os.path.isfile(file_path):
                continue
            font_name = filename[:-4]  # strip .txt
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) == 2 and parts[0]:
                        key = f"{font_name}.{parts[0]}"
                        symbols[key] = parts[1]

        return symbols

    def register(self, font_style: str, replacement: str) -> None:
        """font_style のマッピングを追加/更新する。

        font_style は "FontName.char" 形式。
        """
        if "." not in font_style:
            raise ValueError(f"font_style は 'FontName.char' 形式にしてください: {font_style}")
        font_name, char = font_style.split(".", 1)
        font_name = font_name.strip()
        if not font_name or char == "":
            raise ValueError(f"font_style の形式が不正です: {font_style}")

        file_path = self._font_file_path(font_name)
        lines: list = []
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        # 既存エントリを除去
        filtered = []
        for line in lines:
            if line.strip().startswith("#"):
                filtered.append(line)
            else:
                parts = line.strip().split("\t", 1)
                if not (parts and parts[0] == char):
                    filtered.append(line)

        filtered.append(f"{char}\t{replacement}\n")

        os.makedirs(self.symbolfonts_dir, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(filtered)

    def delete(self, key: str) -> None:
        """key に対応するマッピングを削除する。

        key は "FontName.char" 形式。
        """
        if "." not in key:
            return
        font_name, char = key.split(".", 1)
        font_name = font_name.strip()
        if not font_name:
            return

        file_path = self._font_file_path(font_name)
        if not os.path.exists(file_path):
            return

        lines: list = []
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        filtered = []
        for line in lines:
            if line.strip().startswith("#"):
                filtered.append(line)
            else:
                parts = line.strip().split("\t", 1)
                if not (parts and parts[0] == char):
                    filtered.append(line)

        data_lines = [l for l in filtered if l.strip() and not l.strip().startswith("#")]
        if not data_lines:
            # マッピングが0件になったらファイルを削除
            try:
                os.remove(file_path)
            except OSError:
                pass
        else:
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(filtered)

    def update_mappings(self, font_name: str, mappings: Dict[str, str]) -> None:
        """指定フォントのマッピングを一括更新する。"""
        file_path = self._font_file_path(font_name)

        if not mappings:
            # 0件になったらファイルを削除
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
            return

        os.makedirs(self.symbolfonts_dir, exist_ok=True)
        lines = []
        for key, replacement in mappings.items():
            if key and replacement:
                char_clean = key.replace("\n", "").replace("\r", "").strip()
                replacement_clean = replacement.replace("\n", "").replace("\r", "").strip()
                if char_clean and replacement_clean:
                    lines.append(f"{char_clean}\t{replacement_clean}\n")

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def get_book_fonts(self, json_path: str) -> Dict[str, str]:
        """ブック JSON からフォント名一覧を抽出して返す。"""
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)

        styles = book_data.get("styles", {}) or {}
        fonts: set = set()
        for style_value in styles.values():
            if isinstance(style_value, str):
                font_name = _extract_book_font_name(style_value)
                if font_name:
                    fonts.add(font_name)

        font_list = sorted(fonts)
        return {f: f for f in font_list}
