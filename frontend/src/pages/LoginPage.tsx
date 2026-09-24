import { useState, type FormEvent } from 'react';
import { Navigate } from 'react-router-dom';

import { Logo } from '../components/brand/Logo';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { useAuth } from '../lib/AuthContext';
import type { ApiError } from '../lib/api';
import { describeError } from '../lib/api';
import './LoginPage.css';

// NOTE — flagged per this task's Stop Conditions (Section 25): the
// supplied WAMORA design package (wamora-design-assets/) contains no
// login/authentication screen reference anywhere in its five reference
// boards or its written spec (WAMORA-FRONTEND-DESIGN-SPEC.md has no
// "Login"/"Authentication" section). This page is built using only the
// already-approved design tokens/components (Card-less centered panel,
// Input, Button, Logo) rather than copying an approved mockup, because
// none exists. It has NOT been visually approved and should be reviewed
// against the design system before being considered final — see
// docs/generated/PHASE-7-IMPLEMENTATION-REPORT.md.
export function LoginPage() {
  const { isAuthenticated, login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await login(username, password);
    setSubmitting(false);
    if (!result.ok) {
      setError(result.error);
    }
  }

  return (
    <div className="wa-login">
      <form className="wa-login__panel" onSubmit={handleSubmit}>
        <div className="wa-login__brand">
          <Logo variant="horizontal" height={36} onDark={false} />
        </div>
        <div>
          <h1 className="wa-login__title">Sign in</h1>
          <p className="wa-login__subtitle">Access the WAMORA operations dashboard.</p>
        </div>

        <Input
          label="Username"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          disabled={submitting}
        />
        <Input
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          disabled={submitting}
        />

        {error ? (
          <p className="wa-login__error" role="alert">
            {describeError(error)}
          </p>
        ) : null}

        <Button type="submit" variant="primary" disabled={submitting} style={{ width: '100%' }}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </div>
  );
}
