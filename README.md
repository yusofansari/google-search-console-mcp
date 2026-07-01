# Google Search Console MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that connects **Google Search Console** to [Claude](https://claude.ai) and any MCP-compatible AI client — **43 tools** for search analytics, indexing, and technical SEO, powered by natural language.

Ask *"which queries lost clicks last month?"* or *"find keyword cannibalization on my blog"* and get answers straight from your GSC data — no dashboards, no exports.

## Features

- **43 tools** over the `webmasters.readonly` scope
- Search analytics — clicks, impressions, CTR, average position by query / page / country / device
- URL inspection & indexing status
- Sitemap management
- Keyword **cannibalization detection** and content-opportunity discovery
- Per-user OAuth 2.0 — every user connects their own Google account
- Stateless: your Search Console data is never stored

## Quick Start

### Use as a Claude Connector (no install)

1. Open [claude.ai/settings/connectors](https://claude.ai/settings/connectors)
2. Click **Add custom connector**
3. Enter: `https://saveyourclicks.com/mcp/gsc`
4. Claude handles Google sign-in automatically via OAuth 2.0.

### Self-host

```bash
git clone https://github.com/YOUR_USERNAME/google-search-console-mcp.git
cd google-search-console-mcp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in your Google OAuth credentials
python gsc/run.py
```

You'll need a Google Cloud OAuth client with the **Search Console API** enabled. Production systemd + nginx examples are in [`deploy/`](deploy/).

## How it works

The server uses [FastMCP](https://github.com/modelcontextprotocol) with a custom OAuth 2.0 provider so each user authenticates with their own Google account. Tokens are the only thing persisted (short-lived access + refresh); Search Console responses are streamed straight through to the model and never stored. OAuth, token storage, and the ASGI wrapper live in [`shared/`](shared/).

## Privacy & Security

- **No data storage** — Google API data is never retained
- **Token-only storage** — only OAuth tokens are kept (24h access, 90d refresh)
- **Per-user isolation** — complete separation between users
- **HTTPS only** and compliant with the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)

## License

[MIT](LICENSE)

## Author

**Yusof Ansari-Renani** — [saveyourclicks.com](https://saveyourclicks.com)

- [LinkedIn](https://www.linkedin.com/in/yusof-ansari-renani-325319222/)
- [Telegram](https://t.me/yusofansari)

---

*Keywords: Google Search Console MCP, GSC MCP server, Claude MCP, Model Context Protocol, SEO automation, Search Console API, AI SEO tools.*
