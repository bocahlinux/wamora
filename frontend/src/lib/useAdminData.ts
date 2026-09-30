import { getMe, getOffices, getRoles } from './djangoApi';
import { useApiQuery } from './useApiQuery';

// Shared by every Settings/Manage Users page (each is now its own route,
// formerly a tab of one SettingsPage.tsx) — factored out so the
// me/offices/roles fetch logic lives in exactly one place rather than
// being copied per page.
export function useAdminData() {
  const meQuery = useApiQuery(() => getMe(), []);
  const officesQuery = useApiQuery(() => getOffices(), []);
  const rolesQuery = useApiQuery(() => getRoles(), []);
  return { meQuery, officesQuery, rolesQuery };
}
