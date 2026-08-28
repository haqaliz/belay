// `npm run server` — the console's local server. The engine binary resolves
// PATH-first with a BELAY_CONSOLE_ENGINE override; the trace dir is
// BELAY_CONSOLE_TRACE_DIR (default ~/.belay/traces); the port is
// BELAY_CONSOLE_PORT (default 8787), the bind host BELAY_CONSOLE_HOST
// (default loopback — the container sets both, 8080 + 0.0.0.0, so the
// published port is reachable via the container's interface).

import { createServer } from "./index.js";

const port = Number(process.env.BELAY_CONSOLE_PORT ?? 8787);
const host = process.env.BELAY_CONSOLE_HOST ?? "127.0.0.1";
const server = createServer({});
server.listen(port, host, () => {
  console.error(`belay console server: http://${host}:${port} (SPA served from console/dist)`);
});