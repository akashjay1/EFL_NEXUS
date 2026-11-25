import { RequestError } from "./protocol.ts";
export function response(value: unknown,status=200,origin?: string) {
  return Response.json(value,{status,headers:{"Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
    ...(origin?{"Access-Control-Allow-Origin":origin,"Vary":"Origin"}:{}),...(status===429?{"Retry-After":"60"}:{})}});
}
export function failure(error: unknown,origin?: string) {
  // Never log/return request bodies, credentials, Supabase errors or stack traces.
  const e=error instanceof RequestError?error:new RequestError(503,"backend_unavailable");
  return response({error:e.code},e.status,origin);
}
export function browserOrigin(req: Request): string | undefined {
  const origin=req.headers.get("origin");
  if (!origin) return undefined;
  const allowed=(Deno.env.get("NEXUS_ADMIN_ORIGINS")??"").split(",").map(x=>x.trim()).filter(Boolean);
  if (!allowed.includes(origin)) throw new RequestError(403,"origin_not_allowed");
  return origin;
}
export function preflight(origin: string | undefined) {
  return new Response(null,{status:204,headers:{"Access-Control-Allow-Origin":origin??"null","Vary":"Origin",
    "Access-Control-Allow-Methods":"POST, OPTIONS","Access-Control-Allow-Headers":"authorization, apikey, content-type, x-client-info",
    "Access-Control-Max-Age":"600","Cache-Control":"no-store"}});
}
