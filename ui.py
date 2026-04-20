import customtkinter as ctk
import glob
import os
import threading
import time
from tkinter import filedialog

from src.config import AppConfig, DEFAULT_LANGUAGE_PROMPT, DEFAULT_ADVANCED_PROMPT, APP_VERSION
from src.epub_core import process_epub
from src.paths_store import (
    ensure_books_dirs,
    load_app_settings,
    output_path_for_epub,
    save_app_settings,
)

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# Cursor IDE–inspired dark palette (approx.)
CURSOR_BG = "#141414"
CURSOR_PANEL = "#1a1a1a"
CURSOR_SIDEBAR = "#161616"
CURSOR_ACTIVITYBAR = "#0f0f0f"
CURSOR_BORDER = "#2b2b2b"
CURSOR_TEXT = "#e4e4e7"
CURSOR_MUTED = "#71717a"
CURSOR_ACCENT = "#8b5cf6"
CURSOR_ACCENT_HOVER = "#a78bfa"
CURSOR_SUCCESS = "#34d399"
CURSOR_SUCCESS_HOVER = "#10b981"
CURSOR_DANGER = "#f87171"
CURSOR_DANGER_HOVER = "#ef4444"

# Cantos rectos (alinhado a IDE; evita “gaps” entre bordas e widgets arredondados)
R0 = 0

class TranslatorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("iTranslateBooks")
        self.geometry("1180x760")
        self.minsize(980, 640)

        # Suporte para Ícone da Aplicação
        try:
            self.iconbitmap(os.path.join(os.path.dirname(__file__), "assets", "app_icon.ico"))
        except Exception:
            pass

        self.books_in_abs, self.books_out_abs = ensure_books_dirs()

        self.configure(fg_color=CURSOR_BG)

        # Layout grid:
        # col 0: activity bar
        # col 1: side bar
        # col 2: main editor area
        self.grid_columnconfigure(0, minsize=56)
        self.grid_columnconfigure(1, minsize=320)
        self.grid_columnconfigure(2, weight=1)
        # row 0: content
        # row 1: bottom panel
        # row 2: status bar
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, minsize=210)
        self.grid_rowconfigure(2, minsize=26)
        
        self.cancel_event = threading.Event()
        self.is_running = False
        self.active_view = "explorer"
        self.custom_lang_prompts = {}
        self.custom_adv_prompts = {}
        
        # Activity bar (VS Code leftmost)
        self.activitybar = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=CURSOR_ACTIVITYBAR,
            border_width=0,
        )
        self.activitybar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.activitybar.grid_rowconfigure(10, weight=1)

        self.btn_explorer = ctk.CTkButton(
            self.activitybar,
            text="📂",
            width=44,
            height=44,
            corner_radius=R0,
            fg_color=CURSOR_ACCENT,
            hover_color=CURSOR_ACCENT_HOVER,
            font=ctk.CTkFont(size=22),
            command=lambda: self.set_view("explorer"),
        )
        self.btn_explorer.grid(row=0, column=0, padx=6, pady=(8, 6))

        self.btn_lang_prompt = ctk.CTkButton(
            self.activitybar,
            text="🌐",
            width=44,
            height=44,
            corner_radius=R0,
            fg_color=CURSOR_ACTIVITYBAR,
            hover_color=CURSOR_PANEL,
            font=ctk.CTkFont(size=22),
            command=lambda: self.set_view("lang_prompt"),
        )
        self.btn_lang_prompt.grid(row=1, column=0, padx=6, pady=6)

        self.btn_adv_prompt = ctk.CTkButton(
            self.activitybar,
            text="🔧",
            width=44,
            height=44,
            corner_radius=R0,
            fg_color=CURSOR_ACTIVITYBAR,
            hover_color=CURSOR_PANEL,
            font=ctk.CTkFont(size=22),
            command=lambda: self.set_view("adv_prompt"),
        )
        self.btn_adv_prompt.grid(row=2, column=0, padx=6, pady=6)

        self.btn_settings = ctk.CTkButton(
            self.activitybar,
            text="⚙",
            width=44,
            height=44,
            corner_radius=R0,
            fg_color=CURSOR_ACTIVITYBAR,
            hover_color=CURSOR_PANEL,
            font=ctk.CTkFont(size=22),
            command=lambda: self.set_view("settings"),
        )
        self.btn_settings.grid(row=3, column=0, padx=6, pady=6)

        # Side bar (Explorer / Settings)
        self.sidebar = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=CURSOR_SIDEBAR,
            border_width=1,
            border_color=CURSOR_BORDER,
        )
        self.sidebar.grid(row=0, column=1, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(1, weight=1)

        self.sidebar_title = ctk.CTkLabel(
            self.sidebar,
            text="SIDEBAR",
            text_color=CURSOR_MUTED,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.sidebar_title.grid(row=0, column=0, padx=14, pady=(12, 8), sticky="w")

        self.sidebar_content = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_content.grid(row=1, column=0, padx=0, pady=0, sticky="nsew")
        self.sidebar_content.grid_columnconfigure(0, weight=1)
        self.sidebar_content.grid_rowconfigure(0, weight=1)

        # Sidebar views (switched by activity bar)
        self.sidebar_views = ctk.CTkFrame(self.sidebar_content, fg_color="transparent")
        self.sidebar_views.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.sidebar_views.grid_columnconfigure(0, weight=1)
        self.sidebar_views.grid_rowconfigure(0, weight=1)

        self.view_explorer = ctk.CTkFrame(self.sidebar_views, fg_color="transparent")
        self.view_settings = ctk.CTkFrame(self.sidebar_views, fg_color="transparent")
        self.view_lang_prompt = ctk.CTkFrame(self.sidebar_views, fg_color="transparent")
        self.view_adv_prompt = ctk.CTkFrame(self.sidebar_views, fg_color="transparent")

        for v in (self.view_explorer, self.view_settings, self.view_lang_prompt, self.view_adv_prompt):
            v.grid(row=0, column=0, sticky="nsew")

        # Main editor area (home)
        self.editor = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=CURSOR_BG,
            border_width=1,
            border_color=CURSOR_BORDER,
        )
        self.editor.grid(row=0, column=2, sticky="nsew", padx=(0, 0), pady=(0, 0))
        self.editor.grid_columnconfigure(0, weight=1)
        self.editor.grid_rowconfigure(1, weight=1)

        self.editor_header = ctk.CTkFrame(self.editor, fg_color=CURSOR_PANEL, corner_radius=0)
        self.editor_header.grid(row=0, column=0, sticky="ew")
        self.editor_header.grid_columnconfigure(1, weight=1)

        self.editor_title = ctk.CTkLabel(
            self.editor_header,
            text="iTB",
            text_color=CURSOR_TEXT,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.editor_title.grid(row=0, column=0, padx=12, pady=10, sticky="w")

        # (Run and Stop moved to queue panel footer)

        self.editor_body = ctk.CTkFrame(self.editor, fg_color="transparent")
        self.editor_body.grid(row=1, column=0, sticky="nsew")
        self.editor_body.grid_columnconfigure(0, weight=1)
        self.editor_body.grid_rowconfigure(0, weight=1)

        self.queue_items = []  # list[dict]: input, output, status, seconds
        self._build_queue_panel()

        # Bottom panel (Output + progress)
        self.bottom_panel = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=CURSOR_PANEL,
            border_width=1,
            border_color=CURSOR_BORDER,
        )
        self.bottom_panel.grid(row=1, column=1, columnspan=2, sticky="nsew")
        self.bottom_panel.grid_columnconfigure(0, weight=1)
        self.bottom_panel.grid_rowconfigure(1, weight=1)

        self.bottom_header = ctk.CTkFrame(self.bottom_panel, fg_color="transparent")
        self.bottom_header.grid(row=0, column=0, padx=12, pady=8, sticky="ew")
        self.bottom_header.grid_columnconfigure(0, weight=1)

        self.bottom_title = ctk.CTkLabel(
            self.bottom_header,
            text="OUTPUT",
            text_color=CURSOR_MUTED,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.bottom_title.grid(row=0, column=0, sticky="w")

        self.progress_wrap = ctk.CTkFrame(self.bottom_header, fg_color="transparent")
        self.progress_wrap.grid(row=0, column=1, sticky="e")

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_wrap,
            width=220,
            height=12,
            corner_radius=R0,
            progress_color=CURSOR_ACCENT,
        )
        self.progress_bar.pack(side="left", padx=(0, 10))
        self.progress_bar.set(0)

        self.eta_label = ctk.CTkLabel(self.progress_wrap, text="-- | ETA: -- | 0/0", text_color=CURSOR_TEXT, font=ctk.CTkFont(size=12))
        self.eta_label.pack(side="left")

        self.console = ctk.CTkTextbox(
            self.bottom_panel,
            fg_color=CURSOR_BG,
            text_color=CURSOR_TEXT,
            border_width=1,
            border_color=CURSOR_BORDER,
            corner_radius=R0,
        )
        self.console.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.console.configure(state="disabled")

        # Status bar (VS Code bottom)
        self.statusbar = ctk.CTkFrame(self, corner_radius=0, fg_color=CURSOR_ACTIVITYBAR)
        self.statusbar.grid(row=2, column=0, columnspan=3, sticky="nsew")
        self.statusbar.grid_columnconfigure(1, weight=1)

        self.status_left = ctk.CTkLabel(self.statusbar, text="Ready", text_color=CURSOR_TEXT, font=ctk.CTkFont(size=11))
        self.status_left.grid(row=0, column=0, padx=10, pady=4, sticky="w")

        self.status_right = ctk.CTkLabel(self.statusbar, text="", text_color=CURSOR_MUTED, font=ctk.CTkFont(size=11))
        self.status_right.grid(row=0, column=2, padx=10, pady=4, sticky="e")

        self.status_version = ctk.CTkLabel(
            self.statusbar,
            text=f"v{APP_VERSION}",
            text_color=CURSOR_ACCENT,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.status_version.grid(row=0, column=3, padx=(0, 12), pady=4, sticky="e")

        # Sidebar content
        self.checkboxes = []
        self._build_explorer_view(self.view_explorer)
        self._build_settings_view(self.view_settings)
        self._build_prompt_view(self.view_lang_prompt, mode="lang")
        self._build_prompt_view(self.view_adv_prompt, mode="adv")
        self._sync_books_paths_ui()
        self.refresh_books()
        self.set_view("explorer")

    def update_slider_label(self, value):
        self.slider_label.configure(text=f"Workers: {int(value)}")

    def update_temp_label(self, value):
        self.temp_label.configure(text=f"Temperature: {float(value):.2f}")

    def set_status(self, text: str):
        self.status_left.configure(text=text)

    def _safe_startfile(self, path: str):
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            import platform
            import subprocess
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as e:
            self.log(f"[WARNING] Não foi possível abrir: {path} ({e})")

    def _resolve_path_from_entry(self, entry_widget):
        d = entry_widget.get().strip()
        if not d:
            from src.paths_store import PROJECT_ROOT
            return str(PROJECT_ROOT)
        if os.path.isabs(d):
            return d
        from src.paths_store import PROJECT_ROOT
        return os.path.normpath(os.path.join(str(PROJECT_ROOT), d))

    def open_books_in_folder(self):
        self._safe_startfile(self._resolve_path_from_entry(self.books_in_entry))

    def open_books_out_folder(self):
        self._safe_startfile(self._resolve_path_from_entry(self.books_out_entry))

    def clear_output(self):
        self.console.configure(state="normal")
        self.console.delete("0.0", "end")
        self.console.configure(state="disabled")

    def reset_system_prompt(self):
        self.prompt_text.delete("0.0", "end")
        self.prompt_text.insert("0.0", DEFAULT_SYSTEM_PROMPT)
        self.set_view("prompt")

    def _build_queue_panel(self):
        self.queue_panel = ctk.CTkFrame(self.editor_body, fg_color=CURSOR_PANEL, corner_radius=R0, border_width=1, border_color=CURSOR_BORDER)
        self.queue_panel.grid(row=0, column=0, sticky="nsew")
        self.queue_panel.grid_columnconfigure(0, weight=1)
        self.queue_panel.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.queue_panel, fg_color="transparent")
        header.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(header, text="QUEUE", text_color=CURSOR_TEXT, font=ctk.CTkFont(size=14, weight="bold"))
        title.grid(row=0, column=0, sticky="w")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")

        self.queue_clear_btn = ctk.CTkButton(
            actions,
            text="Clear",
            width=78,
            corner_radius=R0,
            fg_color=CURSOR_BG,
            hover_color="#2a2a2a",
            border_width=1,
            border_color=CURSOR_BORDER,
            command=self.clear_queue,
        )
        self.queue_clear_btn.pack(side="left", padx=(0, 8))

        self.queue_open_in_btn = ctk.CTkButton(
            actions,
            text="📂 Abrir IN",
            width=88,
            corner_radius=R0,
            fg_color=CURSOR_PANEL,
            hover_color="#2f2f2f",
            border_width=1,
            border_color=CURSOR_BORDER,
            command=self.open_books_in_folder,
        )
        self.queue_open_in_btn.pack(side="left", padx=(0, 8))

        self.queue_open_out_btn = ctk.CTkButton(
            actions,
            text="📂 Abrir OUT",
            width=88,
            corner_radius=R0,
            fg_color=CURSOR_PANEL,
            hover_color="#2f2f2f",
            border_width=1,
            border_color=CURSOR_BORDER,
            command=self.open_books_out_folder,
        )
        self.queue_open_out_btn.pack(side="left")

        self.queue_list = ctk.CTkScrollableFrame(self.queue_panel, fg_color="transparent", label_text="", corner_radius=R0)
        self.queue_list.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        footer = ctk.CTkFrame(self.queue_panel, fg_color="transparent")
        footer.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        self.queue_hint = ctk.CTkLabel(
            footer,
            text="Selecione livros no Explorer e adicione à Queue.",
            text_color=CURSOR_MUTED,
            font=ctk.CTkFont(size=11),
            justify="left",
        )
        self.queue_hint.grid(row=0, column=0, sticky="w")

        # Start / Stop Buttons at the bottom of the Queue
        self.run_controls = ctk.CTkFrame(footer, fg_color="transparent")
        self.run_controls.grid(row=0, column=1, sticky="e")

        self.run_btn = ctk.CTkButton(
            self.run_controls,
            text="▶ INICIAR TRADUÇÃO",
            width=140,
            corner_radius=R0,
            fg_color=CURSOR_SUCCESS,
            hover_color=CURSOR_SUCCESS_HOVER,
            command=self.start_translation,
        )
        self.run_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = ctk.CTkButton(
            self.run_controls,
            text="⏹ Cancelar",
            width=90,
            corner_radius=R0,
            fg_color=CURSOR_DANGER,
            hover_color=CURSOR_DANGER_HOVER,
            command=self.stop_translation,
            state="disabled",
        )
        self.stop_btn.pack(side="left")

        self._render_queue()

    def clear_queue(self):
        if self.is_running:
            self.log("[WARNING] Não é possível limpar a queue durante execução.")
            return
        self.queue_items = []
        self._render_queue()

    def remove_from_queue(self, input_file):
        if self.is_running:
            self.log("[WARNING] Não é possível remover da queue durante execução.")
            return
        self.queue_items = [item for item in self.queue_items if item.get("input") != input_file]
        self._render_queue()
        self.log(f"[INFO] Removido da fila: {os.path.basename(input_file)}")

    def _queue_status_color(self, status: str) -> str:
        status = (status or "").upper()
        if status == "RUNNING":
            return CURSOR_ACCENT
        if status == "DONE":
            return CURSOR_SUCCESS
        if status in ("FAILED", "CANCELLED"):
            return CURSOR_DANGER
        return CURSOR_MUTED

    def _render_queue(self):
        for child in self.queue_list.winfo_children():
            child.destroy()

        if not self.queue_items:
            empty = ctk.CTkLabel(self.queue_list, text="Queue vazia.", text_color=CURSOR_MUTED, font=ctk.CTkFont(size=12))
            empty.grid(row=0, column=0, padx=8, pady=8, sticky="w")
            return

        for i, item in enumerate(self.queue_items):
            status = item.get("status", "PENDING")
            secs = item.get("seconds")
            dur = f"{int(secs)}s" if isinstance(secs, (int, float)) else ""
            base = os.path.basename(item.get("input", ""))
            out_path = item.get("output")

            row = ctk.CTkFrame(self.queue_list, fg_color=CURSOR_BG, corner_radius=R0, border_width=1, border_color=CURSOR_BORDER)
            row.grid(row=i, column=0, padx=6, pady=6, sticky="ew")
            row.grid_columnconfigure(0, weight=1)

            left = ctk.CTkFrame(row, fg_color="transparent")
            left.grid(row=0, column=0, padx=10, pady=8, sticky="ew")
            left.grid_columnconfigure(0, weight=1)

            name_lbl = ctk.CTkLabel(left, text=base, text_color=CURSOR_TEXT, font=ctk.CTkFont(size=12), anchor="w")
            name_lbl.grid(row=0, column=0, sticky="w")

            meta = f"{status}{(' • ' + dur) if dur else ''}"
            status_lbl = ctk.CTkLabel(left, text=meta, text_color=self._queue_status_color(status), font=ctk.CTkFont(size=11))
            status_lbl.grid(row=1, column=0, sticky="w", pady=(2, 0))

            open_btn = ctk.CTkButton(
                row,
                text="Open",
                width=74,
                corner_radius=R0,
                fg_color=CURSOR_PANEL,
                hover_color="#2f2f2f",
                border_width=1,
                border_color=CURSOR_BORDER,
                command=(lambda p=out_path: self._safe_startfile(p)) if out_path else None,
                state=("normal" if (out_path and status.upper() == "DONE") else "disabled"),
            )
            open_btn.grid(row=0, column=1, padx=(10, 5), pady=10, sticky="e")

            remove_btn = ctk.CTkButton(
                row,
                text="Remover",
                width=74,
                corner_radius=R0,
                fg_color=CURSOR_DANGER,
                hover_color=CURSOR_DANGER_HOVER,
                border_width=1,
                border_color=CURSOR_BORDER,
                command=lambda f=item.get("input"): self.remove_from_queue(f),
                state="disabled" if self.is_running else "normal",
            )
            remove_btn.grid(row=0, column=2, padx=(0, 10), pady=10, sticky="e")

    def _queue_set_status(self, input_file: str, status: str, seconds: float | None = None):
        for item in self.queue_items:
            if item.get("input") == input_file:
                item["status"] = status
                if seconds is not None:
                    item["seconds"] = seconds
                break
        self.after(0, self._render_queue)

    def _all_sidebar_btns(self):
        return [self.btn_explorer, self.btn_lang_prompt, self.btn_adv_prompt, self.btn_settings]

    def set_view(self, view: str):
        self.active_view = view
        for b in self._all_sidebar_btns():
            b.configure(fg_color=CURSOR_ACTIVITYBAR, hover_color=CURSOR_PANEL)
        if view == "explorer":
            self.sidebar_title.configure(text="EXPLORER")
            self.view_explorer.tkraise()
            self.btn_explorer.configure(fg_color=CURSOR_ACCENT, hover_color=CURSOR_ACCENT_HOVER)
        elif view == "lang_prompt":
            self.sidebar_title.configure(text="LANGUAGE PROMPT")
            self.view_lang_prompt.tkraise()
            self.btn_lang_prompt.configure(fg_color=CURSOR_ACCENT, hover_color=CURSOR_ACCENT_HOVER)
        elif view == "adv_prompt":
            self.sidebar_title.configure(text="ADVANCED PROMPT")
            self.view_adv_prompt.tkraise()
            self.btn_adv_prompt.configure(fg_color=CURSOR_ACCENT, hover_color=CURSOR_ACCENT_HOVER)
        else:
            self.sidebar_title.configure(text="DEFINIÇÕES")
            self.view_settings.tkraise()
            self.btn_settings.configure(fg_color=CURSOR_ACCENT, hover_color=CURSOR_ACCENT_HOVER)

    def _build_explorer_view(self, parent):
        self.explorer_view = ctk.CTkFrame(parent, fg_color="transparent")
        self.explorer_view.pack(fill="both", expand=True)
        self.explorer_view.grid_columnconfigure(0, weight=1)
        self.explorer_view.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.explorer_view, fg_color="transparent")
        header.grid(row=0, column=0, padx=12, pady=(6, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self.books_path = ctk.CTkLabel(header, text="books_IN/", text_color=CURSOR_TEXT, font=ctk.CTkFont(size=12, weight="bold"))
        self.books_path.grid(row=0, column=0, sticky="w")

        self.refresh_btn = ctk.CTkButton(
            header,
            text="Refresh",
            width=88,
            corner_radius=R0,
            fg_color=CURSOR_PANEL,
            hover_color="#2f2f2f",
            border_width=1,
            border_color=CURSOR_BORDER,
            command=self.refresh_books,
        )
        self.refresh_btn.grid(row=0, column=1, sticky="e")

        self.books_frame = ctk.CTkScrollableFrame(self.explorer_view, fg_color="transparent", label_text="", corner_radius=R0)
        self.books_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        footer = ctk.CTkFrame(self.explorer_view, fg_color="transparent")
        footer.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        sel_frame = ctk.CTkFrame(footer, fg_color="transparent")
        sel_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        sel_frame.grid_columnconfigure(0, weight=1)
        sel_frame.grid_columnconfigure(1, weight=1)

        self.select_all_btn = ctk.CTkButton(
            sel_frame,
            text="Select all",
            corner_radius=R0,
            fg_color=CURSOR_PANEL,
            hover_color="#2f2f2f",
            border_width=1,
            border_color=CURSOR_BORDER,
            command=lambda: self._set_all_books(True),
        )
        self.select_all_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.clear_all_btn = ctk.CTkButton(
            sel_frame,
            text="Clear",
            corner_radius=R0,
            fg_color=CURSOR_PANEL,
            hover_color="#2f2f2f",
            border_width=1,
            border_color=CURSOR_BORDER,
            command=lambda: self._set_all_books(False),
        )
        self.clear_all_btn.grid(row=0, column=1, sticky="ew")

        self.add_to_queue_btn = ctk.CTkButton(
            footer,
            text="📥 Adicionar à Fila",
            corner_radius=R0,
            fg_color=CURSOR_PANEL,
            hover_color="#2f2f2f",
            border_width=1,
            border_color=CURSOR_BORDER,
            command=self.add_selected_to_queue,
        )
        self.add_to_queue_btn.grid(row=1, column=0, sticky="ew")

    def add_selected_to_queue(self):
        selected_files = [file for cb, file in self.checkboxes if cb.get()]
        if not selected_files:
            self.log("[WARNING] Nenhum livro selecionado para adicionar!")
            return
        
        self.books_out_abs = self._resolve_path_from_entry(self.books_out_entry)
        added = 0
        existing = {item["input"] for item in self.queue_items}
        for f in selected_files:
            if f not in existing:
                out = output_path_for_epub(f, self.books_out_abs)
                self.queue_items.append({"input": f, "output": out, "status": "PENDING", "seconds": None})
                added += 1
                existing.add(f)
        
        self._set_all_books(False)
        if added > 0:
            self.log(f"[INFO] Adicionados {added} livros à fila.")
            self._render_queue()
        else:
            self.log("[INFO] Os livros selecionados já estavam na fila.")

    def _sync_books_paths_ui(self):
        self.books_in_abs, self.books_out_abs = ensure_books_dirs()
        s = load_app_settings()
        if hasattr(self, "books_in_entry"):
            self.books_in_entry.delete(0, "end")
            self.books_in_entry.insert(0, s["books_in_dir"])
            self.books_out_entry.delete(0, "end")
            self.books_out_entry.insert(0, s["books_out_dir"])
            self.glossary_text.delete("0.0", "end")
            self.glossary_text.insert("0.0", s.get("glossary", ""))
            if s.get("use_context", True):
                self.context_checkbox.select()
            else:
                self.context_checkbox.deselect()
            if s.get("save_translation_report", False):
                self.report_checkbox.select()
            else:
                self.report_checkbox.deselect()
                
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, s.get("base_url", "http://127.0.0.1:1234/v1"))
            self.model_entry.delete(0, "end")
            self.model_entry.insert(0, s.get("model_name", "qwen3-v1-8b-instruct"))
            self.worker_slider.set(s.get("max_workers", 3))
            self.slider_label.configure(text=f"Workers: {int(s.get('max_workers', 3))}")
            if hasattr(self, "temp_slider"):
                t = float(s.get("temperature", 0.4))
                self.temp_slider.set(t)
                self.temp_label.configure(text=f"Temperature: {t:.2f}")

        self.custom_lang_prompts = s.get("custom_lang_prompts", {})
        self.custom_adv_prompts = s.get("custom_adv_prompts", {})
        if hasattr(self, "lang_prompt_text"):
            self.lang_prompt_text.delete("0.0", "end")
            self.lang_prompt_text.insert("0.0", s.get("language_prompt", DEFAULT_LANGUAGE_PROMPT))
            opts = ["Default"] + list(self.custom_lang_prompts.keys())
            self.lang_prompt_dropdown.configure(values=opts)
        if hasattr(self, "adv_prompt_text"):
            self.adv_prompt_text.delete("0.0", "end")
            self.adv_prompt_text.insert("0.0", s.get("advanced_prompt", DEFAULT_ADVANCED_PROMPT))
            opts = ["Default"] + list(self.custom_adv_prompts.keys())
            self.adv_prompt_dropdown.configure(values=opts)

        self.books_path.configure(text=f"{s['books_in_dir'].rstrip(os.sep).rstrip('/')}/")
        self.status_right.configure(text=f"{s['books_in_dir']} → {s['books_out_dir']}")
        self.queue_items = s.get("pending_queue", [])
        if hasattr(self, "queue_list"):
            self.after(0, self._render_queue)

    def save_folder_paths(self):
        lang_text = self.lang_prompt_text.get("0.0", "end").strip() if hasattr(self, "lang_prompt_text") else DEFAULT_LANGUAGE_PROMPT
        adv_text = self.adv_prompt_text.get("0.0", "end").strip() if hasattr(self, "adv_prompt_text") else DEFAULT_ADVANCED_PROMPT
        save_app_settings(
            self.books_in_entry.get(),
            self.books_out_entry.get(),
            self.glossary_text.get("0.0", "end").strip(),
            bool(self.context_checkbox.get()),
            bool(self.report_checkbox.get()),
            self.url_entry.get().strip(),
            self.model_entry.get().strip(),
            int(self.worker_slider.get()),
            float(self.temp_slider.get()) if hasattr(self, "temp_slider") else 0.4,
            lang_text,
            self.custom_lang_prompts,
            adv_text,
            self.custom_adv_prompts,
            [i for i in self.queue_items if i.get("status") == "PENDING"] if hasattr(self, "queue_items") else [],
        )
        self._sync_books_paths_ui()
        self.refresh_books()
        self.log("[INFO] Definições guardadas (itranslatebooks_config.json).")

    def browse_books_in(self):
        d = filedialog.askdirectory(initialdir=self.books_in_abs or os.getcwd())
        if d:
            self.books_in_entry.delete(0, "end")
            self.books_in_entry.insert(0, d)

    def browse_books_out(self):
        d = filedialog.askdirectory(initialdir=self.books_out_abs or os.getcwd())
        if d:
            self.books_out_entry.delete(0, "end")
            self.books_out_entry.insert(0, d)

    def _build_settings_view(self, parent):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="both", expand=True)
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(1, weight=1)

        top_bar = ctk.CTkFrame(wrap, fg_color="transparent")
        top_bar.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="ew")

        ctk.CTkButton(
            top_bar,
            text="Guardar Definições",
            corner_radius=R0,
            fg_color=CURSOR_ACCENT,
            hover_color=CURSOR_ACCENT_HOVER,
            command=self.save_folder_paths,
        ).pack(side="left")

        form = ctk.CTkScrollableFrame(wrap, fg_color=CURSOR_PANEL, corner_radius=R0, border_width=1, border_color=CURSOR_BORDER)
        form.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        form.grid_columnconfigure(0, weight=1)

        s0 = load_app_settings()

        self.books_in_label = ctk.CTkLabel(form, text="Pasta entrada (EPUBs)", text_color=CURSOR_MUTED, font=ctk.CTkFont(size=12))
        self.books_in_label.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")

        in_row = ctk.CTkFrame(form, fg_color="transparent")
        in_row.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")
        in_row.grid_columnconfigure(0, weight=1)

        self.books_in_entry = ctk.CTkEntry(in_row, placeholder_text="books_IN", corner_radius=R0)
        self.books_in_entry.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.books_in_entry.insert(0, s0["books_in_dir"])

        ctk.CTkButton(
            in_row,
            text="…",
            width=36,
            corner_radius=R0,
            fg_color=CURSOR_BG,
            hover_color="#2a2a2a",
            border_width=1,
            border_color=CURSOR_BORDER,
            command=self.browse_books_in,
        ).grid(row=0, column=1, sticky="e")

        self.books_out_label = ctk.CTkLabel(form, text="Pasta saída (traduzidos)", text_color=CURSOR_MUTED, font=ctk.CTkFont(size=12))
        self.books_out_label.grid(row=2, column=0, padx=12, pady=(4, 4), sticky="w")

        out_row = ctk.CTkFrame(form, fg_color="transparent")
        out_row.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="ew")
        out_row.grid_columnconfigure(0, weight=1)

        self.books_out_entry = ctk.CTkEntry(out_row, placeholder_text="books_OUT", corner_radius=R0)
        self.books_out_entry.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.books_out_entry.insert(0, s0["books_out_dir"])

        ctk.CTkButton(
            out_row,
            text="…",
            width=36,
            corner_radius=R0,
            fg_color=CURSOR_BG,
            hover_color="#2a2a2a",
            border_width=1,
            border_color=CURSOR_BORDER,
            command=self.browse_books_out,
        ).grid(row=0, column=1, sticky="e")

        self.url_label = ctk.CTkLabel(form, text="Base URL", text_color=CURSOR_MUTED, font=ctk.CTkFont(size=12))
        self.url_label.grid(row=4, column=0, padx=12, pady=(4, 4), sticky="w")

        self.url_entry = ctk.CTkEntry(form, placeholder_text="http://127.0.0.1:1234/v1", corner_radius=R0)
        self.url_entry.grid(row=5, column=0, padx=12, pady=(0, 10), sticky="ew")
        self.url_entry.insert(0, "http://127.0.0.1:1234/v1")

        self.model_label = ctk.CTkLabel(form, text="Model", text_color=CURSOR_MUTED, font=ctk.CTkFont(size=12))
        self.model_label.grid(row=6, column=0, padx=12, pady=(0, 4), sticky="w")

        self.model_entry = ctk.CTkEntry(form, placeholder_text="qwen3-v1-8b-instruct", corner_radius=R0)
        self.model_entry.grid(row=7, column=0, padx=12, pady=(0, 10), sticky="ew")
        self.model_entry.insert(0, "qwen3-v1-8b-instruct")

        self.slider_label = ctk.CTkLabel(form, text="Workers: 3", text_color=CURSOR_MUTED, font=ctk.CTkFont(size=12))
        self.slider_label.grid(row=8, column=0, padx=12, pady=(0, 2), sticky="w")

        self.worker_slider = ctk.CTkSlider(
            form,
            from_=1,
            to=8,
            number_of_steps=7,
            command=self.update_slider_label,
            corner_radius=R0,
            button_corner_radius=R0,
        )
        self.worker_slider.set(3)
        self.worker_slider.grid(row=9, column=0, padx=12, pady=(0, 12), sticky="ew")

        self.temp_label = ctk.CTkLabel(form, text=f"Temperature: {float(s0.get('temperature', 0.4)):.2f}", text_color=CURSOR_MUTED, font=ctk.CTkFont(size=12))
        self.temp_label.grid(row=10, column=0, padx=12, pady=(0, 2), sticky="w")

        self.temp_slider = ctk.CTkSlider(
            form,
            from_=0.0,
            to=1.0,
            number_of_steps=20,
            command=self.update_temp_label,
            corner_radius=R0,
            button_corner_radius=R0,
        )
        self.temp_slider.set(float(s0.get("temperature", 0.4)))
        self.temp_slider.grid(row=11, column=0, padx=12, pady=(0, 12), sticky="ew")

        self.glossary_label = ctk.CTkLabel(form, text="Glossário Dinâmico (Presets salvos em JSON):\nEscreva Ex: 'Mage: Mago'", text_color=CURSOR_MUTED, font=ctk.CTkFont(size=12), justify="left")
        self.glossary_label.grid(row=12, column=0, padx=12, pady=(4, 4), sticky="w")

        self.glossary_text = ctk.CTkTextbox(form, height=60, corner_radius=R0)
        self.glossary_text.grid(row=13, column=0, padx=12, pady=(0, 8), sticky="ew")

        self.context_checkbox = ctk.CTkCheckBox(form, text="Usar Contexto Anterior (Reduz alucinações de gêneros, ligeiramente mais lento)", corner_radius=R0)
        self.context_checkbox.grid(row=14, column=0, padx=12, pady=(4, 8), sticky="w")

        self.report_checkbox = ctk.CTkCheckBox(
            form,
            text="Guardar relatório TXT após tradução (tempos, ficheiros e config — útil para comparar execuções)",
            corner_radius=R0,
        )
        self.report_checkbox.grid(row=15, column=0, padx=12, pady=(0, 8), sticky="w")
        if s0.get("save_translation_report", False):
            self.report_checkbox.select()

        tip = ctk.CTkLabel(
            wrap,
            text="Pastas ficam em itranslatebooks_config.json (ignorado pelo git). Aumente workers só se a API aguentar.",
            text_color=CURSOR_MUTED,
            font=ctk.CTkFont(size=11),
            justify="left",
        )
        tip.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="w")

    def _build_prompt_view(self, parent, mode: str):
        """mode='lang' for Language Prompt, mode='adv' for Advanced Prompt."""
        is_lang = (mode == "lang")
        default_text = DEFAULT_LANGUAGE_PROMPT if is_lang else DEFAULT_ADVANCED_PROMPT
        hint_text = (
            "Regras de linguagem, estilo e concordância. Suporta {GLOSSARY_SECTION}."
            if is_lang else
            "Regras técnicas de formatação XML/HTML e Drop Caps."
        )

        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="both", expand=True)
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(2, weight=1)

        hint = ctk.CTkLabel(wrap, text=hint_text, text_color=CURSOR_MUTED, font=ctk.CTkFont(size=12))
        hint.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="w")

        top_bar = ctk.CTkFrame(wrap, fg_color="transparent")
        top_bar.grid(row=1, column=0, padx=10, pady=(8, 0), sticky="ew")

        dropdown = ctk.CTkOptionMenu(
            top_bar, values=["Default"],
            command=lambda c, m=mode: self._on_prompt_selected(c, m),
            corner_radius=R0,
        )
        dropdown.pack(side="left", padx=(0, 10))

        name_entry = ctk.CTkEntry(top_bar, placeholder_text="Novo Preset...", corner_radius=R0)
        name_entry.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            top_bar, text="+", width=36, corner_radius=R0,
            fg_color=CURSOR_ACCENT, hover_color=CURSOR_ACCENT_HOVER,
            command=lambda m=mode: self._add_custom_prompt(m),
        ).pack(side="left", padx=(0, 5))

        del_btn = ctk.CTkButton(
            top_bar, text="🗑", width=36, corner_radius=R0,
            fg_color=CURSOR_DANGER, hover_color=CURSOR_DANGER_HOVER,
            command=lambda m=mode: self._del_custom_prompt(m),
        )
        del_btn.pack(side="left")

        # disable delete for Default on init
        del_btn.configure(state="disabled")

        textbox = ctk.CTkTextbox(
            wrap, fg_color=CURSOR_BG, text_color=CURSOR_TEXT,
            border_width=1, border_color=CURSOR_BORDER, corner_radius=R0,
        )
        textbox.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")
        textbox.insert("0.0", default_text)

        if is_lang:
            self.lang_prompt_dropdown = dropdown
            self.lang_prompt_name_entry = name_entry
            self.lang_prompt_text = textbox
            self.lang_del_btn = del_btn
        else:
            self.adv_prompt_dropdown = dropdown
            self.adv_prompt_name_entry = name_entry
            self.adv_prompt_text = textbox
            self.adv_del_btn = del_btn

    def _on_prompt_selected(self, choice, mode):
        is_lang = (mode == "lang")
        textbox = self.lang_prompt_text if is_lang else self.adv_prompt_text
        del_btn = self.lang_del_btn if is_lang else self.adv_del_btn
        presets = self.custom_lang_prompts if is_lang else self.custom_adv_prompts
        default = DEFAULT_LANGUAGE_PROMPT if is_lang else DEFAULT_ADVANCED_PROMPT
        textbox.delete("0.0", "end")
        textbox.insert("0.0", presets.get(choice, default))
        # Only allow delete for non-default presets
        del_btn.configure(state=("normal" if choice != "Default" else "disabled"))

    def _add_custom_prompt(self, mode):
        is_lang = (mode == "lang")
        name_entry = self.lang_prompt_name_entry if is_lang else self.adv_prompt_name_entry
        textbox = self.lang_prompt_text if is_lang else self.adv_prompt_text
        dropdown = self.lang_prompt_dropdown if is_lang else self.adv_prompt_dropdown
        presets = self.custom_lang_prompts if is_lang else self.custom_adv_prompts
        name = name_entry.get().strip()
        if not name or name.lower() == "default":
            self.log("[WARNING] Nome de preset inválido.")
            return
        presets[name] = textbox.get("0.0", "end").strip()
        name_entry.delete(0, "end")
        opts = ["Default"] + list(presets.keys())
        dropdown.configure(values=opts)
        dropdown.set(name)
        self.save_folder_paths()

    def _del_custom_prompt(self, mode):
        is_lang = (mode == "lang")
        dropdown = self.lang_prompt_dropdown if is_lang else self.adv_prompt_dropdown
        del_btn = self.lang_del_btn if is_lang else self.adv_del_btn
        presets = self.custom_lang_prompts if is_lang else self.custom_adv_prompts
        choice = dropdown.get()
        if choice == "Default":
            return
        if choice in presets:
            del presets[choice]
            opts = ["Default"] + list(presets.keys())
            dropdown.configure(values=opts)
            dropdown.set("Default")
            del_btn.configure(state="disabled")
            self._on_prompt_selected("Default", mode)
            self.save_folder_paths()

    def _set_all_books(self, checked: bool):
        for cb, _ in self.checkboxes:
            if checked:
                cb.select()
            else:
                cb.deselect()

    def refresh_books(self):
        for cb, _ in self.checkboxes:
            cb.destroy()
        self.checkboxes.clear()
        
        self.books_in_abs = self._resolve_path_from_entry(self.books_in_entry)
        self.books_out_abs = self._resolve_path_from_entry(self.books_out_entry)

        try:
            os.makedirs(self.books_in_abs, exist_ok=True)
        except OSError:
            pass

        pattern = os.path.join(self.books_in_abs, "*.epub")
        files = glob.glob(pattern)
        for i, file in enumerate(files):
            filename = os.path.basename(file)
            cb = ctk.CTkCheckBox(
                self.books_frame,
                text=filename,
                corner_radius=R0,
            )
            cb.grid(row=i, column=0, padx=5, pady=5, sticky="w")
            # Unselected by default as requested
            self.checkboxes.append((cb, file))
        self.set_status(f"{len(files)} file(s) found")

    def log(self, msg):
        _MAX_LINES = 800
        _ARCHIVE_LINES = 250
        def append():
            self.console.configure(state="normal")
            self.console.insert("end", msg + "\n")
            # Summarize oldest lines instead of silently deleting them
            try:
                line_count = int(self.console.index("end-1c").split(".")[0])
                if line_count > _MAX_LINES:
                    self.console.delete("1.0", f"{_ARCHIVE_LINES + 1}.0")
                    self.console.insert(
                        "1.0",
                        f"[ … {_ARCHIVE_LINES} linhas anteriores arquivadas para libertar memória … ]\n"
                    )
            except Exception:
                pass
            self.console.see("end")
            self.console.configure(state="disabled")
        self.after(0, append)

    def update_progress(self, current, total, elapsed, eta, tps=None):
        def update():
            m, s = divmod(int(eta), 60)
            h, m = divmod(m, 60)
            time_str = f"{h}h {m}m" if h > 0 else f"{m}m {s}s"
            pct = int(current / total * 100) if total > 0 else 0
            self.progress_bar.set(current / total if total > 0 else 0)
            tps_str = f" | Speed: {tps:.1f} t/s" if tps and tps > 0 else ""
            self.eta_label.configure(text=f"{pct}% | ETA: {time_str}{tps_str} | {current}/{total}")
            self.set_status(f"Running… {pct}%")
        self.after(0, update)

    def stop_translation(self):
        if self.is_running:
            self.cancel_event.set()
            self.log("[INFO] Pedido de paragem forçada emitido. Aguardando o descarregamento das threads ativas...")
            self.stop_btn.configure(state="disabled")
            self.set_status("Stopping…")

    def start_translation(self):
        if self.is_running:
            return

        self.books_in_abs = self._resolve_path_from_entry(self.books_in_entry)
        self.books_out_abs = self._resolve_path_from_entry(self.books_out_entry)
        try:
            os.makedirs(self.books_in_abs, exist_ok=True)
            os.makedirs(self.books_out_abs, exist_ok=True)
        except OSError:
            pass

        selected_files = [item["input"] for item in self.queue_items if item.get("status") == "PENDING"]
        if not selected_files:
            self.log("[WARNING] A Fila não tem livros pendentes para traduzir!")
            return

        self.is_running = True
        self.cancel_event.clear()
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.set_status("Running…")
        self.log("\n" + "="*40)
        self.log(f"[INFO] A iniciar tradução de {len(selected_files)} livros pendentes...")
        
        url = self.url_entry.get()
        model = self.model_entry.get()
        workers = int(self.worker_slider.get())
        temp = float(self.temp_slider.get())
        lang_prompt = self.lang_prompt_text.get("0.0", "end").strip()
        adv_prompt = self.adv_prompt_text.get("0.0", "end").strip()
        glossary = self.glossary_text.get("0.0", "end").strip()
        use_ctx = bool(self.context_checkbox.get())

        # Inject glossary into language prompt
        if glossary:
            glossary_block = f"TERMINOLOGY TO KEEP (DYNAMIC GLOSSARY):\n{glossary}"
        else:
            glossary_block = ""
        if "{GLOSSARY_SECTION}" in lang_prompt:
            lang_prompt = lang_prompt.replace("{GLOSSARY_SECTION}", glossary_block)
        else:
            lang_prompt += "\n" + glossary_block

        # Disparar numa worker thread para garantir que o UI não se congele.
        threading.Thread(target=self._worker_thread, args=(selected_files, url, model, workers, temp, lang_prompt, adv_prompt, use_ctx), daemon=True).start()

    def _worker_thread(self, files, url, model, workers, temp, lang_prompt, adv_prompt, use_ctx):
        self.log(f"[INFO] A verificar conexão ao servidor local ({url})...")
        import urllib.request
        try:
            req = urllib.request.Request(url.rstrip('/') + "/models", method='GET')
            with urllib.request.urlopen(req, timeout=3):
                pass
        except Exception:
            self.log(f"[ERROR] O servidor falhou (LM Studio não está a correr em {url}). Tradução cancelada!")
            self.after(0, lambda: self.run_btn.configure(state="normal"))
            self.after(0, lambda: self.stop_btn.configure(state="disabled"))
            self.after(0, lambda: self.set_status("Ready"))
            self.is_running = False
            return

        for file in files:
            self.log(f"\n--- Iniciando: {os.path.basename(file)} ---")

            output_file = output_path_for_epub(file, self.books_out_abs)
            self._queue_set_status(file, "RUNNING")
            file_start = time.time()

            config = AppConfig(
                input_file=file,
                output_file=output_file,
                model_name=model,
                base_url=url,
                temperature=temp,
                language_prompt=lang_prompt,
                advanced_prompt=adv_prompt,
                max_workers=workers,
                use_context=use_ctx,
                save_translation_report=bool(self.report_checkbox.get()),
                cancel_event=self.cancel_event,
            )
            
            self.after(0, lambda: self.progress_bar.set(0))
            self.after(0, lambda: self.eta_label.configure(text="0% | ETA: Calculando... | 0/0"))
            
            success = process_epub(config, log_callback=self.log, progress_callback=self.update_progress)
            elapsed = time.time() - file_start

            if success:
                self._queue_set_status(file, "DONE", elapsed)
            elif self.cancel_event.is_set():
                self._queue_set_status(file, "CANCELLED", elapsed)
                for item in self.queue_items:
                    if item.get("status") == "PENDING":
                        item["status"] = "CANCELLED"
                self.after(0, self._render_queue)
                break
            else:
                self._queue_set_status(file, "FAILED", elapsed)
            
        self.log("\n[INFO] Fila de processos finalizada.")
        self.after(0, lambda: self.run_btn.configure(state="normal"))
        self.after(0, lambda: self.stop_btn.configure(state="disabled"))
        self.after(0, lambda: self.set_status("Ready"))
        self.is_running = False

if __name__ == "__main__":
    app = TranslatorApp()
    app.mainloop()
