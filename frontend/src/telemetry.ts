// OpenTelemetry web bootstrap.
//
// Starts a browser trace and — via FetchInstrumentation — injects a W3C
// `traceparent` header on every `/api` request, so the backend continues the
// SAME trace. That single trace ID ties the user's click to every backend
// span and LLM call.
//
// Spans are exported over OTLP/HTTP to `/otel` (same-origin, proxied to the
// collector by Vite in dev and nginx in prod) to avoid browser CORS issues.

import { context, trace, SpanStatusCode } from "@opentelemetry/api";
import { ZoneContextManager } from "@opentelemetry/context-zone";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { WebTracerProvider } from "@opentelemetry/sdk-trace-web";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";

const TRACER_NAME = "rpg-frontend";

export function setupTelemetry(): void {
  const base = import.meta.env.VITE_OTEL_EXPORTER_OTLP_ENDPOINT || "/otel";

  const provider = new WebTracerProvider({
    resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: TRACER_NAME }),
    spanProcessors: [new BatchSpanProcessor(new OTLPTraceExporter({ url: `${base}/v1/traces` }))],
  });
  provider.register({ contextManager: new ZoneContextManager() });

  registerInstrumentations({
    instrumentations: [
      new FetchInstrumentation({
        // Add the traceparent header to our backend calls so the trace continues server-side.
        propagateTraceHeaderCorsUrls: [/\/api\//],
        clearTimingResources: true,
      }),
    ],
  });
}

/**
 * Run `fn` inside a UI span named `name`. Any fetch fired within becomes a
 * child of this span, so the trace reads from the user's action down to the
 * backend and the LLM.
 */
export async function withUiSpan<T>(
  name: string,
  attributes: Record<string, string | number | boolean>,
  fn: () => Promise<T>,
): Promise<T> {
  const span = trace.getTracer(TRACER_NAME).startSpan(name, { attributes });
  try {
    return await context.with(trace.setSpan(context.active(), span), fn);
  } catch (error) {
    span.recordException(error as Error);
    span.setStatus({ code: SpanStatusCode.ERROR });
    throw error;
  } finally {
    span.end();
  }
}
