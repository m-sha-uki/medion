# 2025/11/14 18:30
# ==========================================================
# MedicalOnline Book Downloader（Refactored + Auto Login）
# Playwright + PNG URL Hook + medium 固定 + 並列DL
# login_info.py にログイン情報を分離した安全構造
# ==========================================================

import os
import re
import csv
import time
import tkinter as tk
from tkinter import ttk, messagebox
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright
import traceback
import requests
from download_path_utils import parse_downloader_args

# --- ログイン情報読み込み ---
import login_info  # LOGIN_ID / LOGIN_PW を参照

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "download_history.csv")
DEFAULT_DOWNLOAD_DIR = os.path.join(BASE_DIR, "DOWNLOAD")
DOWNLOAD_DIR = DEFAULT_DOWNLOAD_DIR

GLOBAL_CHROME_EXEC_PATH = ""
GLOBAL_CHROME_USER_DATA_DIR = ""

# --- パラメータ ---
REQUEST_TIMEOUT = 4
MAX_DL_RETRY = 6
MAX_WORKERS = 4
PNG_DETECT_WAIT = 0.8


# ==========================================================
# UI（Chrome 手動起動の案内）
# ==========================================================
def show_instruction_modal():
    root = tk.Tk()
    root.withdraw()

    modal = tk.Toplevel(root)
    modal.title("準備のお願い")
    modal.geometry("620x310")  # 少し高さを増やす
    modal.resizable(False, False)
    modal.grab_set()

    cmd = f'"{GLOBAL_CHROME_EXEC_PATH}" --remote-debugging-port=9222 --user-data-dir="{GLOBAL_CHROME_USER_DATA_DIR}"'
    ps_cmd = f'& {cmd}'

    msg = """Playwrightでのダウンロードを開始する前に以下を実行してください。

1. 下記コマンドを PowerShell で実行し Chrome を起動する。
2. MedicalOnline にログインする（自動ログイン機能つき）。
3. ログイン後、この画面の OK を押す。
"""

    ttk.Label(modal, text=msg, wraplength=580, justify="left").pack(pady=10)

    frame = ttk.Frame(modal)
    frame.pack(fill="x", padx=10)

    ent = ttk.Entry(frame, width=60)
    ent.insert(0, cmd)
    ent.config(state="readonly")
    ent.pack(side="left", fill="x", expand=True)

    copy_status_label = ttk.Label(modal, text="", foreground="red")
    copy_status_label.pack(pady=(5, 0))

    def cp():
        root.clipboard_clear()
        root.clipboard_append(ps_cmd)
        copy_status_label.config(text="※コピーしました")

    ttk.Button(frame, text="コピー", command=cp).pack(side="right", padx=5)

    btn_frame = ttk.Frame(modal)
    btn_frame.pack(pady=15)

    result = {"ok": False}
    ttk.Button(btn_frame, text="OK", width=10,
               command=lambda: (result.update(ok=True), modal.destroy())).pack(side="left", padx=5)
    ttk.Button(btn_frame, text="Cancel", width=10,
               command=lambda: modal.destroy()).pack(side="right", padx=5)

    root.wait_window(modal)
    return result["ok"]


# ==========================================================
# 書誌ファイル読込
# ==========================================================
def load_targets(history_path):
    if not os.path.exists(history_path):
        print(f"[ERROR] {history_path} がありません")
        return []
    targets = []
    with open(history_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row["状態"].strip():
                row["ISBN"] = row["ISBN"].strip()
                targets.append(row)
    return targets


# ==========================================================
# 自動ログイン
# ==========================================================
def auto_login_if_needed(page):
    LOGIN_URL = "https://www.medicalonline.jp/login/mypage"

    print("[INFO] MedicalOnline 自動ログインチェックを開始")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(800)

    # 入力欄がある？
    id_box = page.locator("#mypage_loginid")
    pw_box = page.locator("#mypage_passwd")

    if id_box.count() == 0 or pw_box.count() == 0:
        print("[INFO] ログインフォームなし → ログイン済と判断")
        return

    print("[INFO] ログインフォーム検出 → 自動ログイン実行")

    id_box.fill(login_info.LOGIN_ID)
    pw_box.fill(login_info.LOGIN_PW)

    btn = page.locator("button.button-login[name='submit']")
    if btn.count() > 0:
        btn.click()
        print("[INFO] ログインボタンをクリックしました")
    else:
        print("[WARN] ログインボタンが見つからないためスキップ")

    page.wait_for_timeout(1500)
    print("[INFO] 自動ログイン完了")


# ==========================================================
# PNG URL 自動検出
# ==========================================================
def collect_png_urls(popup):
    urls = []

    def on_req(req):
        u = req.url
        if u.endswith(".png") and "/thumb/" not in u:
            urls.append(u)

    popup.on("request", on_req)

    popup.mouse.click(450, 400)
    popup.keyboard.press("PageDown")
    popup.wait_for_timeout(int(PNG_DETECT_WAIT * 1000))

    popup.remove_listener("request", on_req)
    return urls


# ==========================================================
# 並列ダウンロード
# ==========================================================
def download_pngs(title, base, folder, page_count):
    headers = {"User-Agent": "Mozilla/5.0"}

    def dl(i):
        url = f"{base}_{i}.png"
        save_path = os.path.join(folder, f"{i:04d}.png")

        for attempt in range(1, MAX_DL_RETRY + 1):
            try:
                r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                if r.status_code == 200:
                    with open(save_path, "wb") as f:
                        f.write(r.content)
                    return (i, True)
            except:
                pass
            time.sleep(0.3)
        return (i, False)

    fails = []
    completed_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(dl, i): i for i in range(1, page_count + 1)}
        for fut in as_completed(futs):
            i, ok = fut.result()
            completed_count += 1
            if ok:
                print(f"{title} をDL中 [{completed_count:04d}/{page_count:04d}]", end='\r', flush=True)
            else:
                fails.append(i)
                print(f"[FAIL] {title} のDLに失敗 [{i:04d}/{page_count:04d}]", end='\r', flush=True) # 失敗時は別途表示
        print(flush=True) # 処理完了後に改行

    if fails:
        fp = os.path.join(folder, "failed_pages.txt")
        with open(fp, "w") as f:
            for i in fails:
                f.write(f"{base}_{i}.png\n")
        print("[WARN] DL失敗ページあり → failed_pages.txt に記録")

    return len(fails) != page_count


# ==========================================================
# 本1冊の処理
# ==========================================================
def process_book(page, book):
    title = book["書籍名"]
    url = book["URL"]
    isbn = book["ISBN"]

    print(f"\n==== {title} ({isbn}) ====")

    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)

    btn = page.locator("a.button.button-icon.button-ebooks", has_text="閲覧")
    if btn.count() == 0:
        print("[ERROR] 閲覧ボタンが見つからないためスキップ")
        return False

    with page.expect_popup() as pop_info:
        btn.first.click()

    popup = pop_info.value
    popup.wait_for_load_state("domcontentloaded")
    popup.bring_to_front()
    popup.wait_for_timeout(800)

    png_urls = collect_png_urls(popup)
    if not png_urls:
        print("[ERROR] PNG 検出ゼロ → スキップ")
        popup.close()
        return False

    sample = png_urls[0]
    m = re.search(r"_(\d+)\.png$", sample)
    if not m:
        print("[ERROR] PNG URL の解析に失敗")
        popup.close()
        return False

    base = sample[:m.start()]
    base = base.replace("/original/", "/medium/")
    print(f"[INFO] base URL = {base}")

    # CSVからページ数を取得。取得できない場合は800をデフォルト値とする
    try:
        page_count_str = book.get("ページ数", "800")
        if not page_count_str or not page_count_str.strip():
             page_count = 800
             print("[WARN] ページ数が空のため、デフォルト値(800)で試行します。")
        else:
            page_count = int(page_count_str)
            if page_count <= 0:
                page_count = 800
                print(f"[WARN] ページ数が0以下のため({page_count_str})、デフォルト値(800)で試行します。")
    except (ValueError, TypeError):
        page_count = 800
        print(f"[WARN] ページ数({book.get('ページ数')})の変換に失敗したため、デフォルト値(800)で試行します。")

    save_dir = os.path.join(DOWNLOAD_DIR, re.sub(r'[\\/*?:":<>|]', "_", f"{title}_{isbn}"))
    os.makedirs(save_dir, exist_ok=True)

    ok = download_pngs(title, base, save_dir, page_count)

    popup.close()
    return ok


# ==========================================================
# CSV 更新
# ==========================================================
def update_history(history_path, book):
    try:
        with open(history_path, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"[ERROR] 履歴ファイルが見つかりません: {history_path}")
        return False

    for r in rows:
        if r["ISBN"].strip() == book["ISBN"].strip():
            r["状態"] = "D"

    while True:
        try:
            with open(history_path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows(rows)
            print("[INFO] 履歴CSVを更新しました")
            return True  # 成功
        except PermissionError:
            root = tk.Tk()
            root.withdraw()
            should_retry = messagebox.askretrycancel(
                "CSV書き込みエラー",
                "history.csvへの書き込みに失敗しました。\n\n"
                "ファイルがExcelなどで開かれている可能性があります。\n"
                "ファイルを閉じてから「再試行」を押してください。"
            )
            root.destroy()
            if not should_retry:
                print("[ERROR] CSVの更新がユーザーによってキャンセルされました。")
                return False  # ユーザーがキャンセル
        except Exception as e:
            messagebox.showerror("CSV書き込みエラー", f"予期せぬエラーが発生しました: {e}")
            return False


# ==========================================================
# メイン
# ==========================================================
def main(args=None):
    global GLOBAL_CHROME_EXEC_PATH, GLOBAL_CHROME_USER_DATA_DIR, DOWNLOAD_DIR

    import sys
    cli_args = sys.argv[1:] if args is None else list(args)

    try:
        chrome_path, user_data_dir, download_dir = parse_downloader_args(cli_args, DEFAULT_DOWNLOAD_DIR)
    except ValueError as exc:
        print("使用法: python refactored_book_downloader.py <chrome.exe> <user_data_dir> [download_dir]")
        print(f"詳細: {exc}")
        return

    GLOBAL_CHROME_EXEC_PATH = chrome_path
    GLOBAL_CHROME_USER_DATA_DIR = user_data_dir
    DOWNLOAD_DIR = download_dir
    print(f"[INFO] DL保存先: {DOWNLOAD_DIR}")

    if not show_instruction_modal():
        print("キャンセルされました")
        return

    targets = load_targets(HISTORY_FILE)
    if not targets:
        print("未DL書籍なし")
        return

    print(f"{len(targets)} 件の書籍を処理します")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.new_page()

            # ★ 自動ログイン処理（必要な場合のみ実行）
            auto_login_if_needed(page)

            for book in targets:
                ok = process_book(page, book)
                if ok:
                    if not update_history(HISTORY_FILE, book):
                        print("[INFO] CSV更新がキャンセルされたため、全体の処理を中断します。")
                        break  # ループを抜ける

        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("致命的エラー", str(e))
        finally:
            print("\n[完了] すべての処理が終了しました")


if __name__ == "__main__":
    main()
