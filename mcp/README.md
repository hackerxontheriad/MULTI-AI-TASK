# OmniRoute MCP connector

OmniRoute includes its own MCP server; it is not started by the MAD X Python server. Deploy/run OmniRoute separately, connect your authorized providers there, and create an endpoint/API key in its dashboard. The MAD X OpenAI-compatible connector uses `OMNIROUTE_BASE_URL`, `OMNIROUTE_API_KEY`, and `OMNIROUTE_MODELS`.

Upstream docs: https://github.com/cheaper-inference/OmniRoute and https://github.com/cheaper-inference/OmniRoute/wiki/MCP-Server

The current upstream guide requires Node.js `>=22.22.2 <23` or `>=24 <27` for the npm installation route. The build environment used for this ZIP has Node `22.16.0`, below that requirement; only the integration configuration and documentation are included, not a running OmniRoute server.

## Local MCP client example

`omniroute.mcp.example.json` shows the client-side stdio configuration. It intentionally contains no token. Configure secrets in your local MCP client's environment or secret manager; don't commit them. For MCP, a typical local command is `omniroute --mcp`. The cloud/hosted instance must be configured with the MCP transport that the client supports.

## Environment for MAD X HTTP route

```dotenv
OMNIROUTE_BASE_URL=https://your-own-omniroute-host.example/v1
OMNIROUTE_API_KEY=your-created-endpoint-key
OMNIROUTE_MODELS=if/kimi-k2-thinking
```

The example model ID is an example from upstream docs, not a guarantee that your connected route currently offers that model. Use the model prefix returned by your own OmniRoute endpoint. The `/api/connectors/status?probe=true` check requests `/models`; it doesn't generate a chat completion.

**Token limitation:** MAD X cannot extend or mint OmniRoute account tokens by itself. Create/rotate endpoint keys in the OmniRoute instance you control, then configure the key server-side. Token validity and quotas remain upstream responsibilities.
