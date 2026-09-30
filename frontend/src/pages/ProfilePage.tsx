import { useEffect, useState } from 'react';
import { KeyRound, ShieldCheck, User } from 'lucide-react';

import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { ErrorState } from '../components/ui/ErrorState';
import { Input } from '../components/ui/Input';
import { LoadingState } from '../components/ui/LoadingState';
import { PageHeader } from '../components/ui/PageHeader';
import { StatusBadge } from '../components/ui/StatusBadge';
import type { ApiError } from '../lib/api';
import { getMe, getMyProfile, updateMyProfile, type Me, type MyProfile } from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import './ProfilePage.css';

// Discussed requirement — every role (Superadmin/Global Admin/Office
// Admin/Operator alike) may self-edit their own name, initial and
// password. Always the caller's OWN row — apps.offices.views.MyProfileView
// has no target `pk` at all, so there is no "which user" input here
// either.
export function ProfilePage() {
  const profileQuery = useApiQuery(() => getMyProfile(), []);
  // Read-only context (role/office/availability) for the hero card only —
  // `getMe()` is the same call every other page already makes; nothing
  // here is ever written back through it.
  const meQuery = useApiQuery(() => getMe(), []);

  function refetchBoth() {
    profileQuery.refetch();
    meQuery.refetch();
  }

  return (
    <div className="wa-profile-page">
      <PageHeader title="Profile" description="Your own name, initial and password." />
      {profileQuery.status === 'loading' ? (
        <LoadingState label="Loading profile…" />
      ) : profileQuery.status === 'error' ? (
        <ErrorState error={profileQuery.error} onRetry={profileQuery.refetch} />
      ) : (
        <div className="wa-profile-page__body">
          <ProfileHero profile={profileQuery.data} me={meQuery.status === 'success' ? meQuery.data : null} />
          <ProfileForm profile={profileQuery.data} onSaved={refetchBoth} />
        </div>
      )}
    </div>
  );
}

function initialsFor(profile: MyProfile): string {
  const first = profile.first_name.trim().charAt(0);
  const last = profile.last_name.trim().charAt(0);
  const combined = `${first}${last}`.toUpperCase();
  return combined || profile.username.slice(0, 2).toUpperCase();
}

function ProfileHero({ profile, me }: { profile: MyProfile; me: Me | null }) {
  const fullName = `${profile.first_name} ${profile.last_name}`.trim() || profile.username;
  return (
    <Card className="wa-profile-hero">
      <div className="wa-profile-hero__avatar" aria-hidden="true">
        {initialsFor(profile)}
      </div>
      <div className="wa-profile-hero__info">
        <p className="wa-profile-hero__name">{fullName}</p>
        <p className="wa-profile-hero__username">@{profile.username}</p>
        {me ? (
          <div className="wa-profile-hero__badges">
            {me.has_global_access ? (
              <Badge tone="info">{me.is_superuser ? 'Superadmin' : 'Global Admin'}</Badge>
            ) : me.role ? (
              <Badge tone="neutral">{me.role.name}</Badge>
            ) : null}
            {me.office ? <Badge tone="neutral">{me.office.name}</Badge> : null}
            {me.role?.is_operator ? (
              <StatusBadge status={me.is_available ? 'healthy' : 'offline'} label={me.is_available ? 'Available' : 'Unavailable'} />
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function ProfileForm({ profile, onSaved }: { profile: MyProfile; onSaved: () => void }) {
  const [firstName, setFirstName] = useState(profile.first_name);
  const [lastName, setLastName] = useState(profile.last_name);
  const [initial, setInitial] = useState(profile.initial);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setFirstName(profile.first_name);
    setLastName(profile.last_name);
    setInitial(profile.initial);
  }, [profile]);

  async function handleSubmit() {
    if (busy) return;
    if (newPassword && !currentPassword) {
      setError({ kind: 'validation', message: 'Enter your current password to set a new one.' });
      return;
    }
    setBusy(true);
    setError(null);
    setSaved(false);
    const result = await updateMyProfile({
      first_name: firstName.trim(),
      last_name: lastName.trim(),
      ...(initial.trim() ? { initial: initial.trim() } : {}),
      ...(newPassword ? { current_password: currentPassword, new_password: newPassword } : {}),
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setCurrentPassword('');
    setNewPassword('');
    setSaved(true);
    onSaved();
  }

  return (
    <>
      <Card className="wa-profile-section">
        <div className="wa-profile-section__header">
          <User size={18} strokeWidth={1.75} aria-hidden="true" />
          <div>
            <h2 className="wa-profile-section__title">Personal information</h2>
            <p className="wa-profile-section__description">Your name and the initial shown to citizens in chat.</p>
          </div>
        </div>
        <div className="wa-profile-section__fields">
          <Input label="Username" value={profile.username} disabled readOnly />
          <div className="wa-profile-section__row">
            <Input label="First name" value={firstName} onChange={(e) => setFirstName(e.target.value)} disabled={busy} />
            <Input label="Last name" value={lastName} onChange={(e) => setLastName(e.target.value)} disabled={busy} />
          </div>
          <Input
            label="Initial (shown to citizens when you claim a chat)"
            value={initial}
            onChange={(e) => setInitial(e.target.value)}
            disabled={busy}
            maxLength={10}
          />
        </div>
      </Card>

      <Card className="wa-profile-section">
        <div className="wa-profile-section__header">
          <KeyRound size={18} strokeWidth={1.75} aria-hidden="true" />
          <div>
            <h2 className="wa-profile-section__title">Change password</h2>
            <p className="wa-profile-section__description">Leave both fields blank to keep your current password.</p>
          </div>
        </div>
        <div className="wa-profile-section__fields">
          <div className="wa-profile-section__row">
            <Input
              label="Current password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              disabled={busy}
            />
            <Input
              label="New password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              disabled={busy}
            />
          </div>
        </div>
      </Card>

      {error ? <ErrorState error={error} /> : null}
      {saved && !error ? (
        <p className="wa-profile-page__saved" role="status">
          <ShieldCheck size={16} strokeWidth={1.75} aria-hidden="true" />
          Saved.
        </p>
      ) : null}

      <div className="wa-profile-page__actions">
        <Button variant="primary" onClick={handleSubmit} disabled={busy}>
          {busy ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </>
  );
}
