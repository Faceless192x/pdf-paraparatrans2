from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict


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
    symbolfont_dict_path: str
    symbolfonts_path: str

    def get_registered(self) -> Dict[str, str]:
        """symbolfont_dict.txt から全マッピングを読み込んで返す。"""
        symbols: Dict[str, str] = {}
        if os.path.exists(self.symbolfont_dict_path):
            with open(self.symbolfont_dict_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) == 2:
                        symbols[parts[0]] = parts[1]
        return symbols

    def register(self, font_style: str, replacement: str) -> None:
        """font_style のマッピングを追加/更新し、フォント名を symbolfonts.txt にも登録する。"""
        lines: list = []
        if os.path.exists(self.symbolfont_dict_path):
            with open(self.symbolfont_dict_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        # 既存エントリを除去
        filtered = []
        for line in lines:
            if line.strip().startswith("#"):
                filtered.append(line)
            else:
                parts = line.strip().split("\t")
                if not (parts and parts[0] == font_style):
                    filtered.append(line)

        filtered.append(f"{font_style}\t{replacement}\n")

        os.makedirs(os.path.dirname(self.symbolfont_dict_path), exist_ok=True)
        with open(self.symbolfont_dict_path, "w", encoding="utf-8") as f:
            f.writelines(filtered)

        # symbolfonts.txt にフォント名を追記（未登録の場合のみ）
        font_name = font_style.split(".")[0] if "." in font_style else font_style
        self._ensure_font_name(font_name)

    def delete(self, key: str) -> None:
        """key に対応するマッピングを symbolfont_dict.txt から削除する。"""
        lines: list = []
        if os.path.exists(self.symbolfont_dict_path):
            with open(self.symbolfont_dict_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        filtered = []
        for line in lines:
            if line.strip().startswith("#"):
                filtered.append(line)
            else:
                parts = line.strip().split("\t")
                if not (parts and parts[0] == key):
                    filtered.append(line)

        os.makedirs(os.path.dirname(self.symbolfont_dict_path), exist_ok=True)
        with open(self.symbolfont_dict_path, "w", encoding="utf-8") as f:
            f.writelines(filtered)

    def update_mappings(self, font_name: str, mappings: Dict[str, str]) -> None:
        """指定フォントのマッピングを一括更新する。"""
        lines: list = []
        if os.path.exists(self.symbolfont_dict_path):
            with open(self.symbolfont_dict_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        # 対象フォントのエントリを除去（コメント・空行は保持）
        filtered = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                filtered.append(line)
            else:
                parts = line_stripped.split("\t")
                if not (parts and parts[0].startswith(font_name + ".")):
                    if line and not line.endswith("\n"):
                        filtered.append(line + "\n")
                    else:
                        filtered.append(line)

        # 新しいマッピングを追加
        for key, replacement in mappings.items():
            if key and replacement:
                key_clean = key.replace("\n", "").replace("\r", "").strip()
                replacement_clean = replacement.replace("\n", "").replace("\r", "").strip()
                if key_clean and replacement_clean:
                    filtered.append(f"{key_clean}\t{replacement_clean}\n")

        os.makedirs(os.path.dirname(self.symbolfont_dict_path), exist_ok=True)
        with open(self.symbolfont_dict_path, "w", encoding="utf-8") as f:
            f.writelines(filtered)

        if mappings:
            self._ensure_font_name(font_name)

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

    def _ensure_font_name(self, font_name: str) -> None:
        """symbolfonts.txt にフォント名が未登録の場合のみ追記する。"""
        if os.path.exists(self.symbolfonts_path):
            with open(self.symbolfonts_path, "r", encoding="utf-8") as f:
                content = f.read()
            if font_name not in content:
                with open(self.symbolfonts_path, "a", encoding="utf-8") as f:
                    f.write(f"{font_name}\n")
        else:
            os.makedirs(os.path.dirname(self.symbolfonts_path), exist_ok=True)
            with open(self.symbolfonts_path, "w", encoding="utf-8") as f:
                f.write(f"{font_name}\n")
