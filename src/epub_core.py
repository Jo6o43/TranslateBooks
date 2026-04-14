import os
import time
from datetime import datetime

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import AppConfig
from src.chunker import DomBatcher, parse_translated_batch
from src.translator import translate_batch_cached
from src.db_cache import clear_cache_for_epub

import asyncio


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def _write_translation_report(
    config: AppConfig,
    wall_start: float,
    wall_end: float,
    translation_start: float | None,
    translation_end: float | None,
    total_batches: int,
    num_documents: int,
    log_callback,
) -> None:
    out_dir = os.path.dirname(config.output_file) or "."
    base = os.path.splitext(os.path.basename(config.output_file))[0]
    report_path = os.path.join(out_dir, f"{base}_translation_report.txt")

    total_s = wall_end - wall_start
    trans_s = (
        (translation_end - translation_start)
        if translation_start is not None and translation_end is not None
        else None
    )
    try:
        in_size = os.path.getsize(config.input_file)
    except OSError:
        in_size = None
    try:
        out_size = os.path.getsize(config.output_file)
    except OSError:
        out_size = None

    lines = [
        "iTranslateBooks — relatório de tradução",
        "=" * 44,
        f"Gerado em (local): {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Tempos",
        "-" * 44,
        f"  Início (processo): {datetime.fromtimestamp(wall_start).isoformat(timespec='seconds')}",
        f"  Fim (processo):    {datetime.fromtimestamp(wall_end).isoformat(timespec='seconds')}",
        f"  Duração total:     {_format_duration(total_s)} ({total_s:.2f} s)",
    ]
    if trans_s is not None:
        lines.append(f"  Só tradução (API/chunks): {_format_duration(trans_s)} ({trans_s:.2f} s)")
        if trans_s > 0 and total_batches > 0:
            lines.append(f"  Média por chunk:        {trans_s / total_batches:.2f} s")
    lines.extend(
        [
            "",
            "Ficheiros",
            "-" * 44,
            f"  Entrada:  {config.input_file}",
            f"  Saída:    {config.output_file}",
        ]
    )
    if in_size is not None:
        lines.append(f"  Tamanho EPUB origem: {in_size} bytes")
    if out_size is not None:
        lines.append(f"  Tamanho EPUB saída:  {out_size} bytes")

    lines.extend(
        [
            "",
            "Configuração da tradução",
            "-" * 44,
            f"  Modelo:     {config.model_name}",
            f"  Base URL:   {config.base_url}",
            f"  Workers:    {config.max_workers}",
            f"  Contexto:   {'sim' if config.use_context else 'não'}",
            f"  Cache DB:   {config.db_path}",
            "",
            "Volume",
            "-" * 44,
            f"  Documentos com texto: {num_documents}",
            f"  Total de chunks:      {total_batches}",
        ]
    )

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        msg = f"[INFO] Relatório de tradução guardado: {report_path}"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    except OSError as e:
        msg = f"[WARNING] Não foi possível guardar o relatório: {e}"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)


async def process_document(batches, config: AppConfig, sem: asyncio.Semaphore, shared_state: dict, log_callback, progress_callback, total_batches: int):
    context_str = ""
    for batch_tuple in batches:
        if config.cancel_event.is_set():
            return
            
        xml_payload, original_tags = batch_tuple
        
        async with sem:
            translated_xml_or_fallback = await translate_batch_cached(xml_payload, config, context_str, log_callback)
            
        if config.use_context:
            context_str = translated_xml_or_fallback
            
        try:
            translated_map = parse_translated_batch(translated_xml_or_fallback)
            for i, tag in enumerate(original_tags):
                if i in translated_map and translated_map[i]:
                    if tag.name == 'img':
                        tag['alt'] = translated_map[i]
                    else:
                        tag.clear()
                        tag.append(BeautifulSoup(translated_map[i], 'html.parser'))
        except Exception as e:
            msg = f"\n[ERROR] Failed to map back translation batch: {e}"
            if log_callback: log_callback(msg)
            else: print(msg)
            
        shared_state['completed'] += 1
        if progress_callback:
            elapsed = time.time() - shared_state['start_time']
            avg_time_per_batch = elapsed / shared_state['completed']
            remaining_batches = total_batches - shared_state['completed']
            eta = avg_time_per_batch * remaining_batches
            progress_callback(shared_state['completed'], total_batches, elapsed, eta)

def process_epub(config: AppConfig, log_callback=None, progress_callback=None):
    wall_start = time.time()
    if not os.path.exists(config.input_file):
        msg = f"[ERROR] Input file not found: {config.input_file}"
        if log_callback: log_callback(msg)
        else: print(msg)
        return False

    if log_callback: log_callback(f"[*] A carregar EPUB: {os.path.basename(config.input_file)}")
    
    book = epub.read_epub(config.input_file)
    items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    
    documents_batches = []
    total_batches = 0
    
    for item in items:
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        batcher = DomBatcher(max_chars=1500)
        for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'img']):
            batcher.add_tag(tag)
        batches = batcher.finish()
        if batches:
            documents_batches.append(batches)
            total_batches += len(batches)
        
        item._parsed_soup = soup
        
    if total_batches == 0:
        if log_callback: log_callback("[INFO] Documento sem texto detetado para traduzir.")
        return True

    num_documents = len(documents_batches)
    if log_callback: log_callback(f"[*] Tradução em andamento. Total de Envios (Chunks): {total_batches}")
    
    shared_state = {'completed': 0, 'start_time': time.time()}
    sem = asyncio.Semaphore(config.max_workers)
    
    async def run_all():
        tasks = [asyncio.create_task(process_document(batches, config, sem, shared_state, log_callback, progress_callback, total_batches)) for batches in documents_batches]
        await asyncio.gather(*tasks)
        
    translation_start = time.time()
    asyncio.run(run_all())
    translation_end = time.time()
    
    if config.cancel_event.is_set():
        if log_callback: log_callback("[WARNING] Tradução abortada pelo utilizador.")
        return False
        
    if log_callback: log_callback("[*] Tradução das tags concluída. Reconstruindo EPUB...")
    for item in items:
        if hasattr(item, '_parsed_soup'):
            item.set_content(str(item._parsed_soup).encode('utf-8'))

    book.set_language('pt-BR')
    
    # Atualizar Metadados
    titles = book.get_metadata('DC', 'title')
    if titles:
        # Pega no primeiro título e acrescenta "[PT-BR]"
        original_title = titles[0][0]
        # Limpar titles anteriores
        book.metadata['http://purl.org/dc/elements/1.1/']['title'] = []
        book.set_title(f"{original_title} [PT-BR]")
        if log_callback: log_callback(f"[INFO] Título do livro atualizado para: {original_title} [PT-BR]")

    os.makedirs(os.path.dirname(config.output_file) or '.', exist_ok=True)
    epub.write_epub(config.output_file, book)
    wall_end = time.time()

    if config.save_translation_report:
        _write_translation_report(
            config,
            wall_start,
            wall_end,
            translation_start,
            translation_end,
            total_batches,
            num_documents,
            log_callback,
        )

    success_msg = f"[SUCCESS] Livro traduzido e renderizado. Concluído em: {config.output_file}"
    if log_callback: log_callback(success_msg)
    else: print(success_msg)
    
    epub_filename = os.path.basename(config.input_file)
    clear_cache_for_epub(epub_filename)
    if log_callback: log_callback(f"[INFO] Cache da database deletada para o arquivo processado: {epub_filename}.")
    return True
