import streamlit as st
import ollama
import os
import datetime
import requests

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

def get_available_models(client):
    try:
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
        st.error(f"Error listing models: {e}")
        return []

import requests
from bs4 import BeautifulSoup

# ... (previous imports remain)

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
            # Fallback to HTML parsing
            # st.warning("JSON API blocked (403). Falling back to HTML parsing.") # Optional debug
            pass
        else:
            st.error(f"SearXNG JSON error: {response.status_code}")
            return []

    except Exception as e:
        st.error(f"SearXNG connection failed: {e}")
        return []

    # 2. Fallback HTML
    try:
        params.pop("format") # Rimuovi format=json
        response = requests.get(SEARXNG_URL, params=params, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            results = []
            
            # Selettori tipici di SearXNG (possono variare in base al tema)
            # Tema 'simple' o default spesso usa <article class="result">
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
            st.error(f"SearXNG HTML error: {response.status_code}")
            return []
            
    except Exception as e:
        st.error(f"SearXNG HTML parsing failed: {e}")
        return []

# === INTERFACCIA ===
st.set_page_config(page_title="Assistente Ollama NG MEM", page_icon="🤖", layout="centered")
st.title("🤖 Assistente con Ollama & SearXNG (con Memoria)")

# Custom CSS and JS for fixed top input with scrollable chat below
st.markdown("""
<style>
    /* Style for the fixed input area */
    .fixed-input-form {
        position: sticky !important;
        top: 0 !important;
        background: var(--background-color) !important;
        padding: 1rem 0 !important;
        z-index: 1000 !important;
        border-bottom: 2px solid rgba(128, 128, 128, 0.2) !important;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1) !important;
        margin-bottom: 1rem !important;
    }
    
    /* Style the text area */
    .stTextArea textarea {
        border-radius: 10px;
    }
    
    /* Ensure proper spacing */
    .main .block-container {
        padding-top: 0.5rem;
    }
</style>

<script>
    // Function to make the form sticky
    function makeFormSticky() {
        // Find all forms
        const forms = parent.document.querySelectorAll('form');
        
        if (forms.length > 0) {
            // Get the first form (our input form)
            const inputForm = forms[0];
            const formParent = inputForm.closest('[data-testid="stVerticalBlock"]');
            
            if (formParent && !formParent.classList.contains('fixed-input-form')) {
                formParent.classList.add('fixed-input-form');
                console.log('Form made sticky!');
            }
        }
    }
    
    // Run immediately
    makeFormSticky();
    
    // Also run when DOM changes (Streamlit re-renders)
    const observer = new MutationObserver(makeFormSticky);
    observer.observe(parent.document.body, { childList: true, subtree: true });
    
    // Run periodically as backup
    setInterval(makeFormSticky, 500);
</script>
""", unsafe_allow_html=True)





# Sidebar
st.sidebar.header("⚙️ Impostazioni")

# Host Selection
host_choice = st.sidebar.selectbox(
    "Seleziona un host Ollama:",
    ["http://localhost:11434", "http://192.168.1.125:11434"],
    index=1,
    key="host_select"
)
custom_host = st.sidebar.text_input("Oppure inserisci un host personalizzato:", "", key="custom_host")
if custom_host.strip():
    host_choice = custom_host.strip()

if check_host_status(host_choice):
    st.sidebar.success(f"🟢 Host raggiungibile: {host_choice}")
else:
    st.sidebar.error(f"🔴 Host non raggiungibile: {host_choice}")

# Initialize Client
try:
    if API_KEY:
        client = ollama.Client(host=host_choice, headers={"Authorization": f"Bearer {API_KEY}"})
    else:
        client = ollama.Client(host=host_choice)
except Exception as e:
    st.error(f"Failed to initialize client: {e}")
    st.stop()

# Model Selection
models = get_available_models(client)
if not models:
    st.sidebar.warning("Nessun modello trovato. Controlla la connessione.")
    model_choice = None
else:
    model_choice = st.sidebar.selectbox("Seleziona il modello Ollama:", models, index=0)

# Settings
save_logs = st.sidebar.checkbox("Salva log giornaliero", value=True)

# Web Search Toggle (Always available since we use local SearXNG, no API key needed for that)
use_web = st.sidebar.checkbox("Usa SearXNG Web Search", value=True)
st.sidebar.success(f"🔎 SearXNG attivo su {SEARXNG_URL}")

st.sidebar.info(f"Host: **{host_choice}**\n\nModello: **{model_choice}**")

# Chat Interface
if "messages" not in st.session_state:
    st.session_state.messages = []

# User Input - Fixed at top
with st.form(key="prompt_form", clear_on_submit=True):
    prompt = st.text_area(
        "Inserisci la tua domanda...", 
        height=90,  # Approximately 3 lines
        key="user_input",
        placeholder="Scrivi qui la tua domanda...",
        label_visibility="collapsed"
    )
    submit_button = st.form_submit_button("Invia", use_container_width=True)

# Chat history - Scrolls below the input
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if submit_button and prompt.strip():
    # Log User
    if save_logs:
        log_message("Utente", prompt)

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate Response
    if model_choice:
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            
            final_prompt = prompt
            
            # Web Search Logic (SearXNG)
            if use_web:
                with st.status("Ricerca su SearXNG...", expanded=True) as status:
                    try:
                        # Build context-aware search query
                        search_query = prompt
                        
                        # If there's conversation history and the current prompt is short (likely a follow-up)
                        if len(st.session_state.messages) > 1 and len(prompt.strip()) < 50:
                            # For short follow-up questions, extract key context from last user message
                            last_user_msg = None
                            for msg in reversed(st.session_state.messages[:-1]):
                                if msg["role"] == "user":
                                    last_user_msg = msg["content"]
                                    break
                            
                            if last_user_msg:
                                # Extract potential year/date context (e.g., "2025", "2024")
                                import re
                                years = re.findall(r'\b(20\d{2})\b', last_user_msg)
                                if years:
                                    # Add the year to the current query if not already present
                                    if years[0] not in prompt:
                                        search_query = f"{prompt} {years[0]}"
                                        st.write(f"Query arricchita con anno: {search_query}")
                                    else:
                                        st.write(f"Cercando: {prompt}")
                                else:
                                    st.write(f"Cercando: {prompt}")
                            else:
                                st.write(f"Cercando: {prompt}")
                        else:
                            st.write(f"Cercando: {prompt}")
                        
                        results = search_searxng(search_query)
                        
                        if results:
                            st.write(f"Trovati {len(results)} risultati. Utilizzo i primi 3.")
                            results = results[:3]
                            context_parts = []
                            MAX_CHARS_PER_RESULT = 1000
                            MAX_TOTAL_CHARS = 5000
                            total_chars = 0
                            
                            # Log Web Results
                            if save_logs:
                                web_log_content = "\n".join([f"{r.get('title', 'No Title')} - {r.get('url', 'No URL')}" for r in results])
                                log_message("SearXNG Search", web_log_content)

                            for r in results:
                                title = r.get("title", "No Title")
                                url = r.get("url", "#")
                                content = r.get("content", "")
                                
                                st.write(f"- [{title}]({url})")
                                
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
                            
                            # Build context and final prompt
                            context = "\\n\\n".join(context_parts)
                            
                            if context:
                                # Add web context to the current question only
                                # The conversation history will be handled by messages_payload
                                final_prompt = f"{prompt}\\n\\nContesto Web (da SearXNG):\\n{context}\\n\\nRispondi in italiano in modo conciso basandoti sul contesto web fornito."
                                status.update(label="Ricerca Completata", state="complete", expanded=False)
                            else:
                                status.update(label="Nessun contesto utile trovato", state="complete", expanded=False)
                        else:
                            st.write("Nessun risultato trovato.")
                            status.update(label="Nessun risultato", state="complete", expanded=False)
                            
                    except Exception as e:
                        st.error(f"Web search process failed: {e}")
                        status.update(label="Errore Ricerca", state="error")

            # Streaming Logic
            try:
                # Build messages payload with history
                messages_payload = st.session_state.messages[:-1]  # History excluding current prompt
                messages_payload.append({"role": "user", "content": final_prompt})  # Current prompt with context
                
                stream = client.chat(model=model_choice, messages=messages_payload, stream=True)
                
                for chunk in stream:
                    content = None
                    if hasattr(chunk, "message") and hasattr(chunk.message, "content"):
                        content = chunk.message.content
                    elif isinstance(chunk, dict) and "message" in chunk and "content" in chunk["message"]:
                        content = chunk["message"]["content"]
                    
                    if content:
                        full_response += content
                        message_placeholder.markdown(full_response + "▌")
                
                message_placeholder.markdown(full_response)
                
                # Log Assistant
                if save_logs:
                    log_message("Assistente", full_response)
                
                # Add to history
                st.session_state.messages.append({"role": "assistant", "content": full_response})

            except Exception as e:
                st.error(f"Errore generazione: {e}")
    else:
        st.error("Seleziona un modello per continuare.")
