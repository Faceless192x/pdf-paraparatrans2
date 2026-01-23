"""Cleanup leftover tempfile artifacts.

背景:
- アトミックセーブ中にプロセスが落ちる/ディスク満杯/権限エラー等が起きると、
  tempfile.mkstemp() が作った tmpXXXXXX.* が残ることがあります。
- 本体コードを複雑化させずに運用で回避したい場合、このスクリプトで後始末します。

注意:
- アプリ停止中に実行してください（書き込み中ファイルの誤削除を避けるため）。
- デフォルトは dry-run です（削除はしません）。

使い方例:
  python tools/cleanup_tmp_files.py --apply
  python tools/cleanup_tmp_files.py --apply --min-age 600
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import time
from pathlib import Path


DEFAULT_PATTERNS = [
    "tmp*.tmp",  # pdf-paraparatrans.py / modules/parapara_trans.py など
    "tmp*.json",  # modules 側の atomicsave_json (suffix=.json)
    "tmp*.txt",  # dict のアトミックセーブ等
]


def _repo_root() -> Path:
    # tools/ の1つ上をリポジトリルート想定
    return Path(__file__).resolve().parent.parent


def _default_data_dir(root: Path) -> Path:
    return Path(os.getenv("PARAPARATRANS_DATA_DIR", str(root / "data"))).resolve()


def _default_config_dir(root: Path) -> Path:
    return Path(os.getenv("PARAPARATRANS_CONFIG_DIR", str(root / "config"))).resolve()


def iter_candidates(base_dir: Path, patterns: list[str]) -> list[Path]:
    if not base_dir.exists() or not base_dir.is_dir():
        return []

    matched: list[Path] = []
    for child in base_dir.iterdir():
        if not child.is_file():
            continue
        name = child.name
        if any(fnmatch.fnmatch(name, pat) for pat in patterns):
            matched.append(child)

    return matched


def cleanup_dir(
    base_dir: Path,
    patterns: list[str],
    apply: bool,
    min_age_seconds: int,
) -> tuple[int, int]:
    now = time.time()

    removed = 0
    kept = 0

    for path in iter_candidates(base_dir, patterns):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            kept += 1
            continue

        if age < min_age_seconds:
            kept += 1
            continue

        if apply:
            try:
                path.unlink()
                removed += 1
            except OSError:
                kept += 1
        else:
            # dry-run
            kept += 1

    return removed, kept


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Remove leftover tmp*.* files in data/ and config/.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="実際に削除します（指定しない場合は dry-run）",
    )
    parser.add_argument(
        "--min-age",
        type=int,
        default=60,
        help="更新からこの秒数未満のファイルは触りません（既定: 60秒）",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="data ディレクトリ（省略時: PARAPARATRANS_DATA_DIR または ./data）",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help="config ディレクトリ（省略時: PARAPARATRANS_CONFIG_DIR または ./config）",
    )
    parser.add_argument(
        "--pattern",
        action="append",
        default=None,
        help="追加の削除パターン（複数指定可）。例: --pattern tmp*.bak",
    )

    args = parser.parse_args(argv)

    root = _repo_root()
    data_dir = Path(args.data_dir).resolve() if args.data_dir else _default_data_dir(root)
    config_dir = Path(args.config_dir).resolve() if args.config_dir else _default_config_dir(root)

    patterns = list(DEFAULT_PATTERNS)
    if args.pattern:
        patterns.extend(args.pattern)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] patterns={patterns} min_age={args.min_age}s")
    print(f"data_dir: {data_dir}")
    print(f"config_dir: {config_dir}")

    # 事前に候補一覧を表示（dry-runでもapplyでも）
    for label, base in [("data", data_dir), ("config", config_dir)]:
        candidates = iter_candidates(base, patterns)
        if not candidates:
            continue
        print(f"\n[{label}] candidates:")
        for p in sorted(candidates):
            try:
                age = int(time.time() - p.stat().st_mtime)
            except OSError:
                age = -1
            print(f"- {p.name} (age={age}s)")

    removed_total = 0
    kept_total = 0

    r, k = cleanup_dir(data_dir, patterns, args.apply, args.min_age)
    removed_total += r
    kept_total += k

    r, k = cleanup_dir(config_dir, patterns, args.apply, args.min_age)
    removed_total += r
    kept_total += k

    if args.apply:
        print(f"\nRemoved: {removed_total}, Kept/Skipped: {kept_total}")
    else:
        print(f"\n(dry-run) Would remove: {removed_total}, Kept/Skipped: {kept_total}")
        print("実行するには --apply を付けてください")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
