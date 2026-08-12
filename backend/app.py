"""
Product Recommendation Chatbot — Backend
=========================================
A Flask API that powers a real-time product recommendation chatbot.

How it works
------------
1. The user sends a message to /api/chat.
2. The message (plus conversation history) is sent to Groq's chat completion
   endpoint, along with a `web_search` tool definition.
3. If the model decides it needs current information (prices, availability,
   new releases, reviews, etc.) it calls the `web_search` tool.
4. We execute the search using the Tavily Search API and feed the results
   back to the model.
5. The model produces a final, grounded product recommendation, which is
   returned to the frontend as JSON.

Env vars required (see .env.example):
    GROQ_API_KEY    - from https://console.groq.com/keys
    TAVILY_API_KEY  - from https://app.tavily.com  (free tier available)
"""

import os
import json
import re
import traceback

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
    )

client = Groq(api_key=GROQ_API_KEY)

# The Groq model used for chat + tool calling.
# llama-3.3-70b-versatile is a strong, fast, tool-calling-capable model on Groq.
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

app = Flask(__name__)

# Which frontend origin(s) are allowed to call this API.
# Locally this defaults to "*" (any origin) for convenience. Once your
# frontend is deployed (e.g. on Netlify), set FRONTEND_ORIGINS in your
# Render environment variables to lock this down, e.g.:
#   FRONTEND_ORIGINS=https://your-site.netlify.app
# Multiple origins can be comma-separated.
_origins_env = os.environ.get("FRONTEND_ORIGINS", "*").strip()
CORS_ORIGINS = "*" if _origins_env == "*" else [o.strip() for o in _origins_env.split(",")]
CORS(app, origins=CORS_ORIGINS)

# --------------------------------------------------------------------------
# System prompt
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """You are ShopSense, an expert product recommendation assistant
built specifically for shoppers in India.

Your job is to help users find the best products for their needs by asking
clarifying questions when necessary, and by recommending real, currently
available products that can be bought in India.

Rules you must follow:
1. Whenever a recommendation depends on current information — prices,
   availability, latest models/versions, release dates, current ratings/
   reviews, or anything that could have changed recently — call the
   `web_search` tool to look it up. Do not rely on memory for facts like
   this, since your training data can be outdated.
2. Never invent prices, specs, or availability. If you are not sure after
   searching, say so plainly.
3. This app is India-only. Always:
   - Quote every price in Indian Rupees using the ₹ symbol (e.g. ₹1,499),
     never $, €, £, or any other currency. If a search result shows a
     price in another currency, convert it to an approximate ₹ figure or
     search again for an India-specific listing (site:amazon.in,
     site:flipkart.com, etc.) instead of showing the foreign price.
   - Only recommend products that are actually sold in India (e.g. via
     Amazon.in, Flipkart, Croma, Reliance Digital, Tata CLiQ, or official
     Indian retailers/brand sites). Do not recommend region-locked or
     US/EU-only products.
4. When you recommend products, format the answer clearly using Markdown:
   - A short heading or intro line.
   - Each product as a bullet with: **Name** — ₹price (if known), a 1-2
     line reason it fits the user's needs, and a Markdown link to buy or
     view it, e.g. [View on Amazon](https://...). Every product you name
     must include a link from your search results. If you cannot find a
     working product link after searching, write "(link not found)"
     instead of omitting it or making one up.
   - End with a brief follow-up question if more detail from the user would
     improve the recommendation (budget, brand preference, use case, etc.)
     — but don't ask unnecessary questions if the user has already been specific.
5. Keep responses focused and skimmable. Avoid filler and repetition.
6. Be honest about trade-offs (e.g. cheaper but lower battery life) instead
   of only listing positives.
7. If the user asks something unrelated to shopping/products, answer
   helpfully anyway, but you may gently steer back to how you can help them
   find products.
8. The user's message may include a line like:
   "[Filters — Preferred brand: X | Budget: Y | Compare prices on: A, B, C]"
   Treat this as structured constraints, not just extra text:
   - Only recommend products matching the stated brand (if given) and within
     the stated ₹ budget.
   - If specific platforms are listed under "Compare prices on", call
     `web_search` once per platform (e.g. include the platform name or a
     `site:` filter in the query, such as "boAt Airdopes 141 price
     site:amazon.in" and "boAt Airdopes 141 price site:flipkart.com") so you
     get each platform's actual current ₹ price rather than guessing.
   - Present the price comparison as a small Markdown table with columns
     Platform | Price (₹) | Link | Notes, then add one sentence clearly
     stating which platform currently has the lowest price. If a price
     can't be found on a requested platform, write "not found" for that
     row instead of guessing.
   - If no platforms were specified but the user still wants to know where
     something is cheapest, pick 2-3 well-known Indian shopping sites
     yourself (e.g. Amazon.in, Flipkart, Croma) and do the same comparison.
9. CRITICAL — never print a fake or literal tool call in your visible reply.
   Do not write text like `<function=web_search>`, `<function\\web_search>`,
   `web_search({"query": "..."})`, or any similar pseudo-code/XML describing
   a tool call. The `web_search` tool is invoked through the actual function
   calling mechanism provided to you — if you need to search, call the tool
   directly and silently; do not narrate or simulate the call as text in
   your response. Your visible reply should only ever contain normal
   Markdown written for the user.
"""

# --------------------------------------------------------------------------
# Tool definition (Groq / OpenAI-style function calling schema)
# --------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the live web for up-to-date information such as "
                "product prices, specs, availability, new releases, "
                "comparisons, or reviews. Use this whenever the answer "
                "depends on current or recent information. You may call "
                "this tool multiple times in the same turn — for example "
                "once per shopping platform (Amazon, Flipkart, Croma, "
                "Reliance Digital, etc.) — to compare actual current "
                "prices across sites for the same product."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The search query. For a general recommendation: "
                            "'best noise cancelling headphones under ₹15000 "
                            "India 2026'. For a platform-specific price check, "
                            "include the platform and, where useful, a "
                            "`site:` filter: 'boAt Airdopes 141 price "
                            "site:amazon.in' or 'boAt Airdopes 141 price "
                            "Flipkart'."
                        ),
                    }
                },
                "required": ["query"],
            },
        },
    }
]


def web_search(query: str, max_results: int = 5):
    """Run a live web search using the Tavily Search API and return a
    condensed list of results (title, url, snippet) that we can hand back
    to the model as the tool result."""

    if not TAVILY_API_KEY:
        return {
            "error": (
                "No TAVILY_API_KEY configured on the server, so live web "
                "search is unavailable right now. Answer using your best "
                "general knowledge and clearly tell the user the "
                "information may not be current."
            )
        }

    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": True,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        results = [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content"),
            }
            for r in data.get("results", [])
        ]

        return {
            "quick_answer": data.get("answer"),
            "results": results,
        }

    except requests.RequestException as e:
        return {"error": f"Web search failed: {e}"}


def run_tool_call(tool_call):
    """Dispatch a single tool call requested by the model."""
    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}

    if name == "web_search":
        return web_search(args.get("query", ""))

    return {"error": f"Unknown tool '{name}'"}


# --------------------------------------------------------------------------
# Fallback handling for "fake" tool calls
# --------------------------------------------------------------------------
# Occasionally the model writes out what it *thinks* a tool call looks like
# as plain visible text instead of using the real function-calling channel,
# e.g.:
#   <function\web_search{"query": "Sony headphones price in India"}</function>
# Rather than showing that raw junk to the user, we scan the model's text
# for a `"query": "..."` pattern, run the search ourselves, feed the result
# back in, and ask the model to answer normally. We also strip any leftover
# fake-tool-call debris from whatever text does get shown to the user.

FAKE_TOOL_TAG_RE = re.compile(
    r"<\s*/?\s*function[^>]*>|web_search\s*\(\s*\{.*?\}\s*\)",
    re.IGNORECASE | re.DOTALL,
)
FAKE_QUERY_RE = re.compile(r'"query"\s*:\s*"([^"]+)"')


def extract_fake_tool_queries(text: str):
    """Pull any 'query' values out of pseudo tool-call text the model may
    have printed instead of issuing a real tool call."""
    if not text:
        return []
    return FAKE_QUERY_RE.findall(text)


def strip_fake_tool_syntax(text: str) -> str:
    """Remove any residual pseudo tool-call tags/snippets from text before
    it's shown to the user."""
    if not text:
        return text
    return FAKE_TOOL_TAG_RE.sub("", text).strip()


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model": MODEL, "search_enabled": bool(TAVILY_API_KEY)})


@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Expected JSON body:
    {
        "message": "recommend me a laptop for video editing under ₹90000",
        "history": [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
        ]
    }
    Returns:
    {
        "reply": "...markdown formatted recommendation...",
        "used_search": true/false,
        "searches": ["query 1", "query 2"]
    }
    """
    body = request.get_json(force=True, silent=True) or {}
    user_message = (body.get("message") or "").strip()
    history = body.get("history") or []

    if not user_message:
        return jsonify({"error": "message is required"}), 400

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Keep history bounded so the request doesn't grow unbounded
    # Keep only the last few turns of history. This is intentionally lower
    # than before (was 20) because Groq's free tier enforces a per-minute
    # token cap in addition to the daily cap — sending too much history
    # plus the system prompt in one request can trip a 413 "request too
    # large" error even well within the daily quota.
    for h in history[-8:]:
        role = h.get("role")
        content = h.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    used_search = False
    searches_performed = []

    try:
        # Allow a few rounds of tool calling in case the model wants to
        # search more than once before giving a final answer (e.g. one
        # search per shopping platform when comparing prices). Kept modest
        # to keep response times reasonable — most requests finish in 1-3
        # rounds even when comparing a couple of platforms.
        for _ in range(4):
            completion = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.4,
                max_tokens=1100,
            )

            choice = completion.choices[0]
            msg = choice.message

            if msg.tool_calls:
                # Record the assistant's tool-call turn
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )

                for tc in msg.tool_calls:
                    used_search = True
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                        searches_performed.append(args.get("query", ""))
                    except json.JSONDecodeError:
                        pass

                    result = run_tool_call(tc)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result),
                        }
                    )
                # Loop again so the model can read tool results and respond
                continue

            # No real tool_calls — but check for a "fake" tool call the
            # model may have printed as plain text instead of using the
            # actual function-calling channel.
            fake_queries = extract_fake_tool_queries(msg.content or "")
            if fake_queries:
                messages.append({"role": "assistant", "content": msg.content or ""})
                for q in fake_queries:
                    used_search = True
                    searches_performed.append(q)
                    result = web_search(q)
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "SYSTEM NOTE: here are live web search "
                                f"results for the query '{q}':\n"
                                f"{json.dumps(result)}\n\n"
                                "Use this to write your final answer now, "
                                "directly in Markdown, with prices in ₹ and "
                                "a link for each product. Do not print any "
                                "tool-call syntax, XML tags, or code in "
                                "your reply — just the normal formatted "
                                "recommendation."
                            ),
                        }
                    )
                # Loop again so the model can use these results properly
                continue

            # Genuine final answer -> sanitize just in case, then return it
            return jsonify(
                {
                    "reply": strip_fake_tool_syntax(msg.content),
                    "used_search": used_search,
                    "searches": searches_performed,
                }
            )

        # Safety net if the model kept calling tools too many times
        return jsonify(
            {
                "reply": (
                    "I gathered some information but had trouble finishing "
                    "the recommendation. Could you rephrase or narrow your "
                    "request (e.g. add a budget or use case)?"
                ),
                "used_search": used_search,
                "searches": searches_performed,
            }
        )

    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        error_text = str(e)

        # Groq's daily/rate limit errors come through as a generic exception
        # with "rate_limit_exceeded" or a 429 status embedded in the message.
        # Surface these as a normal, friendly chat reply instead of raw JSON,
        # so the frontend can show it like any other assistant message.
        if "rate_limit_exceeded" in error_text or "429" in error_text:
            return jsonify(
                {
                    "reply": (
                        "I've hit today's usage limit on the AI model powering "
                        "ShopSense (this is a Groq API quota, not a problem "
                        "with your request). Please try again in a little "
                        "while — usage limits typically reset within a few "
                        "hours. If this keeps happening, the site owner may "
                        "need to switch to a different model or upgrade the "
                        "Groq plan."
                    ),
                    "used_search": False,
                    "searches": [],
                }
            )

        return jsonify({"error": error_text}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)