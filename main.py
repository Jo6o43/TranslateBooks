import argparse
from tqdm import tqdm
import time
import os
import glob
from src.config import AppConfig
from src.epub_core import process_epub
from src.paths_store import ensure_books_dirs, load_app_settings, output_path_for_epub

def _format_time(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0: return f"{h}h {m}m"
    return f"{m}m {s}s"

class CLI_Runner:
    def __init__(self):
        self.pbar = None

    def log(self, msg):
        if self.pbar:
            self.pbar.write(msg)
        else:
            print(msg)

    def progress(self, current, total, elapsed, eta):
        if self.pbar is None:
            self.pbar = tqdm(total=total, desc="Progress", unit="batch")
        
        self.pbar.n = current
        self.pbar.set_postfix({"ETA": _format_time(eta)})
        self.pbar.refresh()
        
        if current >= total and self.pbar:
            self.pbar.close()
            self.pbar = None

def run_translation(input_file, output_file, max_workers, model, base_url):
    s = load_app_settings()
    config = AppConfig(
        input_file=input_file,
        output_file=output_file,
        max_workers=max_workers,
        model_name=model,
        base_url=base_url,
        save_translation_report=bool(s.get("save_translation_report", False)),
    )
    runner = CLI_Runner()
    process_epub(config, log_callback=runner.log, progress_callback=runner.progress)

def main():
    parser = argparse.ArgumentParser(description="iTranslateBooks (CLI)")
    parser.add_argument("--input", type=str, help="Single input file")
    parser.add_argument("--output", type=str, help="Output file")
    parser.add_argument("--workers", type=int, default=3, help="Max parallel workers")
    parser.add_argument("--model", type=str, default="qwen3-v1-8b-instruct")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:1234/v1")
    
    args = parser.parse_args()
    
    if args.input:
        output = args.output or args.input.replace(".epub", "_PT_BR.epub")
        run_translation(args.input, output, args.workers, args.model, args.url)
    else:
        books_in, books_out = ensure_books_dirs()
        print(f"[INFO] Nenhum input definido. Buscando EPUBs em: {books_in}")
        pattern = os.path.join(books_in, "*.epub")
        files = glob.glob(pattern)
        if not files:
            print(f"[INFO] Nenhum livro .epub encontrado em {books_in}")
            return
        for file in files:
            filename = os.path.basename(file)
            output = args.output or output_path_for_epub(file, books_out)
            run_translation(file, output, args.workers, args.model, args.url)

if __name__ == "__main__":
    main()
