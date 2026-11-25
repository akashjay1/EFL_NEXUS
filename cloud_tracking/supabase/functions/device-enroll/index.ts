import { createSupabaseContext } from "@supabase/server";
import { databaseError, enrollment, autoEnrollment, readBody, RequestError } from "../_shared/protocol.ts";
import { failure, response } from "../_shared/http.ts";

Deno.serve(async(req: Request)=>{
  try {
    if (req.headers.has("origin")) throw new RequestError(403,"desktop_only");
    const body = await readBody(req);
    const {data:ctx,error}=await createSupabaseContext(req,{auth:"publishable"});
    if (error || !ctx) throw new RequestError(401,"application_key_required");

    if (body && typeof body === "object" && (body as Record<string, unknown>).auto_register) {
      const args = autoEnrollment(body);
      const result = await ctx.supabaseAdmin.rpc("nexus_auto_register_device", args).abortSignal(AbortSignal.timeout(8000));
      if (result.error) throw databaseError(result.error.code);
      return response(result.data);
    } else {
      const args = enrollment(body);
      const result = await ctx.supabaseAdmin.rpc("nexus_claim_enrollment", args).abortSignal(AbortSignal.timeout(8000));
      if (result.error) throw databaseError(result.error.code);
      return response(result.data);
    }
  } catch(error) { return failure(error); }
});
