# GitHub Codespaces での運用メモ（停止・バックアップ）

このプロジェクトは Codespaces 上でも動きますが、**コストとデータ消失リスク**があるため、最低限このページの内容を押さえるのをおすすめします。

## 1) 作業が終わったら停止する（推奨）

- ブラウザのタブを閉じただけでは Codespace が動き続けることがあります。
- **作業が終わったら停止**すると、無駄な課金やリソース消費を避けられます。

### 停止方法（GitHub 画面）

1. GitHub 右上のアイコン → **Your codespaces**（または https://github.com/codespaces ）
2. 対象の Codespace の **…** メニュー → **Stop codespace**

### 停止方法（VS Code Web 画面）

- コマンドパレット（`F1` または `Ctrl+Shift+P`）で `Codespaces: Stop Current Codespace` を実行

## 2) コンテナ削除に備えて、定期的に `data/` と `config/` をダウンロード（推奨）

Codespace を **削除（Delete）** すると、その Codespace 内のファイルは消えます。

このアプリで重要になりがちなもの:
- `data/` : 取り込んだPDFや生成されたJSON/HTMLなど
- `config/` : 辞書（`dict.txt`）や設定

### かんたんバックアップ（VS Code のファイルツリーから）

- ファイルツリーで `data` や `config` を右クリック → **Download…**（表示される場合）
- 大きいフォルダは時間がかかることがあります

### まとめてZIPを作ってダウンロード（ターミナル）

VS Code のターミナルで以下を実行すると、`paraparatrans-backup.zip` を作れます。

```bash
python - << 'PY'
import os
import zipfile

def add_dir(zipf, dir_path):
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d not in {"__pycache__"}]
        for name in files:
            if name.endswith(('.pyc', '.pyo')):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, '.')
            zipf.write(full, rel)

with zipfile.ZipFile('paraparatrans-backup.zip', 'w', compression=zipfile.ZIP_DEFLATED) as z:
    if os.path.isdir('data'):
        add_dir(z, 'data')
    if os.path.isdir('config'):
        add_dir(z, 'config')

print('Created: paraparatrans-backup.zip')
PY
```

作成後、ファイルツリーに出てくる `paraparatrans-backup.zip` を右クリックしてダウンロードできます。

## 3) 注意: 料金・ポート公開

- Codespaces は課金が発生する場合があります（条件はGitHub側の最新情報を参照）。
- アプリは `http://localhost:5077/` を使います。開けない場合は **Ports** で 5077 を確認してください。
