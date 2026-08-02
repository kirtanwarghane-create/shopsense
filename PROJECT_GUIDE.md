# ShopSense Project Guide

## 1. What This Project Is

ShopSense is a product-recommendation chatbot built **specifically for shoppers in India**. A person can type a shopping request such as:

> Suggest me the best headphones under ₹5000.

ShopSense reads the request, considers the conversation so far, and produces a focused recommendation — always priced in Indian Rupees (₹), and only for products actually available in India (Amazon.in, Flipkart, Croma, Reliance Digital, Tata CLiQ, or official Indian retailer/brand sites). When the answer depends on information that changes frequently, such as current prices, availability, recent releases, specifications, or reviews, the server searches the live web before answering.

The project has two parts:

- **The frontend:** the page a person sees and uses in a web browser.
- **The backend:** the private service that receives messages, talks to the AI model, optionally searches the web, and sends the answer back.

The frontend does not call the AI or search services directly. It calls the local backend, which keeps the API keys out of the browser.

## 2. What A Non-Technical User Experiences

1. The user opens the ShopSense page.
2. The page checks whether the backend is available.
3. The user can optionally tap **Refine search** to set a preferred brand, a budget in ₹, and/or which shopping platforms to compare (Amazon, Flipkart, Croma, Reliance Digital).
4. The user types a product question and presses **Send**. Pressing Enter also sends the message; Shift+Enter creates a new line.
5. The message appears on the right side of the conversation, with small tags showing any filters that were applied.
6. A small "searching and thinking" indicator appears while the backend works.
7. The assistant may search for current information if the question needs it — including a separate search per platform when a price comparison is requested.
8. The recommendation appears on the left side, formatted with headings, bold text, bullet points, prices in ₹, and a link for every product mentioned.
9. If platforms were being compared, the answer includes a small table (Platform | Price | Link | Notes) and a sentence naming the cheapest option.
10. The page remembers the conversation in the browser while the page remains open, so follow-up questions can refer to earlier messages.
11. A small status indicator tells the user whether the backend is online and whether live search is enabled.

The assistant is instructed to ask for useful missing details, such as budget, intended use, brand preference, or required features. It is also instructed to explain trade-offs rather than pretending that one product is perfect for everyone, and to never show a price in any currency other than ₹.

## 3. Main Capabilities

### Product recommendations (India-only)

The assistant can compare products, suggest options for a ₹ budget, and adapt recommendations to a use case. Every product recommendation must include a working link (from search results) and a price in ₹; if a link or price genuinely can't be found, the assistant says so explicitly rather than guessing or omitting it.

### Guided filters (brand, budget, platform comparison)

The frontend includes an optional "Refine search" panel where the user can set:

- **Preferred brand** — free text (e.g. Sony, boAt, JBL).
- **Budget** — a min/max range in ₹.
- **Compare prices on** — toggleable chips for Amazon, Flipkart, Croma, and Reliance Digital.

These are packed into a hidden line appended to the user's message (e.g. `[Filters — Preferred brand: Sony | Budget: ₹10000–100000 (INR) | Compare prices on: Amazon, Flipkart]`), which the backend's system prompt is instructed to treat as hard constraints rather than plain conversation text. When platforms are specified, the backend runs one search per platform so it can report each one's real current price instead of a single blended guess.

### Current web information

When Tavily is configured, the AI can request a web search for information that may have changed. The search results are returned to the AI so it can use them while preparing the final response. The AI may call the search tool multiple times in a single turn (e.g. once per shopping platform).

### Conversation context

The browser sends previous user and assistant messages with each new request. The backend only uses the last 20 history items when building the AI request, which prevents the request from growing indefinitely.

### Backend status display

The frontend calls the health endpoint when it loads. It can show three practical states:

- **Live search on:** the Flask server is reachable and a Tavily key is configured.
- **Search key missing:** the Flask server is reachable, but Tavily live search is disabled.
- **Backend offline:** the browser could not reach Flask.

## 4. Project Structure

```text
ChatBot/
|-- backend/
|   |-- app.py              # Flask API and AI/search orchestration
|   |-- requirements.txt    # Python packages and pinned versions
|   |-- .env.example        # Safe template for environment variables
|   |-- .env                # Local secrets and settings; do not commit
|   `-- venv/                # Local Python virtual environment
|-- frontend/
|   `-- index.html          # Complete browser interface and JavaScript
|-- README.md               # Existing quick-start documentation
`-- PROJECT_GUIDE.md         # This detailed project explanation
```

The frontend is intentionally a single HTML file. It contains the page structure, styling, and browser-side JavaScript. The backend is also intentionally small: the main application logic is in `backend/app.py`.

## 5. High-Level Architecture

```text
User
  |
  v
Browser running frontend/index.html
  |
  |  GET /api/health
  |  POST /api/chat
  v
Flask backend running on localhost:5000
  |
  +--> Groq chat-completion model
  |       |
  |       +--> May request web_search (once per platform, if comparing)
  |
  +--> Tavily Search API, when a Tavily key is configured
  |
  v
Final Markdown recommendation (₹ prices + links) returned as JSON
  |
  v
Browser renders the recommendation in the chat
```

### Responsibility of each part

| Part | Responsibility |
|---|---|
| `frontend/index.html` | Displays the chat, accepts input and filters, calls the backend, renders replies, and keeps temporary conversation history. |
| Flask in `backend/app.py` | Validates requests, adds instructions, limits history, calls Groq, executes requested tools, catches malformed tool-call text, and returns JSON. |
| Groq | Generates the assistant response and decides whether it needs the `web_search` tool. |
| Tavily | Performs the live web search when the AI requests it and a Tavily key is available. |
| `python-dotenv` | Loads values from `backend/.env` into the backend process. |
| `flask-cors` | Allows the separately served frontend to call the Flask backend from the browser. |

## 6. How One Chat Request Works

The complete request path is as follows:

1. The user submits text in the browser, optionally after setting filters.
2. JavaScript builds the final message: the visible text plus a hidden `[Filters — ...]` line if any filters are set, adds the visible text (with filter tags) to the chat, and adds the full message to its local `history` array.
3. JavaScript sends a `POST` request to `http://localhost:5000/api/chat`.
4. The request contains the new message and the conversation history.
5. Flask reads the JSON body. If `message` is missing or empty after trimming, Flask returns HTTP `400`.
6. Flask creates a model message list. It starts with the ShopSense system prompt (India-only, ₹-only, mandatory links, filter-parsing rules), adds up to the last 20 valid user/assistant messages, and adds the new user message.
7. Flask calls Groq with the configured model, the instructions, and the `web_search` tool definition.
8. Groq can do one of three things:
   - Return a final answer immediately.
   - Ask the backend to call `web_search` with a search query (possibly several times in one turn, e.g. once per platform).
   - Occasionally, print what looks like a tool call as plain text instead of using the real tool-calling channel (see the bug-fix note below). The backend detects this and handles it transparently.
9. If a search is requested (real or detected from text), Flask sends the query to Tavily. Tavily returns a short answer and a list of result titles, URLs, and content snippets.
10. Flask adds the search result back into the model conversation and calls Groq again.
11. The backend repeats this process when necessary, with a maximum of six model/tool rounds for one request (raised from four to comfortably support multi-platform comparisons).
12. Once Groq returns a normal assistant message with no real or fake tool call left in it, Flask sanitizes the text (stripping any residual pseudo tool-call debris) and returns it as JSON along with search metadata.
13. The browser removes the typing indicator, renders the Markdown-like response, and adds the assistant answer to its local history.

The result is not streamed token by token. The browser waits for the complete response before displaying the assistant message.

### Bug fix: fake tool-call text leaking into replies

**The problem:** occasionally the model would write something like

```
<function\web_search{"query": "Sony headphones price in India within 10000-100000"}</function>
```

directly into its visible reply, instead of using the actual function-calling mechanism. Because this wasn't a real `tool_calls` entry, the backend previously had no way to catch it — it just got returned to the user as raw, broken-looking text.

**The fix**, in `backend/app.py`:

- A regex (`FAKE_QUERY_RE`) scans the model's plain-text content for a `"query": "..."` pattern whenever there are no real tool calls.
- If found, the backend treats it as an *intended* search: it runs the query against Tavily itself, feeds the result back into the conversation as a system note, and asks the model to answer again — this time properly, in Markdown only.
- A second regex (`FAKE_TOOL_TAG_RE`) strips any leftover `<function>...</function>`-style debris from the final text as a last safety net, so even if a stray tag slips through, the user never sees it.
- The system prompt now also explicitly forbids printing tool-call syntax as visible text (rule 9), which reduces how often this happens in the first place.

## 7. Backend Details

### Startup and configuration

At startup, `app.py` loads environment variables from `.env` and reads:

- `GROQ_API_KEY`: required. The application raises an error and stops if it is missing.
- `TAVILY_API_KEY`: optional. Without it, the chat still works, but live search is unavailable.
- `GROQ_MODEL`: optional. Defaults to `llama-3.3-70b-versatile`.
- `PORT`: optional. Defaults to `5000`.

The Groq client is created once during startup using `GROQ_API_KEY`.

### System prompt

The system prompt is the long set of instructions sent to Groq before the conversation. It defines the assistant as ShopSense — built specifically for India — and tells it to:

- Search whenever current information is needed.
- Avoid inventing prices, specs, or availability.
- Quote every price in ₹ (Indian Rupees) only, never $, €, or £, converting or re-searching if a result comes back in another currency.
- Only recommend products actually sold in India, via Indian retailers.
- Format recommendations clearly using Markdown, with a **mandatory link** for every product named (or an explicit "(link not found)" if none exists).
- Parse the `[Filters — ...]` line as hard constraints (brand, ₹ budget, platforms to compare) and run one search per requested platform, presenting results as a Platform | Price (₹) | Link | Notes table with the cheapest option called out.
- Mention trade-offs.
- Never print literal tool-call syntax (like `<function=web_search>`) as visible text — only use the real function-calling mechanism.
- Stay focused and ask a follow-up question only when it would improve the recommendation.

Changing this prompt changes the assistant's behavior without changing the frontend.

### Tool definition

The backend exposes one model tool named `web_search`. The tool schema tells Groq that it accepts one required string called `query`, and its description explicitly notes the tool can be called multiple times in one turn (e.g. once per shopping platform) to compare real ₹ prices across sites.

The model does not directly access Tavily. It only requests the named tool. The backend is responsible for checking the tool name, decoding the arguments, calling Tavily, and putting the result back into the model conversation.

### Web search implementation

`web_search()` sends a `POST` request to Tavily with:

- The Tavily API key.
- The user's search query selected by the model.
- `search_depth: advanced`.
- Up to five results.
- `include_answer: true`.
- A 20-second request timeout.

The backend reduces each result to its title, URL, and content snippet before passing it to Groq. This keeps the model input smaller than sending complete web pages, and is also where product links for the final answer come from.

If Tavily is not configured, the function returns an explanatory error object instead of crashing. The model is told that live search is unavailable and should be clear that current information may not be current.

### Error behavior

- Missing message: HTTP `400` with `{"error": "message is required"}`.
- Unexpected backend, Groq, or Tavily exception: HTTP `500` with an `error` field. The backend also prints a traceback in its terminal.
- Tavily request failure: represented as a search error that the model can account for.
- Too many tool-call rounds (more than six): a fallback response asks the user to narrow or rephrase the request.
- Fake/malformed tool-call text: caught and handled as described above, rather than surfaced as an error or raw text.

### Health endpoint

`GET /api/health` returns a small status object:

```json
{
  "status": "ok",
  "model": "llama-3.3-70b-versatile",
  "search_enabled": true
}
```

`search_enabled` is calculated from whether `TAVILY_API_KEY` exists. It does not prove that the key is valid or that Tavily is currently reachable; it only reports configuration presence.

## 8. Frontend Details

The frontend uses standard HTML, CSS, and JavaScript. Tailwind CSS is loaded from a CDN for utility classes. Fonts are loaded from Google Fonts. Because these assets are external, the browser needs internet access for the intended visual appearance.

### Visual layout

The page includes:

- A ShopSense header with a live status badge.
- A scrolling "hype" marquee banner.
- A hero section with a tilting product-recommendation card and a "Made for India" badge.
- A scrollable conversation area.
- An introductory message with three quick-prompt suggestion chips.
- A "Refine search" filters panel (brand, ₹ budget, platform comparison chips).
- A growing text box and Send button.
- A short reminder to verify price and availability before buying.

The page uses a bold, colorful neo-brutalist style (thick borders, hard drop shadows, sticker-style chips) with small delight touches — a confetti burst on send, a tilting hero card, gradient-animated headline text — all of which respect `prefers-reduced-motion`.

### Browser-side state

The variable `history` is an in-memory JavaScript array. It is not saved to a database, browser storage, or user account. Refreshing or closing the page clears it.

Before each request, the current user message (including any filter suffix) is added to `history`. After a successful response, the assistant message is added as well. The backend receives this history on the next request.

### Filters and message augmentation

Selecting a brand, budget, or platform in the "Refine search" panel doesn't change what's typed in the text box. Instead, at send time the frontend:

1. Builds a hidden suffix like `\n\n[Filters — Preferred brand: Sony | Budget: ₹10000–100000 (INR) | Compare prices on: Amazon, Flipkart]`.
2. Sends `visible text + suffix` to the backend as the actual `message`.
3. Shows only the visible text in the chat bubble, plus small readable tags (e.g. `🏷️ Sony`, `💰 ₹10000–100000`, `🛒 Amazon, Flipkart`) underneath it, so the user can confirm what was applied.

### Rendering assistant responses

The backend returns Markdown-style text. The frontend has a small renderer that supports the formats the system prompt primarily asks for:

- Bold text using `**text**`.
- Markdown links using `[label](https://example.com)`.
- Level-two and level-three headings.
- Bullet lists beginning with `-` or `*`.
- Paragraphs separated by blank lines.

The frontend escapes the original response before applying its limited formatting conversions. Links open in a new browser tab with `noopener` enabled.

### Input behavior

- The text box automatically grows up to 140 pixels.
- Enter submits the message.
- Shift+Enter inserts a line break.
- The input and Send button are disabled during a request to avoid overlapping submissions.
- The interface scrolls to the newest message after adding content.
- Quick-prompt chips and the send button trigger a small confetti animation as visual feedback.

## 9. API Reference

### `GET /api/health`

Purpose: check whether the Flask backend is reachable and report its configured model and search-key status.

Example PowerShell request:

```powershell
Invoke-RestMethod http://localhost:5000/api/health
```

Example response:

```json
{
  "status": "ok",
  "model": "llama-3.3-70b-versatile",
  "search_enabled": true
}
```

### `POST /api/chat`

Purpose: send a new user request and optional conversation context.

Request body:

```json
{
  "message": "Suggest me the best Sony headphones\n\n[Filters — Preferred brand: Sony | Budget: ₹10000–100000 (INR) | Compare prices on: Amazon, Flipkart]",
  "history": [
    {
      "role": "user",
      "content": "I prefer good noise cancellation."
    },
    {
      "role": "assistant",
      "content": "What is your budget?"
    }
  ]
}
```

Successful response:

```json
{
  "reply": "## Sony Headphones Within Budget\n\n| Platform | Price (₹) | Link | Notes |\n|---|---|---|---|\n| Amazon | ₹24,990 | [View](https://amazon.in/...) | In stock |\n| Flipkart | ₹25,490 | [View](https://flipkart.com/...) | In stock |\n\nAmazon currently has the lowest price.\n",
  "used_search": true,
  "searches": [
    "Sony headphones price site:amazon.in",
    "Sony headphones price site:flipkart.com"
  ]
}
```

Field meanings:

| Field | Meaning |
|---|---|
| `reply` | The final assistant response, normally formatted as Markdown text with ₹ prices and links. |
| `used_search` | `true` if Groq requested (or was detected attempting) the web-search tool during this request. |
| `searches` | The search queries the backend actually attempted. |
| `error` | Present when the request fails. |

The backend accepts only `user` and `assistant` roles from the submitted history. Other roles are ignored. History entries without content are ignored.

## 10. Installation And Running

### Prerequisites

Install or obtain:

- Windows PowerShell.
- Python 3.10 or newer.
- A Groq API key.
- A Tavily API key if current web search is required.
- Internet access for Groq, Tavily, Tailwind CDN, and Google Fonts.

### Create the backend environment

From the project root:

```powershell
Set-Location .\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The dependency list intentionally pins `httpx==0.27.2`. This is compatible with the pinned Groq client version. Installing a newer incompatible `httpx` can cause an error about an unexpected `proxies` argument when the Groq client starts.

If PowerShell prevents activation, use the virtual environment's Python executable directly or enable scripts for the current user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Configure secrets

Create the local environment file:

```powershell
Copy-Item .env.example .env
```

Open `backend/.env` and replace the placeholder values:

```dotenv
GROQ_API_KEY=gsk_your_real_groq_key
TAVILY_API_KEY=tvly_your_real_tavily_key
GROQ_MODEL=llama-3.3-70b-versatile
PORT=5000
```

`GROQ_API_KEY` is mandatory. `TAVILY_API_KEY` is optional, but omitting it disables current web search.

### Start the backend

Keep the PowerShell terminal in the `backend` directory with the virtual environment active:

```powershell
python .\app.py
```

The default backend address is:

```text
http://localhost:5000
```

The server binds to `0.0.0.0`, which means it listens on all network interfaces available to the machine. The application still uses port `5000` unless `PORT` is changed.

To use another port for the current PowerShell session:

```powershell
$env:PORT = "5050"
python .\app.py
```

If the port changes, update both `API_URL` and `HEALTH_URL` near the top of `frontend/index.html` to use the same port.

### Serve the frontend

Open a second PowerShell terminal from the project root:

```powershell
python -m http.server 5500 --directory .\frontend
```

Open this address in a browser:

```text
http://localhost:5500
```

Serving the page over HTTP is preferred to opening `index.html` directly as a `file://` URL because browser security rules can restrict requests made from local files.

## 11. Useful Manual Checks

### Check backend health

```powershell
Invoke-RestMethod http://localhost:5000/api/health
```

A successful result confirms that Flask is running. The `search_enabled` value tells you whether a Tavily value was loaded.

### Send a chat request without the browser

```powershell
$body = @{
  message = "Best Sony headphones under 20000 rupees"
  history = @()
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://localhost:5000/api/chat `
  -ContentType "application/json" `
  -Body $body
```

This is useful for separating backend problems from frontend problems.

### Interpret common results

- Health request fails: Flask is not running, the port is wrong, or a local firewall is blocking the connection.
- Health works but chat returns HTTP `500`: inspect the backend terminal traceback and verify the Groq key, model name, and internet connection.
- Chat works but `used_search` is false: the model may not have judged live information necessary, or Tavily is not configured.
- Reply shows a price in $ or a non-Indian retailer: re-run the request — the system prompt forbids this, but if it recurs often, tighten rule 3 in `SYSTEM_PROMPT` further or lower `temperature`.
- The browser says backend offline but PowerShell health works: check the URLs in `frontend/index.html`, then reload the frontend page.

## 12. Dependency Reference

The exact versions are recorded in `backend/requirements.txt`:

| Package | Why it is used |
|---|---|
| `flask` | Provides the HTTP server and API routes. |
| `flask-cors` | Allows the frontend origin to call the backend. |
| `groq` | Provides the Python client for Groq chat completions and tool calling. |
| `httpx` | HTTP client dependency kept at a compatible version for the Groq package. |
| `python-dotenv` | Loads `.env` configuration values. |
| `requests` | Sends the backend's Tavily HTTP request. |

The browser additionally downloads Tailwind CSS and fonts from external URLs declared in `frontend/index.html`.

## 13. Security And Privacy Boundaries

- API keys belong in `backend/.env`, never in `frontend/index.html`.
- `.env` should not be committed to source control or shared publicly.
- The frontend sends conversation text to the Flask backend. The backend sends the conversation to Groq, and search queries/results may be sent to Tavily.
- There is no login, user account, database, or persistent conversation storage.
- CORS is enabled broadly with `CORS(app)`, which is convenient for local development but should be restricted to known frontend origins before production deployment.
- Flask is started with `debug=True`. Debug mode is useful during development but should be disabled in a public deployment because detailed errors and debug tooling can expose sensitive information.
- The app does not enforce authentication, rate limits, request-size limits, or per-user quotas.
- Product prices and availability can change. Even with live search, the user should verify the final price, stock status, seller, shipping, and return policy before purchasing.

## 14. Current Limitations

1. **No persistent history:** refreshing the page clears the conversation.
2. **No streaming:** the user sees the answer only after the complete backend request finishes.
3. **No product database:** recommendations are generated from the AI model and optional live search, not from a curated catalog.
4. **Search accuracy depends on external services:** Tavily may fail, return incomplete information, or expose conflicting sources.
5. **India-only by design:** the app assumes an Indian user, ₹ currency, and Indian retailers. It is not suited for other regions/currencies without editing the system prompt, filter platform list, and frontend copy.
6. **No strict product verification:** the system does not independently confirm every price or specification, and while a link is now mandatory, it isn't independently checked for validity.
7. **Simple Markdown rendering:** the frontend supports only a limited subset of Markdown (bold, links, headings, bullet lists, and simple tables render as plain text rows rather than a styled `<table>`).
8. **Development-oriented deployment:** the built-in Flask server and debug mode are not a production hosting strategy.
9. **External frontend assets:** the visual styling can be affected if the CDN or Google Fonts request is unavailable.
10. **Fixed local API URLs:** changing the backend port requires editing the frontend constants.
11. **Occasional fake tool-call text:** the backend now catches and recovers from this, but it's a model-behavior quirk being worked around, not eliminated at the source — very rare recurrences are possible.

## 15. Sensible Future Improvements

Possible next steps, in increasing order of scope:

- Move the API URL into frontend configuration instead of hard-coding it.
- Add a production WSGI server such as Gunicorn or Waitress.
- Disable debug mode outside development.
- Restrict CORS to the real frontend origin.
- Add structured logging, request IDs, and clearer user-facing error categories.
- Add rate limiting and authentication before exposing the service publicly.
- Store conversations in a database if users need history across sessions.
- Stream assistant output for a faster perceived response.
- Add tests for health checks, invalid requests, tool dispatch, search failures, history trimming, and the fake-tool-call fallback.
- Render actual Markdown tables as styled HTML `<table>` elements in the frontend instead of plain text rows.
- Add more Indian platforms to the filter list (e.g. Tata CLiQ, Myntra for apparel) and let users type a custom platform.
- Add a deployment configuration for a hosted frontend and backend.

## 16. Short Explanation For A Project Presentation

ShopSense is a web-based shopping assistant built for the Indian market. The browser provides a chat interface — including optional filters for brand, ₹ budget, and which shopping platforms to compare — while a Flask backend coordinates the conversation. Groq supplies the language model that understands the request and writes the recommendation, always in ₹ with a link per product. When the answer requires current shopping information, Groq asks the backend to use a web-search tool, once per platform if a price comparison was requested. The backend calls Tavily, sends the search findings back to Groq, and returns the finished recommendation to the browser — including a small safeguard that catches and cleans up the rare case where the model tries to print a tool call as plain text instead of actually invoking it. API keys stay on the backend, and the browser keeps only temporary conversation history in memory.