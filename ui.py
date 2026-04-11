import customtkinter as ctk
import glob
import os
import threading
from src.config import AppConfig, DEFAULT_SYSTEM_PROMPT
from src.epub_core import process_epub

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class TranslatorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Elite EPUB Translator")
        self.geometry("1100x700")

        self.grid_columnconfigure(0, minsize=350)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.cancel_event = threading.Event()
        
        # Left Panel (Books to Translate)
        self.sidebar_frame = ctk.CTkFrame(self, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(2, weight=1)
        
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="Livros a Traduzir", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        # Scrollable Checkbox frame for books
        self.books_frame = ctk.CTkScrollableFrame(self.sidebar_frame, label_text="Pasta: books_IN/")
        self.books_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        
        self.checkboxes = []
        self.refresh_books()
        
        self.refresh_btn = ctk.CTkButton(self.sidebar_frame, text="Atualizar Pasta", command=self.refresh_books)
        self.refresh_btn.grid(row=3, column=0, padx=20, pady=20)
        
        # Right Panel (Config & Console)
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(4, weight=1)
        
        # Settings 
        self.settings_frame = ctk.CTkFrame(self.main_frame)
        self.settings_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        self.url_entry = ctk.CTkEntry(self.settings_frame, placeholder_text="Base URL")
        self.url_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.url_entry.insert(0, "http://127.0.0.1:1234/v1")
        
        self.model_entry = ctk.CTkEntry(self.settings_frame, placeholder_text="Model Name")
        self.model_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.model_entry.insert(0, "qwen3-v1-8b-instruct")
        
        self.slider_label = ctk.CTkLabel(self.settings_frame, text="Max Parallel Threads: 3")
        self.slider_label.grid(row=1, column=0, padx=10, pady=(10,0), sticky="w")
        self.worker_slider = ctk.CTkSlider(self.settings_frame, from_=1, to=8, number_of_steps=7, command=self.update_slider_label)
        self.worker_slider.set(3)
        self.worker_slider.grid(row=2, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        
        # System Prompt
        self.prompt_label = ctk.CTkLabel(self.main_frame, text="System Prompt (Edição em tempo real de glossário/regras):")
        self.prompt_label.grid(row=1, column=0, padx=10, pady=(10,0), sticky="w")
        
        self.prompt_text = ctk.CTkTextbox(self.main_frame, height=180)
        self.prompt_text.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")
        self.prompt_text.insert("0.0", DEFAULT_SYSTEM_PROMPT)
        
        # Progress & Run
        self.run_frame = ctk.CTkFrame(self.main_frame)
        self.run_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")
        
        self.run_btn = ctk.CTkButton(self.run_frame, text="START TRANSLATION", fg_color="green", hover_color="darkgreen", command=self.start_translation)
        self.run_btn.pack(side="left", padx=10, pady=10)
        
        self.stop_btn = ctk.CTkButton(self.run_frame, text="STOP", fg_color="red", hover_color="darkred", command=self.stop_translation, state="disabled")
        self.stop_btn.pack(side="left", padx=5, pady=10)
        
        self.progress_bar = ctk.CTkProgressBar(self.run_frame)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=10)
        self.progress_bar.set(0)
        
        self.eta_label = ctk.CTkLabel(self.run_frame, text="ETA: --:-- | 0/0")
        self.eta_label.pack(side="right", padx=10)
        
        # Console Log
        self.console = ctk.CTkTextbox(self.main_frame)
        self.console.grid(row=4, column=0, padx=10, pady=10, sticky="nsew")
        self.console.configure(state="disabled")
        
        self.is_running = False

    def update_slider_label(self, value):
        self.slider_label.configure(text=f"Max Parallel Threads: {int(value)}")

    def refresh_books(self):
        for cb, _ in self.checkboxes:
            cb.destroy()
        self.checkboxes.clear()
        
        if not os.path.exists("books_IN"):
            os.makedirs("books_IN")

        files = glob.glob("books_IN/*.epub")
        for i, file in enumerate(files):
            filename = os.path.basename(file)
            cb = ctk.CTkCheckBox(self.books_frame, text=filename)
            cb.grid(row=i, column=0, padx=5, pady=5, sticky="w")
            cb.select() # Check by default
            self.checkboxes.append((cb, file))

    def log(self, msg):
        def append():
            self.console.configure(state="normal")
            self.console.insert("end", msg + "\n")
            self.console.see("end")
            self.console.configure(state="disabled")
        self.after(0, append)

    def update_progress(self, current, total, elapsed, eta):
        def update():
            m, s = divmod(int(eta), 60)
            h, m = divmod(m, 60)
            time_str = f"{h}h {m}m" if h > 0 else f"{m}m {s}s"
            
            self.progress_bar.set(current / total if total > 0 else 0)
            self.eta_label.configure(text=f"ETA: {time_str} | {current}/{total}")
        self.after(0, update)

    def stop_translation(self):
        if self.is_running:
            self.cancel_event.set()
            self.log("[INFO] Pedido de paragem forçada emitido. Aguardando o descarregamento das threads ativas...")
            self.stop_btn.configure(state="disabled")

    def start_translation(self):
        if self.is_running:
            return
            
        selected_files = [file for cb, file in self.checkboxes if cb.get()]
        if not selected_files:
            self.log("[WARNING] Nenhum livro selecionado para traduzir!")
            return

        self.is_running = True
        self.cancel_event.clear()
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.log("\n" + "="*40)
        self.log(f"[INFO] A preparar lista de {len(selected_files)} livros...")
        
        url = self.url_entry.get()
        model = self.model_entry.get()
        workers = int(self.worker_slider.get())
        prompt = self.prompt_text.get("0.0", "end").strip()

        # Disparar numa worker thread para garantir que o UI no se congele.
        threading.Thread(target=self._worker_thread, args=(selected_files, url, model, workers, prompt), daemon=True).start()

    def _worker_thread(self, files, url, model, workers, prompt):
        for file in files:
            self.log(f"\n--- Iniciando: {os.path.basename(file)} ---")
            
            output_file = file.replace("books_IN", "books_OUT").replace(".epub", "_PT_BR.epub")
            
            config = AppConfig(
                input_file=file,
                output_file=output_file,
                model_name=model,
                base_url=url,
                system_prompt=prompt,
                max_workers=workers,
                cancel_event=self.cancel_event
            )
            
            self.after(0, lambda: self.progress_bar.set(0))
            self.after(0, lambda: self.eta_label.configure(text="ETA: Calculando... | 0/0"))
            
            success = process_epub(config, log_callback=self.log, progress_callback=self.update_progress)
            if not success and self.cancel_event.is_set():
                break
            
        self.log("\n[INFO] Fila de processos finalizada.")
        self.after(0, lambda: self.run_btn.configure(state="normal"))
        self.after(0, lambda: self.stop_btn.configure(state="disabled"))
        self.is_running = False

if __name__ == "__main__":
    app = TranslatorApp()
    app.mainloop()
