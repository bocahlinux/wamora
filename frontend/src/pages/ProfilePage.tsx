import { useEffect, useState } from 'react';

import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { ErrorState } from '../components/ui/ErrorState';
import { Input } from '../components/ui/Input';
import { LoadingState } from '../components/ui/LoadingState';
import { PageHeader } from '../components/ui/PageHeader';
import type { ApiError } from '../lib/api';
import { getMyProfile, updateMyProfile, type MyProfile } from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import './SettingsPage.css';

// Discussed requirement — every role (Superadmin/Global Admin/Office
// Admin/Operator alike) may self-edit their own name, initial and
// password. Always the caller's OWN row — apps.offices.views.MyProfileView
// has no target `pk` at all, so there is no "which user" input here
// either.
export function ProfilePage() {
  const profileQuery = useApiQuery(() => getMyProfile(), []);

  return (
    <div>
      <PageHeader title="Profile" description="Your own name, initial and password." />
      <Card>
        {profileQuery.status === 'loading' ? (
          <LoadingState label="Loading profile…" />
        ) : profileQuery.status === 'error' ? (
          <ErrorState error={profileQuery.error} onRetry={profileQuery.refetch} />
        ) : (
          <ProfileForm profile={profileQuery.data} onSaved={profileQuery.refetch} />
        )}
      </Card>
    </div>
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
    <div className="wa-settings-form">
      <Input label="Username" value={profile.username} disabled readOnly />
      <Input label="First name" value={firstName} onChange={(e) => setFirstName(e.target.value)} disabled={busy} />
      <Input label="Last name" value={lastName} onChange={(e) => setLastName(e.target.value)} disabled={busy} />
      <Input
        label="Initial (shown to citizens when you claim a chat)"
        value={initial}
        onChange={(e) => setInitial(e.target.value)}
        disabled={busy}
        maxLength={10}
      />

      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Change password</span>
      </div>
      <Input
        label="Current password"
        type="password"
        value={currentPassword}
        onChange={(e) => setCurrentPassword(e.target.value)}
        disabled={busy}
      />
      <Input
        label="New password"
        type="password"
        value={newPassword}
        onChange={(e) => setNewPassword(e.target.value)}
        disabled={busy}
      />

      {error ? <ErrorState error={error} /> : null}
      {saved && !error ? <p className="wa-settings-form__hint">Saved.</p> : null}

      <div className="wa-settings-form__actions">
        <Button variant="primary" onClick={handleSubmit} disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}
