import React, { useState, useEffect, useRef } from 'react';
import QRCode from 'qrcode';
import { supabase } from '../lib/supabase';
import { useAuth } from '../context/AuthContext';
import { Card } from '../components/common/Card';
import { Modal } from '../components/common/Modal';
import {
  ShieldCheck,
  ShieldAlert,
  Smartphone,
  KeyRound,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Lock,
  RefreshCw,
} from 'lucide-react';

interface FactorItem {
  id: string;
  friendly_name?: string;
  factor_type: string;
  status: 'verified' | 'unverified';
  created_at: string;
}

export const SecurityMfaPage: React.FC = () => {
  const { aalLevel, refreshAuthStatus, user } = useAuth();
  const [factors, setFactors] = useState<FactorItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isEnrolling, setIsEnrolling] = useState<boolean>(false);
  const [qrCodeUrl, setQrCodeUrl] = useState<string | null>(null);
  const [factorSecret, setFactorSecret] = useState<string | null>(null);
  const [enrollFactorId, setEnrollFactorId] = useState<string | null>(null);
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [verifyCode, setVerifyCode] = useState<string>('');
  const [isVerifying, setIsVerifying] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [challengeModalFactorId, setChallengeModalFactorId] = useState<string | null>(null);
  const [challengeCode, setChallengeCode] = useState<string>('');
  const qrCanvasRef = useRef<HTMLCanvasElement | null>(null);

  // Fetch registered factors
  const loadFactors = async () => {
    setIsLoading(true);
    try {
      const { data, error } = await supabase.auth.mfa.listFactors();
      if (error) {
        setStatusMessage({ type: 'error', text: error.message });
      } else if (data) {
        const totpList = (data.totp || []) as FactorItem[];
        setFactors(totpList);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load MFA factors';
      setStatusMessage({ type: 'error', text: msg });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadFactors();
  }, []);

  // Render QR code to canvas when URI changes
  useEffect(() => {
    if (qrCodeUrl && qrCanvasRef.current) {
      QRCode.toCanvas(qrCanvasRef.current, qrCodeUrl, {
        width: 200,
        margin: 2,
        color: {
          dark: '#0f172a',
          light: '#ffffff',
        },
      });
    }
  }, [qrCodeUrl]);

  // Start new TOTP enrollment
  const handleStartEnrollment = async () => {
    setIsEnrolling(true);
    setStatusMessage(null);
    setQrCodeUrl(null);
    setFactorSecret(null);
    setVerifyCode('');

    try {
      const { data, error } = await supabase.auth.mfa.enroll({
        factorType: 'totp',
        friendlyName: `EFL NEXUS Admin (${user?.email || 'Device'})`,
      });

      if (error || !data) {
        throw new Error(error?.message || 'Failed to initialize MFA enrollment');
      }

      setEnrollFactorId(data.id);
      setQrCodeUrl(data.totp.uri);
      setFactorSecret(data.totp.secret);

      // Create challenge immediately
      const challengeRes = await supabase.auth.mfa.challenge({ factorId: data.id });
      if (challengeRes.error || !challengeRes.data) {
        throw new Error(challengeRes.error?.message || 'Failed to create MFA challenge');
      }

      setChallengeId(challengeRes.data.id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'MFA enrollment initialization failed';
      setStatusMessage({ type: 'error', text: msg });
      setIsEnrolling(false);
    }
  };

  // Verify six-digit TOTP code
  const handleVerifyEnrollment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!enrollFactorId || !challengeId || !verifyCode) return;

    setIsVerifying(true);
    setStatusMessage(null);

    try {
      const { error } = await supabase.auth.mfa.verify({
        factorId: enrollFactorId,
        challengeId: challengeId,
        code: verifyCode.trim(),
      });

      if (error) {
        throw new Error(error.message);
      }

      setStatusMessage({
        type: 'success',
        text: 'Multi-factor authentication successfully verified! Your assurance level is now AAL2.',
      });

      // Clear sensitive secrets from memory
      setQrCodeUrl(null);
      setFactorSecret(null);
      setIsEnrolling(false);
      setVerifyCode('');

      // Refresh factors & auth status
      await refreshAuthStatus();
      await loadFactors();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Invalid verification code. Please try again.';
      setStatusMessage({ type: 'error', text: msg });
    } finally {
      setIsVerifying(false);
    }
  };

  // Open verification modal for existing factor
  const handleChallengeExistingFactor = (factorId: string) => {
    setChallengeModalFactorId(factorId);
    setChallengeCode('');
    setStatusMessage(null);
  };

  const handleVerifyExistingChallenge = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!challengeModalFactorId || challengeCode.length !== 6) return;

    setIsVerifying(true);
    setStatusMessage(null);
    try {
      const challengeRes = await supabase.auth.mfa.challenge({ factorId: challengeModalFactorId });
      if (challengeRes.error || !challengeRes.data) {
        throw new Error(challengeRes.error?.message || 'Challenge failed');
      }

      const verifyRes = await supabase.auth.mfa.verify({
        factorId: challengeModalFactorId,
        challengeId: challengeRes.data.id,
        code: challengeCode.trim(),
      });

      if (verifyRes.error) {
        throw new Error(verifyRes.error.message);
      }

      setChallengeModalFactorId(null);
      setChallengeCode('');
      setStatusMessage({ type: 'success', text: 'Identity verified. You are now authenticated at AAL2.' });
      await refreshAuthStatus();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Verification failed';
      setStatusMessage({ type: 'error', text: msg });
    } finally {
      setIsVerifying(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner / Status Alert */}
      {statusMessage && (
        <div
          className={`p-4 rounded-xl text-xs flex items-start gap-3 border ${
            statusMessage.type === 'success'
              ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300'
              : 'bg-red-500/10 border-red-500/20 text-red-300'
          }`}
        >
          {statusMessage.type === 'success' ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0" />
          ) : (
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
          )}
          <span className="leading-relaxed">{statusMessage.text}</span>
        </div>
      )}

      {/* Current Assurance Level Card */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="col-span-1 md:col-span-2">
          <div className="flex items-start gap-4">
            <div
              className={`p-3 rounded-xl border ${
                aalLevel === 'aal2'
                  ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                  : 'bg-amber-500/10 border-amber-500/20 text-amber-400'
              }`}
            >
              {aalLevel === 'aal2' ? <ShieldCheck className="w-6 h-6" /> : <ShieldAlert className="w-6 h-6" />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-slate-100">
                  Current Session: {aalLevel === 'aal2' ? 'AAL2 (High Assurance)' : 'AAL1 (Password Only)'}
                </h3>
              </div>
              <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                {aalLevel === 'aal2'
                  ? 'Your session is authenticated with two-factor authentication. You have full access to privileged device management and enrollment operations.'
                  : 'Your current session has only completed single-factor authentication. Privileged operations such as generating enrollment codes and revoking devices remain blocked by the database backend until you verify an authenticator factor.'}
              </p>
            </div>
          </div>
        </Card>

        <Card>
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Registered Factors</p>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100">
              {factors.filter((f) => f.status === 'verified').length}
            </span>
            <span className="text-xs text-slate-400">active TOTP app(s)</span>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-800 flex justify-between items-center text-xs">
            <span className="text-slate-400">Backend Requirement:</span>
            <span className="font-semibold text-blue-400">AAL2 Enforced</span>
          </div>
        </Card>
      </div>

      {/* Enrollment Section */}
      {isEnrolling && (
        <Card title="Enroll Authenticator App (Google Authenticator, Microsoft Authenticator, etc.)">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-center">
            {/* Left: QR Code & Manual Secret */}
            <div className="flex flex-col items-center p-4 bg-slate-950 rounded-xl border border-slate-800 text-center">
              <p className="text-xs text-slate-400 mb-3">Scan this QR code with your authenticator mobile app:</p>
              <div className="bg-white p-3 rounded-xl shadow-md">
                <canvas ref={qrCanvasRef} />
              </div>
              {factorSecret && (
                <div className="mt-4 w-full text-left">
                  <p className="text-[11px] text-slate-500 mb-1">Or enter this setup key manually:</p>
                  <code className="block p-2 rounded bg-slate-900 border border-slate-800 text-xs font-mono text-blue-300 select-all break-all">
                    {factorSecret}
                  </code>
                </div>
              )}
            </div>

            {/* Right: Code Verification Form */}
            <div className="space-y-4">
              <div>
                <h4 className="text-sm font-semibold text-slate-200">Verify 6-Digit Code</h4>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  Enter the six-digit numerical code displayed on your phone to complete setup and activate AAL2 protection.
                </p>
              </div>

              <form onSubmit={handleVerifyEnrollment} className="space-y-4">
                <div>
                  <input
                    type="text"
                    maxLength={6}
                    pattern="[0-9]{6}"
                    required
                    autoFocus
                    value={verifyCode}
                    onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, ''))}
                    placeholder="123456"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-center text-xl font-mono tracking-widest text-slate-100 placeholder-slate-700 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                </div>

                <div className="flex items-center gap-3">
                  <button
                    type="submit"
                    disabled={isVerifying || verifyCode.length !== 6}
                    className="flex-1 bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2.5 px-4 rounded-xl text-xs transition-colors shadow-md shadow-blue-600/30 disabled:opacity-50 flex items-center justify-center gap-2"
                  >
                    {isVerifying ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Verifying Code...</span>
                      </>
                    ) : (
                      <span>Complete Enrollment & Elevate to AAL2</span>
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setIsEnrolling(false);
                      setQrCodeUrl(null);
                      setFactorSecret(null);
                    }}
                    className="px-4 py-2.5 rounded-xl border border-slate-800 text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          </div>
        </Card>
      )}

      {/* Factors List */}
      <Card
        title="Configured Authentication Factors"
        subtitle="Manage registered hardware or software authenticator factors"
        action={
          !isEnrolling && (
            <button
              onClick={handleStartEnrollment}
              className="bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2 px-3.5 rounded-lg text-xs transition-colors flex items-center gap-2 shadow-sm"
            >
              <Smartphone className="w-4 h-4" />
              <span>Add Authenticator App</span>
            </button>
          )
        }
      >
        {isLoading ? (
          <div className="py-8 flex justify-center">
            <Loader2 className="w-6 h-6 text-blue-500 animate-spin" />
          </div>
        ) : factors.length === 0 ? (
          <div className="text-center py-10 border border-dashed border-slate-800 rounded-xl">
            <KeyRound className="w-10 h-10 text-slate-600 mx-auto mb-2" />
            <h4 className="text-sm font-semibold text-slate-300">No MFA Factors Configured</h4>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-4">
              To perform administrator operations (generating device enrollment tokens, revoking devices), you must configure at least one authenticator app.
            </p>
            {!isEnrolling && (
              <button
                onClick={handleStartEnrollment}
                className="bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2 px-4 rounded-lg text-xs transition-colors"
              >
                Set up Authenticator App Now
              </button>
            )}
          </div>
        ) : (
          <div className="divide-y divide-slate-800">
            {factors.map((factor) => (
              <div key={factor.id} className="py-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-slate-800 border border-slate-700 text-blue-400">
                    <Smartphone className="w-5 h-5" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-slate-200">
                        {factor.friendly_name || 'TOTP Authenticator'}
                      </span>
                      {factor.status === 'verified' ? (
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          Verified
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                          Unverified
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      Enrolled: {new Date(factor.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>

                {aalLevel === 'aal1' && factor.status === 'verified' && (
                  <button
                    onClick={() => handleChallengeExistingFactor(factor.id)}
                    className="px-3 py-1.5 rounded-lg bg-blue-600/20 border border-blue-500/30 text-blue-300 hover:bg-blue-600 hover:text-white text-xs font-medium transition-colors flex items-center gap-1.5"
                  >
                    <Lock className="w-3.5 h-3.5" />
                    <span>Verify Code for AAL2</span>
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Recovery Guidance */}
      <Card title="Security & Recovery Policy">
        <div className="text-xs text-slate-400 space-y-2 leading-relaxed">
          <p>
            • <strong className="text-slate-200">Owner Protection:</strong> The database prevents revoking the last active owner. Arrange approved recovery access before replacing or losing your authenticator.
          </p>
          <p>
            • <strong className="text-slate-200">Secret Secrecy:</strong> TOTP seeds and setup keys are never stored in browser localStorage or transmitted to telemetry workers.
          </p>
          <p>
            • <strong className="text-slate-200">Session Expiry:</strong> Session validity follows the Supabase Auth configuration. Sign out when finished and verify MFA again when prompted.
          </p>
        </div>
      </Card>

      {/* Challenge Modal for Elevating to AAL2 */}
      {challengeModalFactorId && (
        <Modal
          isOpen={!!challengeModalFactorId}
          onClose={() => setChallengeModalFactorId(null)}
          title="Verify Authenticator Code for AAL2"
          description="Enter the current 6-digit TOTP code from your mobile authenticator app."
        >
          <form onSubmit={handleVerifyExistingChallenge} className="space-y-4 text-xs">
            <div>
              <input
                type="text"
                maxLength={6}
                pattern="[0-9]{6}"
                required
                autoFocus
                value={challengeCode}
                onChange={(e) => setChallengeCode(e.target.value.replace(/\D/g, ''))}
                placeholder="000000"
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-center text-xl font-mono tracking-widest text-slate-100 placeholder-slate-700 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setChallengeModalFactorId(null)}
                className="px-4 py-2 rounded-lg border border-slate-800 text-slate-400 text-xs hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isVerifying || challengeCode.length !== 6}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs disabled:opacity-50 flex items-center gap-2"
              >
                {isVerifying ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Verifying...</span>
                  </>
                ) : (
                  <span>Verify & Elevate to AAL2</span>
                )}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
};
