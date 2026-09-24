"""Webhook payload fixtures used across the Phase 3 test suite.

INBOUND_MESSAGE_ENVELOPE is built from the exact field values reported as
a real observed WAHA payload during Phase 2.5 (session `test_session`,
`000000000000000@lid` / `62800000000@s.whatsapp.net`). The `payload.id`
value is NOT part of that reported example — no message-ID field value was
given — so it is a fixture-only placeholder; see
docs/generated/PHASE-3-WEBHOOK-INGESTION.md for why `payload.id` was
chosen as the assumed field name.

OUTBOUND_MESSAGE_ENVELOPE is entirely synthetic: no real outbound example
was available. It mirrors the inbound shape with `fromMe=True` and no
`SenderAlt`, since Phase 3 instructions explicitly warn not to assume
inbound/outbound structural symmetry — this fixture exists only to test
that this implementation's (documented, unverified) assumption of
symmetry behaves as intended, not to assert that real WAHA output looks
like this.
"""

INBOUND_MESSAGE_ENVELOPE = {
    'event': 'message',
    'session': 'test_session',
    'payload': {
        'id': 'FIXTURE-MSG-INBOUND-001',
        'from': '000000000000000@lid',
        'fromMe': False,
        'body': 'Halo pak',
        'timestamp': 1732000000,
        '_data': {
            'Info': {
                'Chat': '000000000000000@lid',
                'Sender': '000000000000000@lid',
                'SenderAlt': '62800000000@s.whatsapp.net',
                'IsGroup': False,
                'IsFromMe': False,
                'Type': 'text',
            }
        },
    },
}

# Synthetic — see module docstring.
OUTBOUND_MESSAGE_ENVELOPE = {
    'event': 'message',
    'session': 'test_session',
    'payload': {
        'id': 'FIXTURE-MSG-OUTBOUND-001',
        'from': '000000000000000@lid',
        'fromMe': True,
        'body': 'Baik, terima kasih',
        'timestamp': 1732000100,
        '_data': {
            'Info': {
                'Chat': '000000000000000@lid',
                'Sender': '000000000000000@lid',
                'IsGroup': False,
                'IsFromMe': True,
                'Type': 'text',
            }
        },
    },
}

UNSUPPORTED_EVENT_ENVELOPE = {
    'event': 'session.status',
    'session': 'test_session',
    'payload': {
        'id': 'FIXTURE-EVT-UNSUPPORTED-001',
        'status': 'WORKING',
    },
}
