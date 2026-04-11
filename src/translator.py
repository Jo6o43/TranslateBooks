import openai
import re
from tenacity import retry, stop_after_attempt, wait_exponential
from src.db_cache import get_cached_translation, save_translation
from src.config import AppConfig

def sanitize_text(text: str) -> str:
    text = text.replace('\ufffd', '')
    text = re.sub(r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9faf\u3000-\u303f\uff00-\uffef]', '', text)
    return text

@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
def _call_llm(xml_payload: str, config: AppConfig) -> str:
    client = openai.OpenAI(base_url=config.base_url, api_key="lm-studio")
    response = client.chat.completions.create(
        model=config.model_name,
        messages=[
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": f"Translate while preserving HTML formatting:\n{xml_payload}"}
        ],
        temperature=0.3
    )
    return response.choices[0].message.content

def translate_batch_cached(xml_payload: str, config: AppConfig, log_callback=None) -> str:
    xml_payload = sanitize_text(xml_payload)
    
    cached = get_cached_translation(xml_payload)
    if cached:
        return cached
        
    try:
        translated = _call_llm(xml_payload, config)
        save_translation(xml_payload, translated)
        return translated
    except Exception as e:
        msg = f"\n[ERROR] Translation failed after 4 retries. Skipping chunk. Reason: {e}"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
        return xml_payload
