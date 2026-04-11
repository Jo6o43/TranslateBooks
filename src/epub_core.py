import os
import time
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import AppConfig
from src.chunker import DomBatcher, parse_translated_batch
from src.translator import translate_batch_cached
from src.db_cache import close_and_clear_cache

def process_single_batch(batch_tuple, config: AppConfig, log_callback):
    if config.cancel_event.is_set():
        return
        
    xml_payload, original_tags = batch_tuple
    translated_xml_or_fallback = translate_batch_cached(xml_payload, config, log_callback)
    
    try:
        translated_map = parse_translated_batch(translated_xml_or_fallback)
        for i, tag in enumerate(original_tags):
            if i in translated_map and translated_map[i]:
                tag.clear()
                tag.append(BeautifulSoup(translated_map[i], 'html.parser'))
    except Exception as e:
        msg = f"\n[ERROR] Failed to map back translation batch: {e}"
        if log_callback: log_callback(msg)
        else: print(msg)

def process_epub(config: AppConfig, log_callback=None, progress_callback=None):
    if not os.path.exists(config.input_file):
        msg = f"[ERROR] Input file not found: {config.input_file}"
        if log_callback: log_callback(msg)
        else: print(msg)
        return False

    if log_callback: log_callback(f"[*] A carregar EPUB: {os.path.basename(config.input_file)}")
    
    book = epub.read_epub(config.input_file)
    items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    
    all_batches = []
    
    # Extract all batches globally for accurate ETA progress bar (and to allow batching across chapters)
    for item in items:
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        batcher = DomBatcher(max_chars=1500)
        for tag in soup.find_all(['p', 'h1', 'h2', 'h3']):
            batcher.add_tag(tag)
        batches = batcher.finish()
        if batches:
            all_batches.extend(batches)
        
        # Save soup reference inside the object so we can encode it back later
        item._parsed_soup = soup
        
    total_batches = len(all_batches)
    if total_batches == 0:
        if log_callback: log_callback("[INFO] Documento sem texto detetado para traduzir.")
        return True
        
    if log_callback: log_callback(f"[*] Tradução em andamento. Total de Envios (Chunks): {total_batches}")
    
    completed_batches = 0
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        futures = [executor.submit(process_single_batch, b, config, log_callback) for b in all_batches]
        for future in as_completed(futures):
            future.result() # Catch any unhandled thread exceptions
            
            if config.cancel_event.is_set():
                if log_callback: log_callback("[WARNING] Tradução abortada pelo utilizador.")
                return False
                
            completed_batches += 1
            if progress_callback:
                elapsed = time.time() - start_time
                avg_time_per_batch = elapsed / completed_batches
                remaining_batches = total_batches - completed_batches
                eta = avg_time_per_batch * remaining_batches
                progress_callback(completed_batches, total_batches, elapsed, eta)
                
    if log_callback: log_callback("[*] Tradução das tags concluída. Reconstruindo EPUB...")
    for item in items:
        if hasattr(item, '_parsed_soup'):
            item.set_content(str(item._parsed_soup).encode('utf-8'))

    book.set_language('pt-BR')
    
    os.makedirs(os.path.dirname(config.output_file) or '.', exist_ok=True)
    epub.write_epub(config.output_file, book)
    
    success_msg = f"[SUCCESS] Livro traduzido e renderizado. Concluído em: {config.output_file}"
    if log_callback: log_callback(success_msg)
    else: print(success_msg)
    
    close_and_clear_cache()
    if log_callback: log_callback("[INFO] Cache da database deletada para o arquivo processado.")
    return True
