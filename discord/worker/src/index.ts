import { type Env, type ExecutionContextLike, createApp } from "./app.ts";
import type { Content } from "./content.ts";
import generated from "./content.generated.json" with { type: "json" };

const app = createApp(generated as unknown as Content, {
  doFetch: (input, init) => fetch(input, init),
  now: () => Date.now(),
});

export default {
  fetch(request: Request, env: Env, ctx: ExecutionContextLike): Promise<Response> {
    return app.fetch(request, env, ctx);
  },
};
