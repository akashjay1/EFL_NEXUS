import React, { useState, useEffect, useCallback } from 'react';
import { AdminProfile, AdminRole } from '../types';
import { Card } from '../components/common/Card';
import { Modal } from '../components/common/Modal';
import { callAdminAction } from '../lib/supabase';
import { useAuth } from '../context/AuthContext';
import {
  ShieldCheck,
  UserPlus,
  ShieldAlert,
  Trash2,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Mail,
  Lock,
} from 'lucide-react';

interface Invitation {
  id: string;
  email: string;
  role: AdminRole;
  slot: number;
  created_at: string;
}

export const AdminManagementPage: React.FC = () => {
  const { adminProfile, aalLevel } = useAuth();
  const isOwner = adminProfile?.role === 'owner';

  const [admins, setAdmins] = useState<AdminProfile[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Reserve Modal State
  const [isReserveModalOpen, setIsReserveModalOpen] = useState(false);
  const [reserveEmail, setReserveEmail] = useState('');
  const [reserveRole, setReserveRole] = useState<AdminRole>('admin');
  const [isReserving, setIsReserving] = useState(false);
  const [reserveError, setReserveError] = useState<string | null>(null);
  const [reserveSuccess, setReserveSuccess] = useState<string | null>(null);

  // Revoke state
  const [adminToRevoke, setAdminToRevoke] = useState<AdminProfile | null>(null);
  const [isRevoking, setIsRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const fetchAdmins = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const { data, error } = await callAdminAction<{
        result: {
          admins?: AdminProfile[];
          invitations?: Invitation[];
        };
      }>('list_admins', {});

      if (error) {
        setErrorMessage(error);
      } else if (data?.result) {
        setAdmins(data.result.admins || []);
        setInvitations(data.result.invitations || []);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch administrator list';
      setErrorMessage(msg);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAdmins();
  }, [fetchAdmins]);

  const handleReserveAdmin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reserveEmail) return;

    if (aalLevel !== 'aal2') {
      setReserveError('AAL2 MFA authentication required to invite administrators.');
      return;
    }

    setIsReserving(true);
    setReserveError(null);
    setReserveSuccess(null);

    const { error } = await callAdminAction('reserve_admin', {
      email: reserveEmail.trim().toLowerCase(),
      role: reserveRole,
    });

    setIsReserving(false);

    if (error) {
      setReserveError(error);
    } else {
      setReserveSuccess(`Slot reserved successfully for ${reserveEmail}.`);
      setReserveEmail('');
      fetchAdmins();
      setTimeout(() => {
        setIsReserveModalOpen(false);
        setReserveSuccess(null);
      }, 1500);
    }
  };

  const handleConfirmRevoke = async () => {
    if (!adminToRevoke) return;

    if (aalLevel !== 'aal2') {
      setRevokeError('AAL2 MFA authentication required.');
      return;
    }

    setIsRevoking(true);
    setRevokeError(null);

    const { error } = await callAdminAction('revoke_admin', {
      user_id: adminToRevoke.user_id,
    });

    setIsRevoking(false);

    if (error) {
      setRevokeError(error);
    } else {
      setAdminToRevoke(null);
      fetchAdmins();
    }
  };

  const totalUsedSlots = admins.length + invitations.length;

  return (
    <div className="space-y-6">
      {/* Header Card */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold text-slate-100 uppercase tracking-wide">
              Administrator Access & Slots
            </h2>
            <span className="text-xs font-semibold px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
              {totalUsedSlots} / 5 Slots Assigned
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            The database backend enforces a hard limit of 5 administrator slots with atomic serialization.
          </p>
        </div>

        {isOwner && (
          <button
            onClick={() => {
              setIsReserveModalOpen(true);
              setReserveError(null);
              setReserveSuccess(null);
            }}
            disabled={totalUsedSlots >= 5}
            className="bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2 px-3.5 rounded-lg text-xs transition-colors flex items-center gap-2 shadow-sm disabled:opacity-40"
          >
            <UserPlus className="w-4 h-4" />
            <span>Reserve Administrator Slot</span>
          </button>
        )}
      </div>

      {errorMessage && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-amber-400 flex-shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Active Admins List */}
      <Card title="Active Administrators">
        {isLoading ? (
          <div className="py-12 flex justify-center">
            <Loader2 className="w-6 h-6 text-blue-500 animate-spin" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 uppercase text-[10px] tracking-wider">
                  <th className="py-3.5 pr-4 font-semibold">Slot</th>
                  <th className="py-3.5 pr-4 font-semibold">Administrator</th>
                  <th className="py-3.5 pr-4 font-semibold">Role</th>
                  <th className="py-3.5 pr-4 font-semibold">Created Date</th>
                  <th className="py-3.5 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {admins.map((adm) => (
                  <tr key={adm.user_id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3.5 pr-4 font-mono font-bold text-slate-300">
                      Slot #{adm.slot}
                    </td>
                    <td className="py-3.5 pr-4">
                      <div className="font-semibold text-slate-200">
                        {adm.email || adm.user_id}
                      </div>
                      <div className="text-[10px] font-mono text-slate-500">
                        UUID: {adm.user_id}
                      </div>
                    </td>
                    <td className="py-3.5 pr-4">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold ${
                          adm.role === 'owner'
                            ? 'bg-purple-500/10 text-purple-300 border border-purple-500/20'
                            : 'bg-blue-500/10 text-blue-300 border border-blue-500/20'
                        }`}
                      >
                        {adm.role}
                      </span>
                    </td>
                    <td className="py-3.5 pr-4 text-slate-400">
                      {new Date(adm.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-3.5 text-right">
                      {isOwner && adm.user_id !== adminProfile?.user_id && (
                        <button
                          onClick={() => setAdminToRevoke(adm)}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-slate-800 transition-colors"
                          title="Revoke Administrator"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Pending Invitations / Reservations */}
      {invitations.length > 0 && (
        <Card title="Pending Slot Reservations" subtitle="Invited addresses awaiting user account creation">
          <div className="divide-y divide-slate-800">
            {invitations.map((inv) => (
              <div key={inv.id} className="py-3 flex items-center justify-between text-xs">
                <div className="flex items-center gap-3">
                  <Mail className="w-4 h-4 text-slate-400" />
                  <div>
                    <span className="font-medium text-slate-200">{inv.email}</span>
                    <span className="text-[11px] text-slate-500 block">
                      Slot #{inv.slot} • Role: {inv.role}
                    </span>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  Reserved (Pending)
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Reserve Administrator Modal */}
      <Modal
        isOpen={isReserveModalOpen}
        onClose={() => setIsReserveModalOpen(false)}
        title="Reserve Administrator Slot"
        description="Authorize a new email address to claim an administrative slot."
      >
        <form onSubmit={handleReserveAdmin} className="space-y-4 text-xs">
          {reserveError && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-300 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
              <span>{reserveError}</span>
            </div>
          )}

          {reserveSuccess && (
            <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
              <span>{reserveSuccess}</span>
            </div>
          )}

          <div>
            <label className="block font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
              Administrator Email
            </label>
            <input
              type="email"
              required
              value={reserveEmail}
              onChange={(e) => setReserveEmail(e.target.value)}
              placeholder="operator.admin@company.com"
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
              Role
            </label>
            <select
              value={reserveRole}
              onChange={(e) => setReserveRole(e.target.value as AdminRole)}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-xs text-slate-100 focus:outline-none focus:border-blue-500"
            >
              <option value="admin">Administrator (Can manage devices & enrollments)</option>
              <option value="owner">Owner (Full system control & admin management)</option>
            </select>
          </div>

          <div className="flex justify-end gap-3 pt-3">
            <button
              type="button"
              onClick={() => setIsReserveModalOpen(false)}
              className="px-4 py-2 rounded-lg border border-slate-800 text-slate-400 text-xs hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isReserving}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs flex items-center gap-2 shadow-sm disabled:opacity-50"
            >
              {isReserving ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Reserving Slot...</span>
                </>
              ) : (
                <span>Confirm Reservation</span>
              )}
            </button>
          </div>
        </form>
      </Modal>

      {/* Revoke Admin Modal */}
      {adminToRevoke && (
        <Modal
          isOpen={!!adminToRevoke}
          onClose={() => setAdminToRevoke(null)}
          title="Revoke Administrator Access"
          description={`Revoking ${adminToRevoke.email || adminToRevoke.user_id}`}
        >
          <div className="space-y-4 text-xs">
            {revokeError && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-300 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
                <span>{revokeError}</span>
              </div>
            )}

            <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 leading-relaxed">
              Are you sure you want to revoke this administrator? They will immediately lose all access to the monitoring dashboard, and their administrative slot will become free for reallocation.
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => setAdminToRevoke(null)}
                className="px-4 py-2 rounded-lg border border-slate-800 text-slate-400 text-xs hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmRevoke}
                disabled={isRevoking}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white font-semibold text-xs flex items-center gap-2 disabled:opacity-50"
              >
                {isRevoking ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                <span>Confirm Revoke Access</span>
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
