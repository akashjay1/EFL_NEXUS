import { createSupabaseContext } from "@supabase/server";
import { adminAction,databaseError,readBody,RequestError,uuid } from "../_shared/protocol.ts";
import { browserOrigin,failure,preflight,response } from "../_shared/http.ts";

// Actions with their own database function (newer than nexus_admin_action).
function dedicatedCall(action: string, args: Record<string, unknown>, actor: string, authSession: string) {
  switch (action) {
    case "start_screen_view":
      return { fn: "nexus_start_screen_view", params: { p_actor: actor, p_auth_session: authSession,
        p_device: args.device_id, p_reason: args.reason, p_fingerprint: args.fingerprint } };
    case "end_screen_view":
      return { fn: "nexus_end_screen_view", params: { p_actor: actor, p_auth_session: authSession, p_view: args.view_id } };
    case "screen_view_log":
      return { fn: "nexus_screen_view_log", params: { p_actor: actor, p_auth_session: authSession, p_limit: 200 } };
    case "set_device_uninstall":
      return { fn: "nexus_set_device_uninstall", params: { p_actor: actor, p_auth_session: authSession,
        p_device: args.device_id, p_uninstall: args.uninstall } };
    default:
      return null;
  }
}

Deno.serve(async(req: Request)=>{
  let origin: string | undefined;
  try {
    origin=browserOrigin(req);
    if (req.method==="OPTIONS") return preflight(origin);
    const {data:ctx,error}=await createSupabaseContext(req,{auth:"user"});
    if (error || !ctx || !ctx.jwtClaims) throw new RequestError(401,"user_session_required");
    if (ctx.jwtClaims.aal!=="aal2") throw new RequestError(403,"mfa_required");
    const {action,args}=adminAction(await readBody(req));
    const actor=uuid(ctx.jwtClaims.sub); const authSession=uuid(ctx.jwtClaims.session_id);

    const dedicated=dedicatedCall(action,args,actor,authSession);
    if (dedicated) {
      const result=await ctx.supabaseAdmin.rpc(dedicated.fn,dedicated.params).abortSignal(AbortSignal.timeout(8000));
      if (result.error) throw databaseError(result.error.code);
      return response({result:result.data},200,origin);
    }

    let code: string | undefined;
    if (action==="create_enrollment") {
      const bytes=crypto.getRandomValues(new Uint8Array(32));
      code=Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join("");
      const hash=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(code));
      args.code_hash=Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,"0")).join("");
    }
    const result=await ctx.supabaseAdmin.rpc("nexus_admin_action",{p_actor:actor,p_auth_session:authSession,p_action:action,p_args:args})
      .abortSignal(AbortSignal.timeout(8000));
    if (result.error) throw databaseError(result.error.code);
    return response({result:result.data,...(code?{enrollment_code:code,expires_in_seconds:600}:{})},200,origin);
  } catch(error) { return failure(error,origin); }
});
