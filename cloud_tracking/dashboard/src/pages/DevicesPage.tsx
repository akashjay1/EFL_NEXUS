import React, { useMemo, useState } from 'react';
import { Device, Session, EnrollmentBundle } from '../types';
import { Card } from '../components/common/Card';
import { Modal } from '../components/common/Modal';
import { StatusBadge } from '../components/common/Badge';
import { EmptyState } from '../components/common/LoadingSpinner';
import { ScreenViewerModal } from '../components/devices/ScreenViewerModal';
import { formatDateTime, formatTimeAgo, getDisplayName } from '../lib/status';
import { callAdminAction, SUPABASE_URL, SUPABASE_ANON_KEY } from '../lib/supabase';
import { useAuth } from '../context/AuthContext';
import { Laptop, Plus, ShieldAlert, Download, AlertCircle, CheckCircle2, Loader2, Info, Monitor, Search } from 'lucide-react';

interface DevicesPageProps {
  devices: Device[];
  sessions: Session[];
  onRefresh: () => void;
  onNavigateToMfa: () => void;
}

const ErrorNote: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div role="alert" className="flex items-start gap-2 rounded-xl border border-[#fecdca] bg-[#fef3f2] p-3 text-sm text-[#b42318]">
    <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
    <span>{children}</span>
  </div>
);

const Field: React.FC<{ id: string; label: string; aside?: React.ReactNode; children: React.ReactNode }> = ({ id, label, aside, children }) => (
  <div>
    <div className="flex items-center justify-between mb-1.5">
      <label htmlFor={id} className="text-sm font-semibold text-ink">
        {label}
      </label>
      {aside}
    </div>
    {children}
  </div>
);

export const DevicesPage: React.FC<DevicesPageProps> = ({ devices, sessions, onRefresh, onNavigateToMfa }) => {
  const { aalLevel } = useAuth();
  const hasMfa = aalLevel === 'aal2';
  const [query, setQuery] = useState('');

  const [isAddOpen, setIsAddOpen] = useState(false);
  const [deviceName, setDeviceName] = useState('');
  const [installationUuid, setInstallationUuid] = useState('');
  const [accountLabel, setAccountLabel] = useState('Default Machine Account');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [createdBundle, setCreatedBundle] = useState<EnrollmentBundle | null>(null);

  const [deviceToRevoke, setDeviceToRevoke] = useState<Device | null>(null);
  const [alsoUninstall, setAlsoUninstall] = useState(false);
  const [isRevoking, setIsRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const [deviceToRestore, setDeviceToRestore] = useState<Device | null>(null);
  const [isRestoring, setIsRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  const [deviceToView, setDeviceToView] = useState<Device | null>(null);

  const sessionByDevice = useMemo(() => {
    const map = new Map<string, Session>();
    sessions.forEach((s) => {
      if (s.device_id && !s.ended_at && s.status !== 'revoked') map.set(s.device_id, s);
    });
    return map;
  }, [sessions]);

  const revokedCount = devices.filter((d) => d.revoked_at).length;
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return devices;
    return devices.filter((d) => d.device_name.toLowerCase().includes(q) || d.installation_uuid.toLowerCase().includes(q));
  }, [devices, query]);

  const openAdd = () => {
    setIsAddOpen(true);
    setCreatedBundle(null);
    setFormError(null);
    setDeviceName('');
    setInstallationUuid(crypto.randomUUID());
  };

  const handleCreateEnrollment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!deviceName || !installationUuid) {
      setFormError('Enter a device name and an installation UUID.');
      return;
    }
    if (!hasMfa) {
      setFormError('Two-factor sign-in is required before adding devices.');
      return;
    }
    setIsSubmitting(true);
    setFormError(null);
    const enrollmentId = crypto.randomUUID();
    const { data, error } = await callAdminAction<{ enrollment_code?: string; expires_in_seconds?: number }>('create_enrollment', {
      enrollment_id: enrollmentId,
      installation_uuid: installationUuid.trim().toLowerCase(),
      device_name: deviceName.trim(),
      account_label: accountLabel.trim() || 'Default Machine Account',
    });
    setIsSubmitting(false);
    if (error || !data?.enrollment_code) {
      setFormError(error || 'The enrollment could not be created.');
      return;
    }
    setCreatedBundle({
      url: SUPABASE_URL,
      key: SUPABASE_ANON_KEY,
      enrollment_id: enrollmentId,
      code: data.enrollment_code,
      installation_uuid: installationUuid.trim().toLowerCase(),
      device_name: deviceName.trim(),
      account_label: accountLabel.trim(),
      expires_at: new Date(Date.now() + (data.expires_in_seconds || 600) * 1000).toISOString(),
      expires_in_seconds: data.expires_in_seconds || 600,
    });
    onRefresh();
  };

  const downloadBundle = (bundle: EnrollmentBundle) => {
    const content = JSON.stringify(
      { url: bundle.url, key: bundle.key, enrollment_id: bundle.enrollment_id, code: bundle.code, installation_uuid: bundle.installation_uuid },
      null,
      2
    );
    const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'provisioning.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  const confirmRevoke = async () => {
    if (!deviceToRevoke) return;
    if (!hasMfa) {
      setRevokeError('Two-factor sign-in is required to revoke devices.');
      return;
    }
    setIsRevoking(true);
    setRevokeError(null);
    const { error } = await callAdminAction('revoke_device', { device_id: deviceToRevoke.id });
    let uninstallError: string | undefined;
    if (!error && alsoUninstall) {
      uninstallError = (await callAdminAction('set_device_uninstall', { device_id: deviceToRevoke.id, uninstall: true })).error;
    }
    setIsRevoking(false);
    if (error) {
      setRevokeError(error);
    } else if (uninstallError) {
      setRevokeError(`The device was revoked, but the uninstall request failed: ${uninstallError}`);
      onRefresh();
    } else {
      setDeviceToRevoke(null);
      onRefresh();
    }
  };

  const confirmRestore = async () => {
    if (!deviceToRestore) return;
    if (!hasMfa) {
      setRestoreError('Two-factor sign-in is required to restore devices.');
      return;
    }
    setIsRestoring(true);
    setRestoreError(null);
    const { error } = await callAdminAction('remove_device_uuid', { device_id: deviceToRestore.id });
    setIsRestoring(false);
    if (error) setRestoreError(error);
    else {
      setDeviceToRestore(null);
      onRefresh();
    }
  };

  return (
    <div className="space-y-6">
      <Card
        title="Registered devices"
        subtitle={`${devices.length} device${devices.length === 1 ? '' : 's'}${revokedCount ? ` · ${revokedCount} revoked` : ''}`}
        bodyClassName="p-0"
        action={
          <div className="flex flex-col sm:flex-row gap-2">
            <label className="relative block sm:w-64">
              <span className="sr-only">Search devices</span>
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true" />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search devices or UUID"
                className="field pl-9"
              />
            </label>
            <button onClick={openAdd} className="btn btn-primary">
              <Plus className="w-4 h-4" aria-hidden="true" /> Add device
            </button>
          </div>
        }
      >
        {devices.length === 0 ? (
          <EmptyState icon={<Laptop className="w-10 h-10" />} title="No devices yet">
            Choose “Add device” to create a provisioning file for a workstation.
          </EmptyState>
        ) : visible.length === 0 ? (
          <EmptyState icon={<Search className="w-10 h-10" />} title="No devices match your search" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs text-muted">
                  <th className="px-5 py-3 font-semibold">Device</th>
                  <th className="px-3 py-3 font-semibold">Status</th>
                  <th className="px-3 py-3 font-semibold">Current operator</th>
                  <th className="px-3 py-3 font-semibold">Last seen</th>
                  <th className="px-3 py-3 font-semibold">Registered</th>
                  <th className="px-5 py-3 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {visible.map((device) => {
                  const isRevoked = !!device.revoked_at;
                  const s = sessionByDevice.get(device.id);
                  const operator = s
                    ? getDisplayName(s.operator_name || s.operator_name_snapshot, s.device_name_snapshot, s.identity_source).name
                    : null;
                  return (
                    <tr key={device.id} className="hover:bg-canvas">
                      <td className="px-5 py-3.5">
                        <p className="font-semibold text-ink">{device.device_name}</p>
                        <p className="font-mono text-xs text-muted mt-0.5">{device.installation_uuid}</p>
                      </td>
                      <td className="px-3 py-3.5">
                        {isRevoked ? (
                          <StatusBadge status="revoked" />
                        ) : s ? (
                          <StatusBadge status={s.status || 'active'} />
                        ) : (
                          <span className="inline-flex rounded-full bg-canvas px-2.5 py-0.5 text-xs font-semibold text-muted">Not running</span>
                        )}
                      </td>
                      <td className="px-3 py-3.5">
                        {operator ? (
                          <>
                            <p className="text-ink">{operator}</p>
                            <p className="text-xs text-muted">{s?.active_module}</p>
                          </>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                      <td className="px-3 py-3.5 text-muted whitespace-nowrap">{s ? formatTimeAgo(s.last_seen_at) : '—'}</td>
                      <td className="px-3 py-3.5 text-muted whitespace-nowrap">{formatDateTime(device.created_at)}</td>
                      <td className="px-5 py-3.5">
                        <div className="flex justify-end gap-2">
                          {isRevoked ? (
                            <button
                              onClick={() => {
                                setRestoreError(null);
                                setDeviceToRestore(device);
                              }}
                              className="btn btn-sm"
                            >
                              Restore
                            </button>
                          ) : (
                            <>
                              <button onClick={() => setDeviceToView(device)} className="btn btn-sm">
                                <Monitor className="w-3.5 h-3.5" aria-hidden="true" /> View screen
                              </button>
                              <button
                                onClick={() => {
                                  setRevokeError(null);
                                  setAlsoUninstall(false);
                                  setDeviceToRevoke(device);
                                }}
                                className="btn btn-sm btn-danger"
                                title="Revoke device authorization"
                              >
                                Revoke
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Add device */}
      <Modal
        isOpen={isAddOpen}
        onClose={() => {
          setIsAddOpen(false);
          setCreatedBundle(null);
        }}
        title="Add a workstation"
        description="Creates a one-time provisioning file for the EFL NEXUS installer."
      >
        {!hasMfa ? (
          <div className="space-y-4">
            <div className="flex items-start gap-3 rounded-xl border border-[#fedf89] bg-[#fffaeb] p-4 text-sm text-[#93370d]">
              <ShieldAlert className="w-5 h-5 shrink-0" aria-hidden="true" />
              <div>
                <p className="font-semibold">Two-factor sign-in required</p>
                <p className="mt-1">Adding devices is a high-security action. Verify your authenticator app first.</p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setIsAddOpen(false)} className="btn">
                Close
              </button>
              <button
                onClick={() => {
                  setIsAddOpen(false);
                  onNavigateToMfa();
                }}
                className="btn btn-primary"
              >
                Set up two-factor sign-in
              </button>
            </div>
          </div>
        ) : createdBundle ? (
          <div className="space-y-4 text-sm">
            <div className="flex items-start gap-3 rounded-xl border border-[#abefc6] bg-[#ecfdf3] p-4 text-[#067647]">
              <CheckCircle2 className="w-5 h-5 shrink-0" aria-hidden="true" />
              <div>
                <p className="font-semibold">Provisioning file ready</p>
                <p className="mt-0.5">
                  Single use, valid for 10 minutes (until {new Date(createdBundle.expires_at).toLocaleTimeString()}).
                </p>
              </div>
            </div>
            <dl className="space-y-3 rounded-xl bg-canvas p-4">
              <div>
                <dt className="text-xs font-medium text-muted">Device name</dt>
                <dd className="text-ink font-medium">{createdBundle.device_name}</dd>
              </div>
              <div>
                <dt className="text-xs font-medium text-muted">Installation UUID</dt>
                <dd className="font-mono text-xs text-ink select-all">{createdBundle.installation_uuid}</dd>
              </div>
              <div>
                <dt className="text-xs font-medium text-muted">One-time enrollment code</dt>
                <dd className="font-mono text-xs text-ink-2 select-all break-all">{createdBundle.code}</dd>
              </div>
            </dl>
            <p className="flex gap-2 rounded-xl bg-accent-soft p-3 text-[13px] text-blue-300">
              <Info className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
              Put provisioning.json next to EFL_NEXUS_Setup.exe. The installer enrolls the PC during setup; operators are never asked for anything.
            </p>
            <div className="flex justify-between gap-2">
              <button onClick={() => setIsAddOpen(false)} className="btn">
                Done
              </button>
              <button onClick={() => downloadBundle(createdBundle)} className="btn btn-primary">
                <Download className="w-4 h-4" aria-hidden="true" /> Download provisioning.json
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleCreateEnrollment} className="space-y-4">
            {formError && <ErrorNote>{formError}</ErrorNote>}
            <Field id="dev-name" label="Device name">
              <input
                id="dev-name"
                required
                value={deviceName}
                onChange={(e) => setDeviceName(e.target.value)}
                placeholder="e.g. WH-OFFICE-PC-01"
                className="field"
              />
            </Field>
            <Field
              id="dev-uuid"
              label="Installation UUID"
              aside={
                <button type="button" onClick={() => setInstallationUuid(crypto.randomUUID())} className="text-sm font-semibold text-accent hover:text-accent-strong">
                  Generate new
                </button>
              }
            >
              <input
                id="dev-uuid"
                required
                value={installationUuid}
                onChange={(e) => setInstallationUuid(e.target.value)}
                placeholder="xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx"
                className="field font-mono"
              />
            </Field>
            <Field id="dev-label" label="Account label">
              <input id="dev-label" value={accountLabel} onChange={(e) => setAccountLabel(e.target.value)} className="field" />
            </Field>
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={() => setIsAddOpen(false)} className="btn">
                Cancel
              </button>
              <button type="submit" disabled={isSubmitting} className="btn btn-primary">
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Creating…
                  </>
                ) : (
                  'Create provisioning file'
                )}
              </button>
            </div>
          </form>
        )}
      </Modal>

      {/* Revoke */}
      {deviceToRevoke && (
        <Modal isOpen onClose={() => setDeviceToRevoke(null)} title={`Revoke ${deviceToRevoke.device_name}?`} maxWidth="md">
          <div className="space-y-4 text-sm">
            {revokeError && <ErrorNote>{revokeError}</ErrorNote>}
            <p className="text-ink-2 leading-relaxed">
              The device stops reporting straight away and its open session ends. EFL NEXUS stays installed and keeps working for the
              operator. You can restore the device later from this page.
            </p>
            <label className="flex items-start gap-3 rounded-xl border border-line p-3 cursor-pointer hover:bg-canvas">
              <input
                type="checkbox"
                checked={alsoUninstall}
                onChange={(e) => setAlsoUninstall(e.target.checked)}
                className="mt-0.5 w-[18px] h-[18px] accent-[#d92d20]"
              />
              <span>
                <span className="font-semibold text-ink block">Also uninstall EFL NEXUS from this PC</span>
                <span className="text-muted">
                  The app removes itself the next time it starts or checks in. This cannot be undone from here.
                </span>
              </span>
            </label>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeviceToRevoke(null)} className="btn">
                Cancel
              </button>
              <button
                onClick={confirmRevoke}
                disabled={isRevoking}
                className="btn border-[#d92d20] bg-[#d92d20] text-white hover:bg-[#b42318]"
              >
                {isRevoking && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                {alsoUninstall ? 'Revoke and uninstall' : 'Revoke device'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Restore */}
      {deviceToRestore && (
        <Modal isOpen onClose={() => setDeviceToRestore(null)} title={`Restore ${deviceToRestore.device_name}?`} maxWidth="md">
          <div className="space-y-4 text-sm">
            {restoreError && <ErrorNote>{restoreError}</ErrorNote>}
            <p className="text-ink-2 leading-relaxed">
              This removes the device record (<span className="font-mono text-xs">{deviceToRestore.installation_uuid}</span>) and any
              pending uninstall request. The next time EFL NEXUS starts on that PC it registers again automatically.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeviceToRestore(null)} className="btn">
                Cancel
              </button>
              <button onClick={confirmRestore} disabled={isRestoring} className="btn btn-primary">
                {isRestoring && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                Restore device
              </button>
            </div>
          </div>
        </Modal>
      )}

      <ScreenViewerModal device={deviceToView} isOpen={!!deviceToView} onClose={() => setDeviceToView(null)} />
    </div>
  );
};
