import gradio as gr
import ollama
import os
import datetime
import requests
from bs4 import BeautifulSoup
import time

# === CONFIGURAZIONE ===
API_KEY = os.getenv("OLLAMA_API_KEY")
SEARXNG_URL = "http://192.168.1.125:8989/search"

# === FUNZIONI DI LOG ===
def get_log_file():
    today = datetime.date.today().strftime("%Y-%m-%d")
    return f"chat_log_{today}.md"

def log_message(role, content):
    log_file = get_log_file()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"### {role} ({timestamp})\n")
        f.write(content + "\n\n")

# === FUNZIONI UTILI ===
def check_host_status(host_url):
    try:
        r = requests.get(f"{host_url}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False

def get_available_models(host_url):
    try:
        # Initialize client with dynamic host
        if API_KEY:
            client = ollama.Client(host=host_url, headers={"Authorization": f"Bearer {API_KEY}"})
        else:
            client = ollama.Client(host=host_url)
            
        response = client.list()
        if hasattr(response, 'models'):
            models = response.models
        else:
            models = response.get('models', [])
            
        model_names = []
        for m in models:
            if hasattr(m, 'model'):
                model_names.append(m.model)
            elif hasattr(m, 'name'):
                model_names.append(m.name)
            elif isinstance(m, dict):
                model_names.append(m.get('model') or m.get('name'))
            else:
                model_names.append(str(m))
        return model_names
    except Exception as e:
        print(f"Error listing models: {e}")
        return []


def extract_text_from_content(content):
    """
    Extracts text from Gradio's multimodal content format.
    Handles:
    - Simple string
    - List of dicts (Gradio 5.x/6.x multimodal)
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join([item["text"] for item in content if isinstance(item, dict) and item.get("type") == "text"])
    return str(content)

def search_searxng(query):
    """
    Esegue una ricerca su SearXNG.
    Tenta prima l'API JSON. Se fallisce (es. 403), fa fallback sul parsing HTML.
    """
    # 1. Tentativo JSON
    params = {
        "q": query,
        "format": "json",
        "language": "it"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # Try JSON first
        response = requests.get(SEARXNG_URL, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("results", [])
        elif response.status_code == 403:
            pass
        else:
            print(f"SearXNG JSON error: {response.status_code}")
            return []

    except Exception as e:
        print(f"SearXNG connection failed: {e}")
        return []

    # 2. Fallback HTML
    try:
        params.pop("format") # Rimuovi format=json
        response = requests.get(SEARXNG_URL, params=params, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            results = []
            
            for article in soup.select("article.result"):
                title_elem = article.select_one("h3 a, h4 a")
                content_elem = article.select_one(".content, .result-content")
                
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    url = title_elem.get("href")
                    content = content_elem.get_text(strip=True) if content_elem else ""
                    
                    results.append({
                        "title": title,
                        "url": url,
                        "content": content
                    })
            
            return results
        else:
            print(f"SearXNG HTML error: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"SearXNG HTML parsing failed: {e}")
        return []

# === CHAT LOGIC ===
def chat_function(message, history, model_name, use_web, host_url):
    if not message:
        return ""
    
    if not model_name:
        yield "⚠️ Seleziona un modello per continuare."
        return

    # Log User
    log_message("Utente", message)

    # Initialize Client
    try:
        if API_KEY:
            client = ollama.Client(host=host_url, headers={"Authorization": f"Bearer {API_KEY}"})
        else:
            client = ollama.Client(host=host_url)
    except Exception as e:
        yield f"⚠️ Errore connessione client: {e}"
        return

    final_prompt = message
    web_context_msg = ""

    # Web Search Logic
    if use_web:
        try:
            search_query = message
            
            # Simple context extraction from history for short queries
            # Gradio history is list of [user, bot] lists
            if len(history) > 0 and len(message.strip()) < 50:
                last_user_msg = history[-1][0]
                import re
                years = re.findall(r'\b(20\d{2})\b', last_user_msg)
                if years and years[0] not in message:
                    search_query = f"{message} {years[0]}"
            
            yield "🔎 Ricerca su SearXNG in corso..."
            results = search_searxng(search_query)
            
            if results:
                results = results[:3]
                context_parts = []
                MAX_CHARS_PER_RESULT = 1000
                MAX_TOTAL_CHARS = 5000
                total_chars = 0
                
                # Log Web Results
                web_log_content = "\n".join([f"{r.get('title', 'No Title')} - {r.get('url', 'No URL')}" for r in results])
                log_message("SearXNG Search", web_log_content)

                for r in results:
                    title = r.get("title", "No Title")
                    url = r.get("url", "#")
                    content = r.get("content", "")
                    
                    if content:
                        truncated_content = content[:MAX_CHARS_PER_RESULT]
                        if total_chars + len(truncated_content) > MAX_TOTAL_CHARS:
                            remaining = MAX_TOTAL_CHARS - total_chars
                            if remaining > 100:
                                truncated_content = content[:remaining]
                                context_parts.append(f"{title}: {truncated_content}...")
                                total_chars += len(truncated_content)
                            break
                        else:
                            context_parts.append(f"{title}: {truncated_content}...")
                            total_chars += len(truncated_content)
                
                context = "\n\n".join(context_parts)
                
                if context:
                    final_prompt = f"{message}\n\nContesto Web (da SearXNG):\n{context}\n\nRispondi in italiano in modo conciso basandoti sul contesto web fornito."
                    web_context_msg = f"\n\n*Contesto web trovato: {len(results)} risultati*"
                else:
                    web_context_msg = "\n\n*Nessun contesto utile trovato*"
            else:
                web_context_msg = "\n\n*Nessun risultato dalla ricerca web*"
                
        except Exception as e:
            print(f"Web search error: {e}")
            web_context_msg = f"\n\n*Errore ricerca web: {e}*"

    # Build messages payload for Ollama
    # Convert Gradio history to Ollama format
    messages_payload = []
    for user_msg, bot_msg in history:
        messages_payload.append({"role": "user", "content": user_msg})
        messages_payload.append({"role": "assistant", "content": bot_msg})
    
    messages_payload.append({"role": "user", "content": final_prompt})

    # Streaming Response
    full_response = ""
    try:
        stream = client.chat(model=model_name, messages=messages_payload, stream=True)
        
        for chunk in stream:
            content = None
            if hasattr(chunk, "message") and hasattr(chunk.message, "content"):
                content = chunk.message.content
            elif isinstance(chunk, dict) and "message" in chunk and "content" in chunk["message"]:
                content = chunk["message"]["content"]
            
            if content:
                full_response += content
                yield full_response
        
        # Log Assistant
        log_message("Assistente", full_response)
        
    except Exception as e:
        yield f"⚠️ Errore generazione: {e}"

# === UI EVENTS ===
def update_models(host_url):
    models = get_available_models(host_url)
    if not models:
        return gr.Dropdown(choices=[], value=None, interactive=True), "🔴 Host non raggiungibile o nessun modello"
    return gr.Dropdown(choices=models, value=models[0] if models else None, interactive=True), "🟢 Host connesso"

# === INTERFACE ===
with gr.Blocks(title="Assistente Ollama NG MEM") as demo:
    gr.Markdown("# 🤖 Assistente con Ollama & SearXNG (Gradio)")
    
    with gr.Row():
        with gr.Column(scale=1):
            with gr.Accordion("⚙️ Impostazioni", open=True):
                host_input = gr.Dropdown(
                    choices=["http://localhost:11434", "http://192.168.1.125:11434"],
                    value="http://192.168.1.125:11434",
                    label="Ollama Host",
                    allow_custom_value=True
                )
                status_output = gr.Markdown("Verifica connessione...")
                
                model_dropdown = gr.Dropdown(
                    label="Modello Ollama",
                    choices=[],
                    interactive=True
                )
                
                refresh_btn = gr.Button("🔄 Aggiorna Modelli")
                
                use_web_checkbox = gr.Checkbox(
                    label="Usa SearXNG Web Search", 
                    value=True,
                    info=f"Server: {SEARXNG_URL}"
                )

        with gr.Column(scale=4):
            chatbot = gr.Chatbot(
                height=600,
                avatar_images=(None, "🤖") 
            )
            
            msg = gr.Textbox(
                show_label=False,
                placeholder="Inserisci la tua domanda...",
                lines=3,
                max_lines=10,
                container=True,
                autofocus=True
            )
            
            with gr.Row():
                submit_btn = gr.Button("Invia", variant="primary")
                clear_btn = gr.Button("Cancella Conversazione")

    # Event Handlers
    
    # Load models on start and on refresh
    demo.load(update_models, inputs=[host_input], outputs=[model_dropdown, status_output])
    refresh_btn.click(update_models, inputs=[host_input], outputs=[model_dropdown, status_output])
    host_input.change(update_models, inputs=[host_input], outputs=[model_dropdown, status_output])

    # Chat interaction
    # Note: gr.ChatInterface is simpler but we want custom layout, so we use submit/click
    
    def user(user_message, history):
        return "", history + [{"role": "user", "content": user_message}]

    def bot(history, model, use_web, host):
        # Extract user message content
        raw_content = history[-1]["content"]
        user_message = extract_text_from_content(raw_content)
        
        if not model:
            history.append({"role": "assistant", "content": "⚠️ Seleziona un modello per continuare."})
            yield history
            return

        # Log User
        log_message("Utente", user_message)

        # Initialize Client
        try:
            if API_KEY:
                client = ollama.Client(host=host, headers={"Authorization": f"Bearer {API_KEY}"})
            else:
                client = ollama.Client(host=host)
        except Exception as e:
            history.append({"role": "assistant", "content": f"⚠️ Errore connessione client: {e}"})
            yield history
            return

        final_prompt = user_message
        
        # Web Search Logic
        if use_web:
            try:
                search_query = user_message
                # Simple context extraction
                if len(history) > 2 and len(user_message.strip()) < 50:
                    last_user_msg = history[-3]["content"] # -1 is user (curr), -2 is bot, -3 is prev user
                    import re
                    years = re.findall(r'\b(20\d{2})\b', last_user_msg)
                    if years and years[0] not in user_message:
                        search_query = f"{user_message} {years[0]}"
                
                # Notify searching...
                history.append({"role": "assistant", "content": "🔎 Ricerca su SearXNG in corso..."})
                yield history
                
                results = search_searxng(search_query)
                
                # Remove the "Searching..." message
                history.pop()
                
                if results:
                    results = results[:3]
                    context_parts = []
                    MAX_CHARS_PER_RESULT = 1000
                    MAX_TOTAL_CHARS = 5000
                    total_chars = 0
                    
                    # Log Web Results
                    web_log_content = "\n".join([f"{r.get('title', 'No Title')} - {r.get('url', 'No URL')}" for r in results])
                    log_message("SearXNG Search", web_log_content)

                    for r in results:
                        title = r.get("title", "No Title")
                        url = r.get("url", "#")
                        content = r.get("content", "")
                        
                        if content:
                            truncated_content = content[:MAX_CHARS_PER_RESULT]
                            if total_chars + len(truncated_content) > MAX_TOTAL_CHARS:
                                remaining = MAX_TOTAL_CHARS - total_chars
                                if remaining > 100:
                                    truncated_content = content[:remaining]
                                    context_parts.append(f"{title}: {truncated_content}...")
                                    total_chars += len(truncated_content)
                                break
                            else:
                                context_parts.append(f"{title}: {truncated_content}...")
                                total_chars += len(truncated_content)
                    
                    context = "\n\n".join(context_parts)
                    
                    if context:
                        final_prompt = f"{user_message}\n\nContesto Web (da SearXNG):\n{context}\n\nRispondi in italiano in modo conciso basandoti sul contesto web fornito."
            except Exception as e:
                print(f"Web search error: {e}")

        # Build messages payload for Ollama
        # history contains [{"role": "user", "content": "..."}] (current message is last)
        # We need to pass everything EXCEPT the last one as history, and the last one (modified) as prompt
        # CRITICAL: Sanitize ALL history messages to ensure they are strings, not lists, 
        # otherwise Ollama client (Pydantic) will fail on 2nd turn.
        
        messages_payload = []
        for msg in history:
             # msg is a dict, we need to copy and clean the content
             cleaned_msg = msg.copy()
             cleaned_msg["content"] = extract_text_from_content(msg["content"])
             messages_payload.append(cleaned_msg)

        # Replace the last message content with our finalized prompt (with context if any)
        messages_payload[-1]["content"] = final_prompt

        # Streaming Response
        history.append({"role": "assistant", "content": ""})
        full_response = ""
        
        try:
            stream = client.chat(model=model, messages=messages_payload, stream=True)
            
            for chunk in stream:
                content = None
                if hasattr(chunk, "message") and hasattr(chunk.message, "content"):
                    content = chunk.message.content
                elif isinstance(chunk, dict) and "message" in chunk and "content" in chunk["message"]:
                    content = chunk["message"]["content"]
                
                if content:
                    full_response += content
                    history[-1]["content"] = full_response
                    yield history
            
            # Log Assistant
            log_message("Assistente", full_response)
            
        except Exception as e:
            history[-1]["content"] = f"⚠️ Errore generazione: {e}"
            yield history

    # Submit handler
    msg.submit(user, [msg, chatbot], [msg, chatbot], queue=False).then(
        bot, [chatbot, model_dropdown, use_web_checkbox, host_input], chatbot
    )
    
    submit_btn.click(user, [msg, chatbot], [msg, chatbot], queue=False).then(
        bot, [chatbot, model_dropdown, use_web_checkbox, host_input], chatbot
    )
    
    clear_btn.click(lambda: [], None, chatbot, queue=False)

if __name__ == "__main__":
    demo.launch()
