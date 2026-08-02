# ShopSense

ShopSense is a small product-recommendation chatbot with a Flask backend and a single-page HTML frontend. It uses Groq for chat completions and optional Tavily web search for current prices, availability, product releases, specifications, and reviews.

The backend supports Groq tool calling. When the model needs fresh information, it requests the `web_search` tool, the server executes that search through Tavily, and the search result is sent back to the model before the final recommendation is returned.

## Project Structure

```text
ChatBot/
|-- backend/
|   |-- app.py
|   |-- requirements.txt
|   |-- .env.example
|   `-- .env                 # local secrets; do not commit
|-- frontend/
|   `-- index.html
`-- README.md
```

## Requirements

- Windows PowerShell
- Python 3.10 or newer
- A Groq API key from [Groq Console](https://console.groq.com/keys)
- A Tavily API key from [Tavily](https://app.tavily.com/) if live web search is wanted
- Internet access from the backend process

## Configuration

The backend loads environment variables from `backend/.env` using `python-dotenv`.

1. Open PowerShell in the `backend` directory.
2. Create a local environment file from the example:

```powershell
Copy-Item .env.example .env
```

3. Open `.env` and set at least `GROQ_API_KEY`:

```dotenv
GROQ_API_KEY=gsk_your_real_groq_key
TAVILY_API_KEY=tvly_your_real_tavily_key
GROQ_MODEL=llama-3.3-70b-versatile
PORT=5000
```

`GROQ_API_KEY` is required. `TAVILY_API_KEY` is optional; without it, the health endpoint reports that search is disabled and the model receives a message explaining that live search is unavailable.

Never put API keys in `frontend/index.html`, commit them to source control, or paste them into a client-side request. The frontend only talks to the Flask server.

## Installation

From the repository root:

```powershell
Set-Location .\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, either run the backend with the virtual environment's Python directly or allow scripts for the current user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

The `requirements.txt` file deliberately pins `httpx==0.27.2`. The current `groq==0.11.0` client passes a `proxies` argument while constructing its HTTP client; newer `httpx` releases removed that argument. Installing a newer `httpx` with this Groq SDK causes:

```text
TypeError: Client.__init__() got an unexpected keyword argument 'proxies'
```

Always install from `requirements.txt` after creating or recreating the virtual environment.

## Run The Application

The application has a backend process and a frontend process. Start the backend first.

### 1. Start Flask

From `backend` with the virtual environment activated:

```powershell
python .\app.py
```

Expected output includes a server address similar to:

```text
http://127.0.0.1:5000
```

The app listens on `0.0.0.0` and uses port `5000` by default. Change the port for the current PowerShell session if needed:

```powershell
$env:PORT = "5050"
python .\app.py
```

If the port changes, update `API_URL` and `HEALTH_URL` near the top of the script in `frontend/index.html` to use the same port.

### 2. Serve the frontend

Keep the backend terminal running. Open a second PowerShell terminal from the repository root and run:

```powershell
python -m http.server 5500 --directory .\frontend
```

Open [http://localhost:5500](http://localhost:5500) in a browser. Serving the HTML over HTTP avoids browser restrictions that can occur when opening it directly as a `file://` URL.

The frontend is configured for:

- Chat API: `http://localhost:5000/api/chat`
- Health check: `http://localhost:5000/api/health`

## API Reference

### `GET /api/health`

Returns server status and whether a Tavily key is configured.

Example response:

```json
{
  "status": "ok",
  "model": "llama-3.3-70b-versatile",
  "search_enabled": true
}
```

### `POST /api/chat`

Accepts a JSON object with the new user message and optional prior conversation history:

```json
{
  "message": "Recommend wireless earbuds under $100 for commuting",
  "history": [
    {"role": "user", "content": "I prefer good noise cancellation."},
    {"role": "assistant", "content": "What is your budget?"}
  ]
}
```

Successful response:

```json
{
  "reply": "## Recommendations\n...",
  "used_search": true,
  "searches": ["wireless earbuds under $100 commuting noise cancellation"]
}
```

The server keeps at most the last 20 history items when building a model request. An empty or missing `message` returns HTTP `400`:

```json
{"error": "message is required"}
```

Unexpected Groq or Tavily failures return HTTP `500` with an `error` field. The Flask process also prints the traceback to its terminal for diagnosis.

### PowerShell API checks

With the backend running:

```powershell
Invoke-RestMethod http://localhost:5000/api/health

$body = @{
  message = "Best laptop for programming under 1000 dollars"
  history = @()
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://localhost:5000/api/chat `
  -ContentType "application/json" `
  -Body $body
```

## How The Request Flow Works

1. The browser checks `/api/health` and displays backend/search status.
2. The browser sends the current message and conversation history to `/api/chat`.
3. Flask prepends the ShopSense system prompt and bounds the history to 20 messages.
4. Groq generates an answer or requests the `web_search` function.
5. The backend sends Tavily results back to Groq when a search was requested.
6. The final Markdown response, search flag, and search queries are returned as JSON.
7. The frontend renders the response and appends it to the local conversation history.

The backend allows up to four model/tool-call rounds for one user request. Search results are condensed before being passed back to the model.

## Troubleshooting

### `Client.__init__() got an unexpected keyword argument 'proxies'`

This is a Groq SDK and `httpx` version mismatch. From `backend`, activate the virtual environment and reinstall the pinned dependencies:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install --force-reinstall -r .\requirements.txt
python -c "import groq, httpx; print(groq.__version__, httpx.__version__)"
```

The second command should print `0.11.0 0.27.2`.

### `GROQ_API_KEY is not set`

Make sure the file is named exactly `backend/.env`, that it contains a non-empty `GROQ_API_KEY`, and that you start `python .\app.py` from the `backend` directory. Do not include surrounding quotes unless they are part of the key.

### The page says `backend offline`

Check that the Flask terminal is still running and that `http://localhost:5000/api/health` opens directly. Confirm that the port in `frontend/index.html` matches the port used by Flask.

### The page says `search key missing`

The backend is running, but `TAVILY_API_KEY` is not present. Add it to `backend/.env` and restart Flask. Chat can still run without Tavily, but current product details may be unavailable or stale.

### Browser CORS or connection errors

Run the frontend with `python -m http.server` as described above, keep Flask running, and confirm that the backend's CORS configuration has not been removed. If another application is using port `5000` or `5500`, select unused ports and update the frontend URLs.

### Groq model errors

Set `GROQ_MODEL` to a model currently available to your Groq account. The default is `llama-3.3-70b-versatile`. After changing `.env`, restart Flask because configuration is read at process startup.

## Development Notes

- Flask debug mode is enabled in `app.py` for local development. Do not expose this development server directly to the public internet.
- CORS is currently open to all origins for simple local frontend development. Restrict it to the deployed frontend origin before production use.
- The backend does not persist conversations; history exists in the browser and is submitted with each request.
- The lightweight Markdown renderer lives in the frontend and supports headings, bold text, links, paragraphs, and bullet lists.
- Price and availability information should still be verified on the retailer's site before purchase.

## Production Considerations

Before deploying, use a production WSGI server, restrict CORS, store secrets in the hosting provider's secret manager, add request authentication and rate limiting, and validate maximum message/history sizes. Also review Tavily and Groq usage limits and add structured logging without logging API keys or sensitive user content.
