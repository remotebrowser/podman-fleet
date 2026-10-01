# Podman Fleet

**Requirements:** [Podman](https://podman.io) and [uv](https://docs.astral.sh/uv).

```bash
make
```

Then open `http://localhost:8400`.

For Dokku deployment, see the [deployment guide](deploy-dokku.md).

## API

### Launch a browser

`POST /api/v1/browsers` launches a new browser. Each browser runs in its own container, and the server generates its `browser_id` automatically.

_Example_: `curl -X POST localhost:8400/api/v1/browsers` launches a container named `chromium-P5xqk2md` and returns:

```json
{ "browser_id": "P5xqk2md", "status": "launched" }
```

### Terminate a browser

`DELETE /api/v1/browsers/{browser_id}` terminates the browser with the given `browser_id` and returns the result. If the browser does not exist, the server returns HTTP 404.

_Example_: `curl -X DELETE localhost:8400/api/v1/browsers/xyz123` terminates the container named `chromium-xyz123` and returns:

```json
{ "status": "terminated" }
```

### Query a browser

`GET /api/v1/browsers/{browser_id}` returns information about the browser with the given `browser_id`. If the browser does not exist, the server returns HTTP 404.

_Example_: `curl localhost:8400/api/v1/browsers/xyz123` returns:

```json
{ "last_activity_timestamp": 1772069081 }
```

### List all browsers

`GET /api/v1/browsers` returns a JSON array with the IDs of all running browsers.

_Example_: `curl localhost:8400/api/v1/browsers` returns:

```json
["xyz123", "abc234"]
```

### Connect to a browser over CDP

`GET /api/v1/browsers/{browser_id}/cdp` upgrades the connection to a WebSocket and tunnels a [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/) (CDP) session to the specified browser. If the browser's debugger URL cannot be resolved after several retries, the server closes the WebSocket with close code 4502.

_Example (Playwright with Node.js)_:

```js
import { chromium } from 'playwright';

(async () => {
  const target = 'ws://localhost:8400/api/v1/browsers/B5xqk2md/cdp';
  const browser = await chromium.connectOverCDP(target);
  const [context] = browser.contexts();
  const page = await context.newPage();
  await page.goto('https://www.google.com');
  await browser.close();
})();
```
