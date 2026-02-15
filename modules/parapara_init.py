import os
import sys
import json


def parapara_init(data_folder, settings_folder=None):
    if settings_folder is None:
        settings_folder = data_folder
    # 1. paraparatrans.settings.jsonを読み込み。存在しなければ空の辞書を生成。
    settings_path = os.path.join(settings_folder, "paraparatrans.settings.json")
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    else:
        settings = {}

    settings["files"] = {}

    # 2. 渡されたフォルダ配下のpdfファイルのリストを取得。
    ignored_dirs = {"backup", "structure", "doc_structure", "__pycache__", "old"}

    def _should_skip_dir(name: str) -> bool:
        if not name:
            return True
        if name.startswith("."):
            return True
        return name in ignored_dirs

    pdf_files = []
    for root, dirs, files in os.walk(data_folder):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]
        for fname in files:
            if fname.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, fname))

    # 

    # 3. リストをループしてpdfと同名のjsonをdataに読み込み、またはデフォルト値を設定
    for pdf_file in pdf_files:
        rel_path = os.path.relpath(pdf_file, data_folder)
        file_key = os.path.splitext(rel_path)[0].replace(os.sep, "/")
        json_file = os.path.splitext(pdf_file)[0] + ".json"

        if os.path.exists(json_file):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 4. data["version"]が1.0.0でなければ以降の処理はスキップ
                if data.get("version") != "2.0.0":
                    # JSONファイルはあるがバージョンが異なる場合はスキップ
                    continue

                # 5. ファイル名をキーとするfiles要素に各jsonから項目をセット
                settings["files"][file_key] = {
                    "version": data.get("version", ""),
                    "src_filename": data.get("src_filename", ""),
                    "title": data.get("title", ""),
                    "page_count": data.get("page_count", 0),
                    "trans_status_counts": data.get("trans_status_counts", {}),
                }
            except json.JSONDecodeError:
                # JSONファイルが破損している場合などはデフォルト値を設定
                print(f"Warning: Could not decode JSON file: {json_file}. Using default values.")
                settings["files"][file_key] = {
                    "version": "",
                    "src_filename": file_key,
                    "title": file_key,
                    "page_count": 0,
                    "trans_status_counts": {},
                }
        else:
            # JSONファイルが存在しない場合、デフォルト値を設定
            settings["files"][file_key] = {
                "version": "",
                "src_filename": file_key,
                "title": file_key,
                "page_count": 0,
                "trans_status_counts": {},
            }

    # 6. paraparatrans.settings.jsonに出力
    os.makedirs(settings_folder, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)
    
    return settings

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用法: python parapara_init_all.py <フォルダ名>")
        sys.exit(1)

    data_folder = sys.argv[1]
    parapara_init(data_folder)
