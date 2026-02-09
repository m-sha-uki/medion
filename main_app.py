# main_app.py
# 作成日時: 2026-01-12 08:14:33
# 更新履歴:
# - 2026-01-12 08:14:33 - ChromeDriverパスの修正（Gドライブ→Hドライブ）
# - 2026-01-12 08:17:56 - ChromeDriverの自動バージョン管理機能を追加（webdriver-manager使用）
# - 2026-01-12 11:38:48 - GUIにヘッドレスモード選択チェックボックスを追加
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
import json
from download_path_utils import resolve_download_dir

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False

# ==============================================================================
# ユーザー設定値（プロファイル対応）
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "configs")
CONFIG_EXAMPLE_FILE = os.path.join(BASE_DIR, "config.json.example")

def get_default_config():
    """デフォルト設定値を返す"""
    return {
        "CHROMEDRIVER_PATH": r"H:\My Drive\Programing\Python\chromedriver\142.0.7444.162\chromedriver-win64\chromedriver.exe",
        "HEADLESS_MODE": True,
        "SELENIUM_WAIT": 10,
        "REQUESTS_TIMEOUT": 20,
        "USER_AGENT": "Mozilla/5.0",
        "GUI_THEME": "arc",
        "GUI_FONT_FAMILY": "Meiryo UI",
        "GUI_FONT_SIZE_NORMAL": 10,
        "CHROME_EXEC_PATH_PW": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "CHROME_USER_DATA_DIR_PW": r"C:\temp\chrome-pw"
    }

def get_profile_list():
    """利用可能なプロファイル一覧を取得"""
    profiles = []
    # configsディレクトリからプロファイルを検索
    if os.path.exists(CONFIG_DIR):
        for filename in os.listdir(CONFIG_DIR):
            if filename.startswith("config_") and filename.endswith(".json"):
                profile_name = filename[7:-5]  # "config_" と ".json" を除去
                profiles.append(profile_name)
    # ルートディレクトリのconfig.jsonも確認（後方互換性）
    root_config = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(root_config):
        profiles.append("default")
    return sorted(profiles) if profiles else ["default"]

def get_config_file_path(profile_name):
    """プロファイル名から設定ファイルのパスを取得"""
    if profile_name == "default":
        return os.path.join(BASE_DIR, "config.json")
    else:
        # configsディレクトリが存在しない場合は作成
        if not os.path.exists(CONFIG_DIR):
            os.makedirs(CONFIG_DIR, exist_ok=True)
        return os.path.join(CONFIG_DIR, f"config_{profile_name}.json")

def load_config(profile_name="default"):
    """指定されたプロファイルの設定ファイルを読み込む"""
    default_config = get_default_config()
    config_file = get_config_file_path(profile_name)
    
    # 設定ファイルが存在する場合は読み込む
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                # デフォルト値とマージ（ユーザー設定を優先）
                config = {**default_config, **user_config}
                return config
        except Exception as e:
            print(f"[WARN] 設定ファイルの読み込みに失敗しました: {e}")
            print("[INFO] デフォルト設定を使用します。")
            return default_config
    
    # 設定ファイルが存在しない場合は、テンプレートから作成を試みる
    if os.path.exists(CONFIG_EXAMPLE_FILE):
        try:
            import shutil
            shutil.copy(CONFIG_EXAMPLE_FILE, config_file)
            print(f"[INFO] 設定ファイルを {CONFIG_EXAMPLE_FILE} から作成しました: {config_file}")
            print(f"[INFO] {config_file} を編集して、各PCの設定に合わせてください。")
            with open(config_file, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                config = {**default_config, **user_config}
                return config
        except Exception as e:
            print(f"[WARN] 設定ファイルの作成に失敗しました: {e}")
            print("[INFO] デフォルト設定を使用します。")
    else:
        # テンプレートが存在しない場合は、デフォルト値から設定ファイルを作成
        try:
            # configsディレクトリが存在しない場合は作成
            config_dir = os.path.dirname(config_file)
            if not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            print(f"[INFO] 設定ファイル {config_file} を自動作成しました。")
            print(f"[INFO] {config_file} を編集して、各PCの設定に合わせてください。")
        except Exception as e:
            print(f"[WARN] 設定ファイルの作成に失敗しました: {e}")
            print("[INFO] デフォルト設定を使用します。")
    
    return default_config

# デフォルト設定（GUIテーマなど初期表示用）
_default_config = load_config("default")
GUI_THEME = _default_config.get("GUI_THEME", "arc")
GUI_FONT_FAMILY = _default_config.get("GUI_FONT_FAMILY", "Meiryo UI")
GUI_FONT_SIZE_NORMAL = _default_config.get("GUI_FONT_SIZE_NORMAL", 10)

# ==============================================================================
# アプリケーション内部設定
# ==============================================================================
# BASE_DIRは既に上で定義済み
HISTORY_FILE = os.path.join(BASE_DIR, "download_history.csv")
DOWNLOAD_SCRIPT = os.path.join(BASE_DIR, "03_book_image_downloader copy.py")
DEFAULT_DOWNLOAD_DIR = os.path.join(BASE_DIR, "DOWNLOAD")

# --- アプリケーションクラス ---
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
        
        # プロファイル管理
        self.current_profile = "default"
        self.profile_var = tk.StringVar(value=self.current_profile)
        self.load_profile_config(self.current_profile)
        
        self.headless_mode_var = tk.BooleanVar(value=self.config.get("HEADLESS_MODE", True))
        self.create_widgets()
        # 起動時にバージョンチェック
        self.after(1000, self.check_chromedriver_version)
    
    def load_profile_config(self, profile_name):
        """プロファイルの設定を読み込む"""
        self.current_profile = profile_name
        self.config = load_config(profile_name)
        # 設定値をインスタンス変数として保持
        self.CHROMEDRIVER_PATH = self.config.get("CHROMEDRIVER_PATH", "")
        self.HEADLESS_MODE = self.config.get("HEADLESS_MODE", True)
        self.SELENIUM_WAIT = self.config.get("SELENIUM_WAIT", 10)
        self.REQUESTS_TIMEOUT = self.config.get("REQUESTS_TIMEOUT", 20)
        self.USER_AGENT = self.config.get("USER_AGENT", "Mozilla/5.0")
        self.CHROME_EXEC_PATH_PW = self.config.get("CHROME_EXEC_PATH_PW", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        self.CHROME_USER_DATA_DIR_PW = self.config.get("CHROME_USER_DATA_DIR_PW", r"C:\temp\chrome-pw")
    
    def on_profile_changed(self, *args):
        """プロファイル変更時の処理"""
        new_profile = self.profile_var.get()
        if new_profile != self.current_profile:
            self.log(f"[INFO] プロファイルを変更しました: {new_profile}")
            self.load_profile_config(new_profile)
            # ヘッドレスモードのチェックボックスを更新
            self.headless_mode_var.set(self.HEADLESS_MODE)
            self.log(f"[INFO] ChromeDriverパス: {self.CHROMEDRIVER_PATH}")
            self.log(f"[INFO] Chrome実行パス: {self.CHROME_EXEC_PATH_PW}")
    
    def get_chrome_version(self):
        """Chromeのバージョンを取得"""
        try:
            chrome_path = self.CHROME_EXEC_PATH_PW
            if not os.path.exists(chrome_path):
                self.log(f"[WARN] Chrome実行ファイルが見つかりません: {chrome_path}")
                return None
            
            # Chromeのバージョンを取得（--versionオプション）
            # タイムアウトを30秒に延長（Chromeの起動が遅い場合があるため）
            result = subprocess.run([chrome_path, "--version"], 
                                  capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                # 出力例: "Google Chrome 131.0.6778.85"
                version_match = re.search(r'(\d+)\.(\d+)\.(\d+)\.(\d+)', result.stdout)
                if version_match:
                    return version_match.group(0)  # 完全なバージョン文字列
                # メジャーバージョンのみ
                major_match = re.search(r'(\d+)\.(\d+)\.', result.stdout)
                if major_match:
                    return major_match.group(0).rstrip('.')
            else:
                self.log(f"[WARN] Chromeバージョン取得コマンドがエラーを返しました: returncode={result.returncode}, stderr={result.stderr}")
            return None
        except subprocess.TimeoutExpired:
            self.log(f"[WARN] Chromeバージョンの取得がタイムアウトしました（30秒）。Chromeの起動に時間がかかっている可能性があります。")
            return None
        except FileNotFoundError:
            self.log(f"[WARN] Chrome実行ファイルが見つかりません: {chrome_path}")
            return None
        except Exception as e:
            self.log(f"[WARN] Chromeバージョンの取得に失敗: {e}")
            return None
    
    def get_chromedriver_version(self, chromedriver_path):
        """ChromeDriverのバージョンを取得"""
        try:
            if not chromedriver_path or not os.path.exists(chromedriver_path):
                return None
            
            result = subprocess.run([chromedriver_path, "--version"], 
                                  capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                # 出力例: "ChromeDriver 131.0.6778.85 (abc123def456)"
                version_match = re.search(r'(\d+)\.(\d+)\.(\d+)\.(\d+)', result.stdout)
                if version_match:
                    return version_match.group(0)
                # メジャーバージョンのみ
                major_match = re.search(r'(\d+)\.(\d+)\.', result.stdout)
                if major_match:
                    return major_match.group(0).rstrip('.')
            else:
                self.log(f"[WARN] ChromeDriverバージョン取得コマンドがエラーを返しました: returncode={result.returncode}, stderr={result.stderr}")
            return None
        except subprocess.TimeoutExpired:
            self.log(f"[WARN] ChromeDriverバージョンの取得がタイムアウトしました（30秒）。")
            return None
        except FileNotFoundError:
            self.log(f"[WARN] ChromeDriver実行ファイルが見つかりません: {chromedriver_path}")
            return None
        except Exception as e:
            self.log(f"[WARN] ChromeDriverバージョンの取得に失敗: {e}")
            return None
    
    def check_chromedriver_version(self):
        """起動時にChromeとChromeDriverのバージョンをチェック"""
        chrome_version = self.get_chrome_version()
        if not chrome_version:
            return
        
        driver_version = None
        if self.CHROMEDRIVER_PATH and os.path.exists(self.CHROMEDRIVER_PATH):
            driver_version = self.get_chromedriver_version(self.CHROMEDRIVER_PATH)
        
        if chrome_version and driver_version:
            # メジャーバージョンを比較（例: 131.0.6778.85 -> 131）
            chrome_major = chrome_version.split('.')[0]
            driver_major = driver_version.split('.')[0]
            
            if chrome_major != driver_major:
                self.log(f"[WARN] ChromeとChromeDriverのバージョンが一致しません。")
                self.log(f"[WARN] Chrome: {chrome_version} (メジャー: {chrome_major})")
                self.log(f"[WARN] ChromeDriver: {driver_version} (メジャー: {driver_major})")
                self.log(f"[INFO] 「ChromeDriver更新」ボタンで更新できます。")
        elif chrome_version and not driver_version:
            self.log(f"[INFO] Chromeバージョン: {chrome_version}")
            self.log(f"[INFO] ChromeDriverが見つかりません。更新が必要かもしれません。")
    
    def update_chromedriver(self):
        """Chromeのバージョンに合わせてChromeDriverを更新"""
        if not WEBDRIVER_MANAGER_AVAILABLE:
            messagebox.showerror("エラー", "webdriver-managerがインストールされていません。\n'pip install webdriver-manager' でインストールしてください。")
            return
        
        self.log("[INFO] ChromeDriverの更新を開始します...")
        
        # Chromeのバージョンを取得
        chrome_version = self.get_chrome_version()
        if not chrome_version:
            messagebox.showerror("エラー", "Chromeのバージョンを取得できませんでした。\nChromeのパスを確認してください。")
            return
        
        self.log(f"[INFO] Chromeバージョン: {chrome_version}")
        
        # 現在のChromeDriverのバージョンを確認
        current_driver_version = None
        if self.CHROMEDRIVER_PATH and os.path.exists(self.CHROMEDRIVER_PATH):
            current_driver_version = self.get_chromedriver_version(self.CHROMEDRIVER_PATH)
            if current_driver_version:
                self.log(f"[INFO] 現在のChromeDriverバージョン: {current_driver_version}")
        
        # webdriver-managerでChromeDriverをダウンロード
        try:
            self.log("[INFO] ChromeDriverをダウンロード中...")
            driver_manager = ChromeDriverManager()
            new_driver_path = driver_manager.install()
            self.log(f"[INFO] 新しいChromeDriverをダウンロードしました: {new_driver_path}")
            
            # 新しいChromeDriverのバージョンを確認
            new_driver_version = self.get_chromedriver_version(new_driver_path)
            if new_driver_version:
                self.log(f"[INFO] 新しいChromeDriverバージョン: {new_driver_version}")
            
            # 設定ファイルのパスを更新するか確認
            if messagebox.askyesno("確認", 
                f"ChromeDriverの更新が完了しました。\n\n"
                f"Chromeバージョン: {chrome_version}\n"
                f"新しいChromeDriver: {new_driver_path}\n\n"
                f"設定ファイルのパスを更新しますか？"):
                
                # 設定ファイルを更新
                config_file = get_config_file_path(self.current_profile)
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    
                    config['CHROMEDRIVER_PATH'] = new_driver_path
                    
                    with open(config_file, 'w', encoding='utf-8') as f:
                        json.dump(config, f, indent=2, ensure_ascii=False)
                    
                    # 設定を再読み込み
                    self.load_profile_config(self.current_profile)
                    self.log(f"[INFO] 設定ファイルを更新しました: {config_file}")
                    messagebox.showinfo("完了", "設定ファイルを更新しました。")
                except Exception as e:
                    self.log(f"[ERROR] 設定ファイルの更新に失敗: {e}")
                    messagebox.showerror("エラー", f"設定ファイルの更新に失敗しました:\n{e}")
            else:
                self.log("[INFO] 設定ファイルの更新をスキップしました。")
                
        except Exception as e:
            self.log(f"[ERROR] ChromeDriverの更新に失敗: {e}")
            messagebox.showerror("エラー", f"ChromeDriverの更新に失敗しました:\n{e}")
    
    def add_profile(self):
        """新しいプロファイルを追加"""
        dialog = tk.Toplevel(self)
        dialog.title("プロファイル追加")
        dialog.geometry("400x150")
        dialog.transient(self)
        dialog.grab_set()
        
        ttk.Label(dialog, text="プロファイル名:").pack(pady=10)
        name_entry = ttk.Entry(dialog, width=30)
        name_entry.pack(pady=5)
        name_entry.focus()
        
        def save_profile():
            profile_name = name_entry.get().strip()
            if not profile_name:
                messagebox.showerror("エラー", "プロファイル名を入力してください。", parent=dialog)
                return
            
            # 無効な文字をチェック
            invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
            if any(char in profile_name for char in invalid_chars):
                messagebox.showerror("エラー", f"プロファイル名に使用できない文字が含まれています: {', '.join(invalid_chars)}", parent=dialog)
                return
            
            config_file = get_config_file_path(profile_name)
            if os.path.exists(config_file):
                if not messagebox.askyesno("確認", f"プロファイル '{profile_name}' は既に存在します。上書きしますか？", parent=dialog):
                    return
            
            # 現在のプロファイルの設定をコピーして新しいプロファイルを作成
            try:
                current_config = self.config.copy()
                config_dir = os.path.dirname(config_file)
                if not os.path.exists(config_dir):
                    os.makedirs(config_dir, exist_ok=True)
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(current_config, f, indent=2, ensure_ascii=False)
                
                # プロファイル一覧を更新
                profiles = get_profile_list()
                # ドロップダウンの値を更新
                if hasattr(self, 'profile_combo'):
                    self.profile_combo['values'] = profiles
                    self.profile_var.set(profile_name)
                    self.on_profile_changed()
                
                self.log(f"[INFO] プロファイル '{profile_name}' を作成しました。")
                messagebox.showinfo("完了", f"プロファイル '{profile_name}' を作成しました。", parent=dialog)
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("エラー", f"プロファイルの作成に失敗しました:\n{e}", parent=dialog)
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text="保存", command=save_profile).pack(side="left", padx=5)
        ttk.Button(button_frame, text="キャンセル", command=dialog.destroy).pack(side="left", padx=5)
        
        # Enterキーで保存
        name_entry.bind('<Return>', lambda e: save_profile())

    def on_closing(self):
        if self.worker_thread and self.worker_thread.is_alive():
            if messagebox.askyesno("確認", "処理が実行中です。本当に終了しますか？"):
                self.stop_worker.set(); self.destroy()
        else: self.destroy()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding="10"); main_frame.pack(fill="both", expand=True)
        self.setup_frame = ttk.LabelFrame(main_frame, text="Step 1: 書籍リストの取得", padding="10"); self.setup_frame.pack(fill="x", padx=5, pady=5)

        # --- プロファイル選択 ---
        profile_frame = ttk.Frame(self.setup_frame)
        profile_frame.grid(row=0, column=0, columnspan=5, sticky="w", pady=5)
        ttk.Label(profile_frame, text="プロファイル:").pack(side="left", padx=(0, 5))
        profiles = get_profile_list()
        self.profile_combo = ttk.Combobox(profile_frame, textvariable=self.profile_var, values=profiles, state="readonly", width=20)
        self.profile_combo.pack(side="left", padx=(0, 10))
        self.profile_combo.bind("<<ComboboxSelected>>", self.on_profile_changed)
        # プロファイル追加ボタン
        ttk.Button(profile_frame, text="プロファイル追加", command=self.add_profile).pack(side="left", padx=5)
        # ChromeDriver更新ボタン
        ttk.Button(profile_frame, text="ChromeDriver更新", command=self.update_chromedriver).pack(side="left", padx=5)

        # --- URL入力欄の動的追加・削除機能 ---
        ttk.Label(self.setup_frame, text="一覧ページURL:").grid(row=1, column=0, sticky="w", pady=2)
        self.url_input_container = ttk.Frame(self.setup_frame)
        self.url_input_container.grid(row=2, column=0, columnspan=5, sticky="we")
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
        button_frame.grid(row=1, column=1, columnspan=4, sticky="e")
        ttk.Button(button_frame, text="URL入力欄を追加", command=add_url_entry).pack()

        ttk.Label(self.setup_frame, text="ログインID:").grid(row=3, column=0, sticky="w", pady=2)
        self.id_entry = ttk.Entry(self.setup_frame, width=40); self.id_entry.grid(row=4, column=0, sticky="w", pady=2); self.id_entry.insert(0, "dlowolxlowoly@gmail.com")
        ttk.Label(self.setup_frame, text="パスワード:").grid(row=3, column=1, sticky="w", pady=2)
        self.pw_entry = ttk.Entry(self.setup_frame, width=40, show="*"); self.pw_entry.grid(row=4, column=1, sticky="w", pady=2); self.pw_entry.insert(0, "masa19890601")
        self.headless_checkbox = ttk.Checkbutton(self.setup_frame, text="ヘッドレスモード", variable=self.headless_mode_var); self.headless_checkbox.grid(row=4, column=2, sticky="w", padx=10)
        self.start_button = ttk.Button(self.setup_frame, text="リスト取得開始", command=self.start_list_generation); self.start_button.grid(row=4, column=3, sticky="w", padx=5)
        self.direct_dl_button = ttk.Button(self.setup_frame, text="リストからDL", command=self.start_direct_download); self.direct_dl_button.grid(row=4, column=4, sticky="w", padx=5)
        self.cancel_button = ttk.Button(self.setup_frame, text="キャンセル", command=self.cancel_worker); self.cancel_button.grid(row=5, column=0, sticky="w", padx=5, pady=2); self.cancel_button.config(state=tk.DISABLED)

        ttk.Label(self.setup_frame, text="DL保存先:").grid(row=6, column=0, sticky="w", pady=(10, 2))
        path_frame = ttk.Frame(self.setup_frame); path_frame.grid(row=7, column=0, columnspan=5, sticky="we"); path_frame.columnconfigure(0, weight=1)
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

    def _create_chrome_service(self):
        """ChromeDriverのServiceオブジェクトを作成（自動バージョン管理対応）"""
        # 指定されたパスが存在する場合はそれを使用
        if self.CHROMEDRIVER_PATH and os.path.exists(self.CHROMEDRIVER_PATH):
            try:
                self.log(f"[INFO] 指定されたChromeDriverを使用: {self.CHROMEDRIVER_PATH}")
                return Service(self.CHROMEDRIVER_PATH)
            except Exception as e:
                self.log(f"[WARN] 指定されたChromeDriverの使用に失敗: {e}")
                self.log("[INFO] webdriver-managerを使用して自動取得を試みます...")
        
        # webdriver-managerが利用可能な場合は自動ダウンロード
        if WEBDRIVER_MANAGER_AVAILABLE:
            try:
                self.log("[INFO] webdriver-managerを使用してChromeDriverを自動取得中...")
                return Service(ChromeDriverManager().install())
            except Exception as e:
                self.log(f"[WARN] ChromeDriverの自動取得に失敗: {e}")
                self.log("[INFO] システムにインストールされているChromeDriverを使用します")
        
        # フォールバック: システムのChromeDriverを使用
        return Service()

    def _list_generation_worker(self, list_urls, login_id, login_pw):
        self.log("書籍リストの取得処理を開始します。"); driver = None
        try:
            options = Options(); 
            headless_mode = self.headless_mode_var.get()
            if headless_mode: options.add_argument("--headless=new")
            # 追加のオプションでクラッシュを防ぐ
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            service = self._create_chrome_service()
            try:
                driver = webdriver.Chrome(service=service, options=options)
                self.log("[INFO] ChromeDriver起動完了")
            except Exception as driver_error:
                error_msg = str(driver_error)
                self.log(f"[ERROR] ChromeDriverの起動に失敗しました: {error_msg}")
                # webdriver-managerが利用可能で、まだ試していない場合は再試行
                if WEBDRIVER_MANAGER_AVAILABLE and self.CHROMEDRIVER_PATH and os.path.exists(self.CHROMEDRIVER_PATH):
                    self.log("[INFO] webdriver-managerを使用して再試行します...")
                    try:
                        service = Service(ChromeDriverManager().install())
                        driver = webdriver.Chrome(service=service, options=options)
                        self.log("[INFO] ChromeDriver起動完了（webdriver-manager経由）")
                    except Exception as retry_error:
                        self.log(f"[ERROR] 再試行も失敗しました: {retry_error}")
                        raise
                else:
                    raise
            driver.get("https://www.medicalonline.jp/login/mypage")
            WebDriverWait(driver, self.SELENIUM_WAIT).until(EC.presence_of_element_located((By.ID, "mypage_loginid")))
            driver.find_element(By.ID, "mypage_loginid").send_keys(login_id); driver.find_element(By.ID, "mypage_passwd").send_keys(login_pw)
            driver.find_element(By.CSS_SELECTOR, "button.button-login[name='submit']").click()
            WebDriverWait(driver, self.SELENIUM_WAIT).until_not(EC.presence_of_element_located((By.ID, "mypage_loginid"))); self.log("[INFO] ログイン成功")
            if self.stop_worker.is_set(): raise InterruptedError()
            driver.get("https://mol.medicalonline.jp/library/ebooks/"); time.sleep(2)
            user_id = parse_qs(urlparse(driver.current_url).query).get('UserID', [None])[0]
            if not user_id: raise ValueError("UserIDの取得に失敗")
            self.log(f"[INFO] UserID取得成功: {user_id}")

            all_links = set()
            for list_url in list_urls:
                if self.stop_worker.is_set(): break
                self.log(f"[INFO] '{list_url}' からリンクを収集中...")
                driver.get(re.sub(r'[?&]UserID=.*$', '', list_url))
                links_on_page = {a["href"] if a["href"].startswith("http") else "https://mol.medicalonline.jp" + a["href"] for a in BeautifulSoup(driver.page_source, "lxml").find_all("a", href=True) if "library/ebooks/detail?id=" in a["href"]}
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
            self.log(f"判定完了。閲覧可能な書籍が {len(ok_links)} 件見つかりました。", is_update=True); self.is_status_log_active = False
            self.after(0, self.prepare_selection_gui, ok_links)
        except Exception as e: self.log(f"[ERROR] リスト取得中にエラー: {e}")
        finally:
            if driver: driver.quit()
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
            r = requests.get(url.split("&", 1)[0], headers={"User-Agent": self.USER_AGENT}, timeout=self.REQUESTS_TIMEOUT); r.raise_for_status()
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
            cmd = ['python', DOWNLOAD_SCRIPT, self.CHROME_EXEC_PATH_PW, self.CHROME_USER_DATA_DIR_PW, download_dir]
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
            r = requests.get(url.split("&", 1)[0], headers={"User-Agent": self.USER_AGENT}, timeout=self.REQUESTS_TIMEOUT); r.raise_for_status()
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
