// No SDK, database or environment access: shared request contracts are directly testable.
export class RequestError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string) { super(code); this.status=status; this.code=code; }
}
export type ObjectValue = Record<string, unknown>;
export function object(value: unknown, allowed: string[]): ObjectValue {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).some(key => !allowed.includes(key))) throw new RequestError(400,"invalid_fields");
  return value as ObjectValue;
}
export function text(value: unknown, max: number): string {
  if (typeof value !== "string" || !value.trim() || value.length > max || /[\x00-\x1f\x7f]/.test(value))
    throw new RequestError(400,"invalid_text");
  return value.trim();
}
export function uuid(value: unknown): string {
  if (typeof value !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value))
    throw new RequestError(400,"invalid_uuid");
  return value.toLowerCase();
}
export function secret(value: unknown): string {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) throw new RequestError(401,"invalid_device_credential");
  return value;
}
function integer(value: unknown, min: number, max: number): number {
  if (!Number.isSafeInteger(value) || Number(value)<min || Number(value)>max) throw new RequestError(400,"invalid_integer");
  return Number(value);
}
function timestamp(value: unknown): string {
  if (typeof value !== "string" || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(value) || !Number.isFinite(Date.parse(value)))
    throw new RequestError(400,"invalid_timestamp");
  return value;
}
function identity(p: ObjectValue): ObjectValue {
  if (p.identity_source!=="KPI Profile" && p.identity_source!=="Device Fallback") throw new RequestError(400,"invalid_identity_source");
  return {operator_name:text(p.operator_name,120),identity_source:p.identity_source};
}
export function enrollment(value: unknown) {
  const p=object(value,["enrollment_id","code","installation_uuid","credential_id","secret"]);
  return {p_enrollment_id:uuid(p.enrollment_id),p_code:secret(p.code),p_installation_uuid:uuid(p.installation_uuid),
    p_credential_id:uuid(p.credential_id),p_secret:secret(p.secret)};
}
export function autoEnrollment(value: unknown) {
  const p=object(value,["auto_register","device_name","installation_uuid","credential_id","secret"]);
  return {p_installation_uuid:uuid(p.installation_uuid),p_device_name:text(p.device_name,120),
    p_credential_id:uuid(p.credential_id),p_secret:secret(p.secret)};
}
export function telemetry(value: unknown, credentialId: unknown, credentialSecret: unknown) {
  const p=object(value,["session_id","events","live"]);
  if (!Array.isArray(p.events) || p.events.length>50) throw new RequestError(400,"invalid_batch");
  const events=p.events.map(value=>{
    const e=object(value,["id","sequence","type","timestamp","payload"]);
    let payload: ObjectValue;
    switch(e.type) {
      case "started": {
        const q=object(e.payload,["operator_name","identity_source","device_name","module","app_version"]);
        payload={...identity(q),device_name:text(q.device_name,120),module:text(q.module,80),app_version:text(q.app_version,40)};
        if (q.identity_source==="Device Fallback" && payload.operator_name!==payload.device_name) throw new RequestError(400,"invalid_fallback");
        break;
      }
      case "operator_changed": payload=identity(object(e.payload,["operator_name","identity_source"])); break;
      case "module_changed": payload={module:text(object(e.payload,["module"]).module,80)}; break;
      case "closed": case "unclean": payload=object(e.payload,[]); break;
      case "recording_gap": payload={dropped_events:integer(object(e.payload,["dropped_events"]).dropped_events,1,2147483647)}; break;
      default: throw new RequestError(400,"invalid_event_type");
    }
    return {id:uuid(e.id),sequence:integer(e.sequence,1,Number.MAX_SAFE_INTEGER),type:e.type,timestamp:timestamp(e.timestamp),payload};
  });
  let live=null;
  if (p.live!==undefined && p.live!==null) {
    const l=object(p.live,["sequence","sent_at","idle_seconds"]);
    live={sequence:integer(l.sequence,1,Number.MAX_SAFE_INTEGER),sent_at:timestamp(l.sent_at),idle_seconds:integer(l.idle_seconds,0,604800)};
  }
  return {p_credential_id:uuid(credentialId),p_secret:secret(credentialSecret),p_session_id:uuid(p.session_id),p_events:events,p_live:live};
}
export function reconciliationJobs(value: unknown, credentialId: unknown, credentialSecret: unknown) {
  const p = object(value, ["jobs"]);
  if (!Array.isArray(p.jobs) || p.jobs.length > 50) throw new RequestError(400, "invalid_batch");
  const optionalText = (value: unknown, max: number) => value === "" ? "" : text(value, max);
  const jobs = p.jobs.map(value => {
    const j = object(value, ["job_id", "warehouse", "client", "status", "assigned_user", "observed_at"]);
    if (!["Pending", "In Progress", "Completed", "Unknown"].includes(String(j.status))) throw new RequestError(400, "invalid_status");
    return { job_id: text(j.job_id, 160), warehouse: optionalText(j.warehouse, 80),
      client: optionalText(j.client, 160), status: j.status,
      assigned_user: optionalText(j.assigned_user, 500), observed_at: timestamp(j.observed_at) };
  });
  return { p_credential_id: uuid(credentialId), p_secret: secret(credentialSecret), p_jobs: jobs };
}

export function adminAction(value: unknown) {
  const p=object(value,["action","args"]);
  let args: ObjectValue;
  switch(p.action) {
    case "reserve_admin": {
      const q=object(p.args,["email","role"]); const email=text(q.email,254).toLowerCase();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || !["owner","admin"].includes(String(q.role))) throw new RequestError(400,"invalid_invitation");
      args={email,role:q.role}; break;
    }
    case "create_enrollment": {
      const q=object(p.args,["enrollment_id","installation_uuid","device_name","account_label"]);
      args={enrollment_id:uuid(q.enrollment_id),installation_uuid:uuid(q.installation_uuid),device_name:text(q.device_name,120),account_label:text(q.account_label,120)}; break;
    }
    case "revoke_device": case "remove_device_uuid": case "unrevoke_device": case "device_credentials": {
      const q = object(p.args, ["device_id", "installation_uuid"]);
      if (q.device_id) args = { device_id: uuid(q.device_id) };
      else if (q.installation_uuid) args = { installation_uuid: uuid(q.installation_uuid) };
      else throw new RequestError(400, "invalid_fields");
      break;
    }
    case "revoke_credential": args={credential_id:uuid(object(p.args,["credential_id"]).credential_id)}; break;
    case "revoke_admin": args={user_id:uuid(object(p.args,["user_id"]).user_id)}; break;
    case "cancel_invitation": args={invitation_id:uuid(object(p.args,["invitation_id"]).invitation_id)}; break;
    case "list_admins": args=object(p.args,[]); break;
    case "start_screen_view": {
      const q=object(p.args,["device_id","reason","fingerprint"]);
      const reason=text(q.reason,200);
      if (reason.length<3) throw new RequestError(400,"invalid_reason");
      args={device_id:uuid(q.device_id),reason,fingerprint:fingerprint(q.fingerprint)}; break;
    }
    case "end_screen_view": args={view_id:uuid(object(p.args,["view_id"]).view_id)}; break;
    case "screen_view_log": args=object(p.args,[]); break;
    case "set_device_uninstall": {
      const q=object(p.args,["device_id","uninstall"]);
      if (typeof q.uninstall!=="boolean") throw new RequestError(400,"invalid_fields");
      args={device_id:uuid(q.device_id),uninstall:q.uninstall}; break;
    }
    default: throw new RequestError(400,"invalid_action");
  }
  return {action:String(p.action),args};
}
// SHA-256 DTLS fingerprint as it appears in SDP ("AB:CD:..."), normalized to upper case.
export function fingerprint(value: unknown): string {
  if (typeof value !== "string") throw new RequestError(400,"invalid_fingerprint");
  const v=value.trim().toUpperCase();
  if (!/^[0-9A-F]{2}(:[0-9A-F]{2}){31}$/.test(v)) throw new RequestError(400,"invalid_fingerprint");
  return v;
}
export function screenVerify(value: unknown, credentialId: unknown, credentialSecret: unknown) {
  const p=object(value,["view_id","fingerprint"]);
  return {p_credential_id:uuid(credentialId),p_secret:secret(credentialSecret),p_view:uuid(p.view_id),p_fingerprint:fingerprint(p.fingerprint)};
}
export function deviceStatus(value: unknown, credentialId: unknown, credentialSecret: unknown) {
  object(value,[]);
  return {p_credential_id:uuid(credentialId),p_secret:secret(credentialSecret)};
}
export async function readBody(req: Request): Promise<unknown> {
  if (req.method!=="POST") throw new RequestError(405,"method_not_allowed");
  if (req.headers.get("content-type")?.split(";")[0].trim()!=="application/json") throw new RequestError(415,"json_required");
  if (!req.body) throw new RequestError(400,"body_required");
  const reader=req.body.getReader(); const parts: Uint8Array[]=[]; let length=0;
  const deadline=setTimeout(()=>{ void reader.cancel().catch(()=>{}); },5000);
  try {
    while(true) {
      const {value,done}=await reader.read(); if (done) break;
      length+=value.byteLength;
      if (length>65536) { await reader.cancel(); throw new RequestError(413,"body_too_large"); }
      parts.push(value);
    }
    const buffer=new Uint8Array(length); let offset=0;
    for (const part of parts) { buffer.set(part,offset); offset+=part.length; }
    try { return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(buffer)); }
    catch { throw new RequestError(400,"invalid_json"); }
  } finally { clearTimeout(deadline); reader.releaseLock(); }
}
export function databaseError(code: string | undefined): RequestError {
  if (code==="P0401") return new RequestError(401,"credential_invalid");
  if (code==="42501") return new RequestError(403,"access_denied");
  if (code==="P0429") return new RequestError(429,"rate_limited");
  if (code==="23505" || code==="P0409") return new RequestError(409,"state_conflict");
  if (code?.startsWith("22") || code?.startsWith("23")) return new RequestError(400,"invalid_request");
  return new RequestError(503,"backend_unavailable");
}
