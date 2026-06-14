import { setupServer } from "msw/node";

/**
 * Shared MSW server for component/hook tests. Tests register their own
 * per-case handlers with `server.use(...)`; handlers reset between tests
 * (see `setup.ts`). The `api()` wrapper prefixes every call with `/api`,
 * so handlers match `/api/...` paths.
 */
export const server = setupServer();
