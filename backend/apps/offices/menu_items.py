"""Discussed requirement — Menu Access (Settings). The canonical list of
sidebar leaf-menu keys a `Role.visible_menu_items` entry may reference —
kept deliberately identical to `frontend/src/lib/menuItems.ts`'s own
`MENU_ITEMS` list (same "two implementations, deliberately kept in sync"
precedent this project already established for
`apps.blast.templating.extract_variable_names`/
`frontend/src/lib/blastTemplateVariables.ts`).

Only LEAF destinations are listed — a submenu group (Blast, Manage Users,
Settings) has no key of its own; the frontend derives a group's own
visibility from whether any of its children are visible, so hiding every
child of a group has the same effect as hiding the group, with no
separate toggle that could fall out of sync with its children.
"""

MENU_ITEM_KEYS = [
    'dashboard',
    'whatsapp',
    'inbox',
    'sessions',
    'blast.campaigns',
    'blast.templates',
    'blast.history',
    'manage_users.users',
    'manage_users.roles',
    'reports',
    'settings.offices',
    'settings.inbox_config',
    'settings.bot_config',
    'settings.blast_api',
    'settings.menu_access',
]
