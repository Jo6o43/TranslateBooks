import os
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import INPUT_FILE, OUTPUT_FILE
from src.chunker import DomBatcher, parse_translated_batch
from src.translator import translate_batch_cached
from src.db_cache import close_and_clear_cache

def process_single_batch(batch_tuple):
    xml_payload, original_tags = batch_tuple
    
    # Send to LLM
    translated_xml_or_fallback = translate_batch_cached(xml_payload)
    
    # Try parsing the result back into tags
    try:
        translated_map = parse_translated_batch(translated_xml_or_fallback)
        
        # Apply mapped translations back to the BeautifulSoup objects
        for i, tag in enumerate(original_tags):
            if i in translated_map and translated_map[i]:
                tag.clear()
                tag.append(BeautifulSoup(translated_map[i], 'html.parser'))
    except Exception as e:
        print(f"\n[ERROR] Failed to map back translation batch: {e}")
        # On failure, tags remain as original by reference

def process_epub():
    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] Input file not found: {INPUT_FILE}")
        return

    book = epub.read_epub(INPUT_FILE)
    items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    
    print("Starting translation process (Elite Edition with Checkpoints & Batching)...")
    
    for item in tqdm(items, desc="Chapters"):
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        
        batcher = DomBatcher(max_chars=1500)
        for tag in soup.find_all(['p', 'h1', 'h2', 'h3']):
            batcher.add_tag(tag)
        batches = batcher.finish()
        
        if not batches:
            continue
            
        # Concurrency: Process all batches in the current chapter simultaneously
        # max_workers=5 means 5 simultaneous requests to LM Studio (can adjust)
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(process_single_batch, b) for b in batches]
            for future in as_completed(futures):
                future.result() # Re-raise any unhandled exceptions natively
        
        item.set_content(str(soup).encode('utf-8'))

    book.set_language('pt-BR')
    epub.write_epub(OUTPUT_FILE, book)
    print(f"\n[SUCCESS] Translation completed successfully. Saved as: {OUTPUT_FILE}")
    
    # Limpa a cache porque o programa terminou com sucesso a 100%
    close_and_clear_cache()
    print("[INFO] Database cache was successfully cleared.")
