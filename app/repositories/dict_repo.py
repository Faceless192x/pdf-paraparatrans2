import os
import tempfile
from typing import List

DEFAULT_DICT_HEADER = "#英語\t#日本語\t#状態\t#出現回数\n"


def load_dict(dict_path: str) -> List[List]:
    dict_data: List[List] = []
    if not os.path.exists(dict_path):
        return dict_data
    with open(dict_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                count = 0
                if len(parts) > 3 and parts[3].isdigit():
                    count = int(parts[3])
                dict_data.append([parts[0], parts[1], int(parts[2]), count])
    return dict_data


def save_dict(dict_path: str, dict_data: List[List]) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(dict_path), suffix=".txt", text=True)
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
        for entry in dict_data:
            count = entry[3] if len(entry) > 3 else 0
            tmp_file.write(f"{entry[0]}\t{entry[1]}\t{entry[2]}\t{count}\n")
    os.replace(tmp_path, dict_path)


def ensure_dict_file(dict_path: str, *, header: str = DEFAULT_DICT_HEADER) -> None:
    os.makedirs(os.path.dirname(dict_path), exist_ok=True)
    if not os.path.exists(dict_path):
        with open(dict_path, "w", encoding="utf-8") as f:
            f.write(header)
