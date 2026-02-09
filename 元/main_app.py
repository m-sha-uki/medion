# main_app.py
import os
import re
import time
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from ttkthemes import ThemedTk
from bs4 import BeautifulSoup
import requests
from urllib.parse import urlparse, parse_qs
import pandas as pd
import subprocess
from download_path_utils import resolve_download_dir

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# ==============================================================================
# ユーザー設定値
# ==============================================================================
CHROMEDRIVER_PATH = r"G:\My Drive\Programing\Python\chromedriver\142.0.7444.162\chromedriver-win64\chromedriver.exe"
HEADLESS_MODE = False  # 要望によりブラウザを表示
SELENIUM_WAIT = 10
REQUESTS_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0"
GUI_THEME = "arc"
GUI_FONT_FAMILY = "Meiryo UI"
GUI_FONT_SIZE_NORMAL = 10

# Playwright用Chrome設定 (ダウンロード時のみ使用)
CHROME_EXEC_PATH_PW = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_USER_DATA_DIR_PW = r"C:\temp\chrome-pw"

# ==============================================================================
# アプリケーション内部設定
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "download_history.csv")
DOWNLOAD_SCRIPT = os.path.join(BASE_DIR, "03_book_image_downloader copy.py")
DEFAULT_DOWNLOAD_DIR = os.path.join(BASE_DIR, "DOWNLOAD")

try:
    import login_info
except ImportError:
    login_info = None

# ... アプリケーションクラス ...
class MainApplication(ThemedTk):
    def __init__(self):
        super().__init__(theme=GUI_THEME)
        self.title("MedicalOnline Downloader")
        self.geometry("900x750")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.worker_thread = None
        self.stop_worker = threading.Event()
        self.book_vars = []
        self.book_list_for_selection = []
        self.is_status_log_active = False
        self.download_dir_var = tk.StringVar(value=DEFAULT_DOWNLOAD_DIR)
        
        self.driver = None  # ブラウザインスタンス保持用
        self.create_widgets()
        
        # 起動直後にブラウザを開く
        self.after(500, self.start_auto_login_browser)

    def on_closing(self):
        if self.worker_thread and self.worker_thread.is_alive():
            if messagebox.askyesno("確認", "処理が実行中です。本当に終了しますか？"):
                self.stop_worker.set()
                if self.driver: 
                    try: self.driver.quit()
                    except: pass
                self.destroy()
        else:
            if self.driver: 
                try: self.driver.quit()
                except: pass
            self.destroy()

    def start_auto_login_browser(self):
        """起動時にブラウザを立ち上げてログインしておく"""
        def login_task():
            if self.driver: return
            self.log("[INFO] 自動ログインブラウザを起動中...")
            try:
                if not login_info:
                    self.log("[WARN] login_info.py が見つからないため自動ログインをスキップします")
                    return

                options = Options()
                # ユーザー設定に従う
                if HEADLESS_MODE:
                    options.add_argument("--headless=new")

                self.driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
                
                # ログイン処理
                try:
                    self.driver.get("https://www.medicalonline.jp/login/mypage")
                    # 既にログイン済みでもmypageに飛ばされるだけなので、ログインフォームがあるか確認
                    try:
                        WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.ID, "mypage_loginid")))
                        self.driver.find_element(By.ID, "mypage_loginid").send_keys(login_info.LOGIN_ID)
                        self.driver.find_element(By.ID, "mypage_passwd").send_keys(login_info.LOGIN_PW)
                        self.driver.find_element(By.CSS_SELECTOR, "button.button-login[name='submit']").click()
                        WebDriverWait(self.driver, 10).until_not(EC.presence_of_element_located((By.ID, "mypage_loginid")))
                        self.log("[INFO] ブラウザ起動・自動ログイン完了")
                    except TimeoutException:
                         self.log("[INFO] 既にログイン済み(起動時)")
                except Exception as e:
                    self.log(f"[WARN] 自動ログイン中にエラー: {e}")

            except Exception as e:
                self.log(f"[ERROR] ブラウザ起動失敗: {e}")
                self.driver = None

        threading.Thread(target=login_task, daemon=True).start()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding="10"); main_frame.pack(fill="both", expand=True)
        self.setup_frame = ttk.LabelFrame(main_frame, text="Step 1: 書籍リストの取得", padding="10"); self.setup_frame.pack(fill="x", padx=5, pady=5)

        # --- URL入力欄の動的追加・削除機能 ---
        ttk.Label(self.setup_frame, text="一覧ページURL:").grid(row=0, column=0, sticky="w", pady=2)
        self.url_input_container = ttk.Frame(self.setup_frame)
        self.url_input_container.grid(row=1, column=0, columnspan=5, sticky="we")
        self.url_entries = []

        def add_url_entry(url=""):
            row_frame = ttk.Frame(self.url_input_container)
            row_frame.pack(fill="x", expand=True, pady=2)
            entry = ttk.Entry(row_frame, width=80)
            entry.pack(side="left", fill="x", expand=True)
            entry.insert(0, url)
            
            remove_button = ttk.Button(row_frame, text="削除", command=lambda r=row_frame, e=entry: remove_url_entry(r, e))
            remove_button.pack(side="left", padx=5)
            
            self.url_entries.append(entry)
            # 削除ボタンの状態を更新
            update_remove_buttons()

        def remove_url_entry(row_frame, entry):
            row_frame.destroy()
            self.url_entries.remove(entry)
            # 削除ボタンの状態を更新
            update_remove_buttons()

        def update_remove_buttons():
            # エントリーが1つしかない場合は削除ボタンを無効化
            is_one_entry = len(self.url_entries) == 1
            for entry in self.url_entries:
                # entryの親(row_frame)の子ウィジェット(remove_button)を探す
                for widget in entry.master.winfo_children():
                    if isinstance(widget, ttk.Button):
                        widget.config(state=tk.DISABLED if is_one_entry else tk.NORMAL)

        add_url_entry() # 最初の入力欄を追加

        # --- ボタン類 ---
        button_frame = ttk.Frame(self.setup_frame)
        button_frame.grid(row=0, column=1, columnspan=4, sticky="e")
        ttk.Button(button_frame, text="URL入力欄を追加", command=add_url_entry).pack()

        ttk.Label(self.setup_frame, text="ログインID:").grid(row=2, column=0, sticky="w", pady=2)
        self.id_entry = ttk.Entry(self.setup_frame, width=40); self.id_entry.grid(row=3, column=0, sticky="w", pady=2); self.id_entry.insert(0, "dlowolxlowoly@gmail.com")
        ttk.Label(self.setup_frame, text="パスワード:").grid(row=2, column=1, sticky="w", pady=2)
        self.pw_entry = ttk.Entry(self.setup_frame, width=40, show="*"); self.pw_entry.grid(row=3, column=1, sticky="w", pady=2); self.pw_entry.insert(0, "masa19890601")
        self.start_button = ttk.Button(self.setup_frame, text="リスト取得開始", command=self.start_list_generation); self.start_button.grid(row=3, column=2, sticky="w", padx=10)
        self.direct_dl_button = ttk.Button(self.setup_frame, text="リストからDL", command=self.start_direct_download); self.direct_dl_button.grid(row=3, column=3, sticky="w", padx=5)
        self.cancel_button = ttk.Button(self.setup_frame, text="キャンセル", command=self.cancel_worker); self.cancel_button.grid(row=3, column=4, sticky="w", padx=5); self.cancel_button.config(state=tk.DISABLED)

        ttk.Label(self.setup_frame, text="DL保存先:").grid(row=4, column=0, sticky="w", pady=(10, 2))
        path_frame = ttk.Frame(self.setup_frame); path_frame.grid(row=5, column=0, columnspan=5, sticky="we"); path_frame.columnconfigure(0, weight=1)
        self.download_dir_entry = ttk.Entry(path_frame, textvariable=self.download_dir_var, width=80)
        self.download_dir_entry.grid(row=0, column=0, sticky="we", pady=2)
        ttk.Button(path_frame, text="参照...", command=self.browse_download_dir).grid(row=0, column=1, padx=5)

        self.selection_frame = ttk.LabelFrame(main_frame, text="Step 2: ダウンロードする書籍を選択", padding="10")
        log_frame = ttk.LabelFrame(main_frame, text="ログ", padding="10"); log_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, width=100, height=15, font=(GUI_FONT_FAMILY, GUI_FONT_SIZE_NORMAL), wrap=tk.WORD); self.log_text.pack(fill="both", expand=True)

    def log(self, msg, is_update=False): self.after(0, self._log_thread_safe, msg, is_update)
    def _log_thread_safe(self, msg, is_update):
        if is_update:
            # 既存の最後の行を削除して上書き
            self.log_text.delete("end-1c linestart", "end")
            self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}")
        else:
            self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see(tk.END)

    def set_ui_state(self, is_running):
        state = tk.DISABLED if is_running else tk.NORMAL
        self.start_button.config(state=state)
        self.direct_dl_button.config(state=state)
        self.cancel_button.config(state=tk.NORMAL if is_running else tk.DISABLED)

    def start_list_generation(self):
        urls = [entry.get().strip() for entry in self.url_entries if entry.get().strip()]
        if not urls:
            messagebox.showerror("エラー", "URLを1つ以上入力してください。")
            return
        self.set_ui_state(True)
        self.stop_worker.clear()
        self.worker_thread = threading.Thread(target=self._list_generation_worker, args=(urls, self.id_entry.get(), self.pw_entry.get()), daemon=True)
        self.worker_thread.start()

    def start_direct_download(self):
        download_dir = self.prepare_download_dir()
        if not download_dir:
            return
        self.set_ui_state(True); self.stop_worker.clear()
        self.worker_thread = threading.Thread(target=self._download_worker, args=([], True, download_dir), daemon=True)
        self.worker_thread.start()

    def cancel_worker(self):
        self.log("[INFO] 処理のキャンセルを要求しました..."); self.stop_worker.set(); self.cancel_button.config(state=tk.DISABLED)

    def _list_generation_worker(self, list_urls, login_id, login_pw):
        self.log("書籍リストの取得処理を開始します。")
        driver = None
        using_shared_driver = False

        try:
            if self.driver:
                driver = self.driver
                using_shared_driver = True
                self.log("[INFO] 起動済みのブラウザを使用します")
            else:
                options = Options()
                if HEADLESS_MODE: options.add_argument("--headless=new")
                driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
                self.log("[INFO] ChromeDriver起動完了")

            # ログイン確認・実行
            try:
                driver.get("https://www.medicalonline.jp/login/mypage")
                try:
                    WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.ID, "mypage_loginid")))
                    # ログインフォームがあれば入力
                    self.log("[INFO] ログインフォーム検出。ログインを実行します。")
                    driver.find_element(By.ID, "mypage_loginid").clear()
                    driver.find_element(By.ID, "mypage_loginid").send_keys(login_id)
                    driver.find_element(By.ID, "mypage_passwd").clear()
                    driver.find_element(By.ID, "mypage_passwd").send_keys(login_pw)
                    driver.find_element(By.CSS_SELECTOR, "button.button-login[name='submit']").click()
                    WebDriverWait(driver, SELENIUM_WAIT).until_not(EC.presence_of_element_located((By.ID, "mypage_loginid")))
                    self.log("[INFO] ログイン成功")
                except TimeoutException:
                    self.log("[INFO] 既にログイン済みです")
            except Exception as e:
                self.log(f"[WARN] ログインページの確認中にエラー: {e}")

            if self.stop_worker.is_set(): raise InterruptedError()
            
            driver.get("https://mol.medicalonline.jp/library/ebooks/")
            time.sleep(2)
            
            # UserID取得
            qs = parse_qs(urlparse(driver.current_url).query)
            user_id = qs.get('UserID', [None])[0]
            if not user_id: 
                # UserIDがない場合、もう一度URLを確認してみる（リダイレクト等の可能性）
                self.log("[WARN] UserIDが見つかりません。URLを再確認します...")
                qs = parse_qs(urlparse(driver.current_url).query)
                user_id = qs.get('UserID', [None])[0]

            if not user_id:
                raise ValueError("UserIDの取得に失敗 (URLにUserIDパラメータが含まれていません)")
            
            self.log(f"[INFO] UserID取得成功: {user_id}")

            all_links = set()
            for list_url in list_urls:
                if self.stop_worker.is_set(): break
                self.log(f"[INFO] '{list_url}' からリンクを収集中...")
                driver.get(re.sub(r'[?&]UserID=.*$', '', list_url))
                soup = BeautifulSoup(driver.page_source, "lxml")
                # リンク収集
                links_on_page = {a["href"] if a["href"].startswith("http") else "https://mol.medicalonline.jp" + a["href"] 
                                 for a in soup.find_all("a", href=True) 
                                 if "library/ebooks/detail?id=" in a["href"]}
                all_links.update(links_on_page)
                self.log(f"[INFO] {len(links_on_page)}件のリンクを発見。現在合計{len(all_links)}件。")

            if self.stop_worker.is_set(): raise InterruptedError()

            ok_links = []
            for idx, url in enumerate(sorted(list(all_links)), 1):
                if self.stop_worker.is_set(): break
                self.log(f"[{idx}/{len(all_links)}] 閲覧可能か判定中... | 有効: {len(ok_links)}", is_update=True)
                driver.get(url)
                try:
                    WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.XPATH, "//form[@name='bev_form_view'] | //span[contains(@class, 'button-uncontracted')] ")))
                    if driver.find_elements(By.XPATH, "//form[@name='bev_form_view']"):
                        clean_url = re.sub(r'[?&]UserID=.*$', '', url)
                        ok_links.append(f"{clean_url}{'&' if '?' in clean_url else '?'}UserID={user_id}")
                except TimeoutException: pass
            
            self.log(f"判定完了。閲覧可能な書籍が {len(ok_links)} 件見つかりました。", is_update=True)
            self.is_status_log_active = False
            self.after(0, self.prepare_selection_gui, ok_links)
            
        except Exception as e:
            self.log(f"[ERROR] リスト取得中にエラー: {e}")
        finally:
            if driver and not using_shared_driver:
                driver.quit()
            self.after(0, self.set_ui_state, False)

    def prepare_selection_gui(self, book_urls):
        self.log("[INFO] 既存の履歴と照合します...")
        all_books_info = [info for url in book_urls if (info := self._get_book_info_for_gui(url))]
        history_urls = set(pd.read_csv(HISTORY_FILE, encoding='utf-8-sig')['URL'].str.split('UserID=').str[0]) if os.path.exists(HISTORY_FILE) else set()
        
        new_books = []
        for book in all_books_info:
            base_url = book['URL'].split('UserID=')[0]
            if base_url not in history_urls:
                new_books.append(book)
            else:
                self.log(f"書籍名：{book['書籍名']} はすでにリストにあるためSkipしました")

        if not new_books: messagebox.showinfo("完了", "新しい書籍はありませんでした。"); return
        self.book_list_for_selection = new_books
        self.show_selection_gui()

    def _get_book_info_for_gui(self, url: str):
        try:
            r = requests.get(url.split("&", 1)[0], headers={"User-Agent": USER_AGENT}, timeout=REQUESTS_TIMEOUT); r.raise_for_status()
            soup = BeautifulSoup(r.content, "lxml")
            table = soup.find(lambda t: t.name == "table" and "table-dotted" in (t.get("class") or []))
            if not table: return None
            raw = {re.sub(r"\s+|\u3000", "", th.get_text(strip=True)): ("、".join([li.get_text(strip=True) for li in td.find_all("li")]) if key == "著者" else td.get_text(strip=True)) for tr in table.find_all("tr") if (th := tr.find("th")) and (td := tr.find("td")) and (key := re.sub(r"\s+|\u3000", "", th.get_text(strip=True)))}
            return {"書籍名": raw.get("書籍名", "N/A"), "著者": raw.get("著者", "N/A"), "URL": url}
        except Exception as e: self.log(f"[ERROR] {url} の情報取得に失敗: {e}"); return None

    def show_selection_gui(self):
        self.setup_frame.pack_forget(); self.selection_frame.pack(fill="both", expand=True, padx=5, pady=5)
        for widget in self.selection_frame.winfo_children(): widget.destroy()
        self.book_vars.clear()
        canvas = tk.Canvas(self.selection_frame, borderwidth=0, background="#ffffff"); self.selection_canvas = canvas
        list_frame = ttk.Frame(canvas); self.selection_list_frame = list_frame
        vsb = ttk.Scrollbar(self.selection_frame, orient="vertical", command=canvas.yview); canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True); canvas.create_window((4,4), window=list_frame, anchor="nw")
        list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))); self.bind_mousewheel(canvas, list_frame)
        style = ttk.Style(); style.configure("TCheckbutton", font=(GUI_FONT_FAMILY, GUI_FONT_SIZE_NORMAL))
        for i, book in enumerate(self.book_list_for_selection):
            var = tk.BooleanVar(value=True); self.book_vars.append(var)
            cb = ttk.Checkbutton(list_frame, text=f"{i+1}. {book.get('書籍名', 'N/A')}  |  {book.get('著者', 'N/A')}", variable=var, style="TCheckbutton"); cb.pack(anchor="w", padx=10, pady=4)
            self.bind_mousewheel(cb)
        button_frame = ttk.Frame(self.selection_frame); button_frame.pack(fill="x", pady=10)
        ttk.Button(button_frame, text="すべて選択", command=lambda: [var.set(True) for var in self.book_vars]).pack(side="left", padx=5)
        ttk.Button(button_frame, text="すべて解除", command=lambda: [var.set(False) for var in self.book_vars]).pack(side="left", padx=5)
        self.dl_button = ttk.Button(button_frame, text="確定してダウンロード開始", command=self.start_download); self.dl_button.pack(side="right", padx=5)

    def bind_mousewheel(self, *widgets):
        for widget in widgets: widget.bind("<MouseWheel>", self._on_mousewheel)
    def _on_mousewheel(self, event): self.selection_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def start_download(self):
        selected_books = [book for book, var in zip(self.book_list_for_selection, self.book_vars) if var.get()]
        if not selected_books: messagebox.showwarning("確認", "書籍が選択されていません。"); return
        if not messagebox.askyesno("最終確認", f"{len(selected_books)}件の書籍を処理します。よろしいですか？"): return
        download_dir = self.prepare_download_dir()
        if not download_dir:
            return
        self.set_ui_state(True)
        self.worker_thread = threading.Thread(target=self._download_worker, args=(selected_books, False, download_dir), daemon=True)
        self.worker_thread.start()

    def _download_worker(self, selected_books, is_direct_dl, download_dir):
        if not is_direct_dl:
            self.log("[INFO] 履歴ファイルへの追加を開始します。")
            full_details = [self._get_full_book_info(book['URL']) for book in selected_books]
            new_books = [b for b in full_details if b]
            if new_books:
                try:
                    header = pd.read_csv(HISTORY_FILE, encoding='utf-8-sig').columns.tolist()
                    new_df = pd.DataFrame(new_books).reindex(columns=header)
                    new_df.to_csv(HISTORY_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')
                except FileNotFoundError:
                    pd.DataFrame(new_books).to_csv(HISTORY_FILE, mode='w', header=True, index=False, encoding='utf-8-sig')
                self.log(f"{len(new_books)}件の書籍を履歴に追加しました。", is_update=True)
        
        self.log(f"[INFO] Playwrightによる画像のダウンロードを開始します... 保存先: {download_dir}")
        try:
            cmd = ['python', DOWNLOAD_SCRIPT, CHROME_EXEC_PATH_PW, CHROME_USER_DATA_DIR_PW, download_dir]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
            for line in iter(process.stdout.readline, ''):
                if line.endswith('\r'):
                    self.log(f"  [DL] {line.strip('\r\n')}", is_update=True)
                else:
                    self.log(f"  [DL] {line.strip()}")
            stderr = process.communicate()[1]
            if stderr: self.log(f"[DL ERROR] {stderr}")
        except Exception as e: self.log(f"[ERROR] ダウンロードスクリプトの実行に失敗: {e}")
        finally: self.after(0, self.reset_to_initial_state)

    def browse_download_dir(self):
        initial_dir = self.download_dir_var.get().strip() or DEFAULT_DOWNLOAD_DIR
        selected = filedialog.askdirectory(initialdir=initial_dir, title="ダウンロード先フォルダを選択")
        if selected:
            self.download_dir_var.set(selected)

    def prepare_download_dir(self):
        try:
            # download_path_utils経由で絶対パス化＋フォルダを先に作成する
            return resolve_download_dir(DEFAULT_DOWNLOAD_DIR, self.download_dir_var.get())
        except OSError as e:
            messagebox.showerror("エラー", f"ダウンロード先フォルダを作成できませんでした:\n{e}")
            return None

    def _get_full_book_info(self, url):
        try:
            r = requests.get(url.split("&", 1)[0], headers={"User-Agent": USER_AGENT}, timeout=REQUESTS_TIMEOUT); r.raise_for_status()
            soup = BeautifulSoup(r.content, "lxml")
            table = soup.find(lambda t: t.name == "table" and "table-dotted" in (t.get("class") or []))
            raw = {re.sub(r"\s+|\u3000", "", th.get_text(strip=True)): ("、".join([li.get_text(strip=True) for li in td.find_all("li")]) if key == "著者" else td.get_text(strip=True)) for tr in table.find_all("tr") if (th := tr.find("th")) and (td := tr.find("td")) and (key := re.sub(r"\s+|\u3000", "", th.get_text(strip=True)))}
            base_url = url.split('UserID=')[0] + 'UserID='
            return {"状態": "", "書籍名": raw.get("書籍名", ""), "発行日": raw.get("発行日", "").replace("/", "-"), "著者": raw.get("著者", ""), "ISBN": re.sub(r"[^0-9Xx\-\\]", "", raw.get("ISBN", "")), "ページ数": (lambda v: int(m.group()) if (m := re.search(r"\d+", v)) else 0)(raw.get("ページ数", "")), "URL": base_url}
        except Exception: return None

    def reset_to_initial_state(self):
        self.selection_frame.pack_forget()
        self.setup_frame.pack(fill="x", padx=5, pady=5)
        self.set_ui_state(False)
        messagebox.showinfo("完了", "すべての処理が完了しました。")

if __name__ == "__main__":
    app = MainApplication()
    app.mainloop()
