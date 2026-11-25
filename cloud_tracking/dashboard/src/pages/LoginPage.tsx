import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { AlertCircle, Loader2 } from 'lucide-react';

export const LoginPage: React.FC = () => {
  const { signIn } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setErrorMessage('Please enter both email and password.');
      return;
    }
    setIsSubmitting(true);
    setErrorMessage(null);
    const result = await signIn(email, password);
    setIsSubmitting(false);
    if (!result.success) {
      setErrorMessage(result.error || 'Sign in failed. Check your email and password.');
    }
  };

  return (
    <div className="min-h-screen bg-canvas flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-xl bg-accent text-white font-display font-bold flex items-center justify-center">NX</div>
          <div>
            <p className="font-display font-bold text-ink leading-tight">EFL NEXUS</p>
            <p className="text-sm text-muted">Admin console</p>
          </div>
        </div>

        <div className="bg-surface border border-line rounded-2xl p-6 sm:p-8 shadow-[0_1px_3px_rgba(16,24,40,0.06)]">
          <h1 className="text-2xl font-bold text-ink">Sign in</h1>
          <p className="text-sm text-muted mt-1 mb-6">Administrators only. You'll confirm with your authenticator app next.</p>

          {errorMessage && (
            <div role="alert" className="mb-5 flex items-start gap-2 rounded-xl border border-[#fecdca] bg-[#fef3f2] p-3 text-sm text-[#b42318]">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
              <span>{errorMessage}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="login-email" className="block text-sm font-semibold text-ink mb-1.5">
                Email
              </label>
              <input
                id="login-email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@company.com"
                className="field"
              />
            </div>
            <div>
              <label htmlFor="login-password" className="block text-sm font-semibold text-ink mb-1.5">
                Password
              </label>
              <input
                id="login-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="field"
              />
            </div>
            <button type="submit" disabled={isSubmitting} className="btn btn-primary w-full min-h-11">
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Checking…
                </>
              ) : (
                'Sign in'
              )}
            </button>
          </form>
        </div>
        <p className="text-xs text-muted text-center mt-6">Public sign-up is disabled. Sign-in activity is audited.</p>
      </div>
    </div>
  );
};
