// `npm run server` — the console's local server. The engine binary resolves
// PATH-first with a BELAY_CONSOLE_ENGINE override; the trace dir is
// BELAY_CONSOLE_TRACE_DIR (default ~/.belay/traces); the port is
// BELAY_CONSOLE_PORT (default 8787).

import { createServer } from "./index";

const port = Number(process.env.BELAY_CONSOLE_PORT ?? 8787);
const server = createServer({});
server.listen(port, "127.0.0.1", () => {
  console.error(`belay console server: http://127.0.0.1:${port} (SPA served from console/dist)`);
});