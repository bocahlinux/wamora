import { getMe, listOffices, type OfficeChoice } from './djangoApi';
import { useApiQuery } from './useApiQuery';

// Shared by BlastTemplatesPage/BlastHistoryPage (both need the same
// "is this caller globally-accessing, and if so what Offices can they
// filter/create against" data) — factored out so the fetch/gating logic
// lives in exactly one place rather than being copied per page.
export function useBlastAdminAccess() {
  const meQuery = useApiQuery(() => getMe(), []);
  const hasGlobalAccess = meQuery.status === 'success' && meQuery.data.has_global_access;
  const officesQuery = useApiQuery(
    () => (hasGlobalAccess ? listOffices() : Promise.resolve({ ok: true as const, data: [] })),
    [hasGlobalAccess],
  );
  const officeChoices: OfficeChoice[] = officesQuery.status === 'success' ? officesQuery.data : [];
  return { hasGlobalAccess, officeChoices, officesQuery };
}
