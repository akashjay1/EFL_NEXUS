import { createSupabaseContext } from "@supabase/server";
import { databaseError,deviceStatus,readBody,RequestError } from "../_shared/protocol.ts";
import { failure,response } from "../_shared/http.ts";

// Desktop asks after a rejection: am I revoked, and has an admin explicitly asked for uninstall?
Deno.serve(async(req: Request)=>{
  try {
    if (req.headers.has("origin")) throw new RequestError(403,"desktop_only");
    const args=deviceStatus(await readBody(req),req.headers.get("x-device-id"),req.headers.get("x-device-secret"));
    const {data:ctx,error}=await createSupabaseContext(req,{auth:"publishable"});
    if (error || !ctx) throw new RequestError(401,"application_key_required");
    const result=await ctx.supabaseAdmin.rpc("nexus_device_status",args).abortSignal(AbortSignal.timeout(8000));
    if (result.error) throw databaseError(result.error.code);
    return response(result.data);
  } catch(error) { return failure(error); }
});
