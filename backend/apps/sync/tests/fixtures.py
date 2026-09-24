"""REST history fixtures for Phase 4 reconciliation tests.

Built from the real evidence captured against the deployed WAHA instance
(session `test_session`, chat `000000000000000@lid`) via
`GET /api/test_session/chats/000000000000000%40lid/messages?limit=10` —
see docs/generated/PHASE-3-LIVE-VERIFICATION.md and
docs/generated/PHASE-4-RECONCILIATION.md for the full evidence chain.
Structurally identical to a webhook `payload` object (confirmed: same
field names), which is why `apps.webhooks.parsing.parse_message` is
reused as-is rather than duplicated.
"""

REST_INBOUND_MESSAGE_1 = {
    'id': 'false_000000000000000@lid_2A19C241A2D8A0CD88E6',
    'from': '000000000000000@lid',
    'fromMe': False,
    'body': 'Halo pak',
    'timestamp': 1790142598,
    '_data': {
        'Info': {
            'ID': '2A19C241A2D8A0CD88E6',
            'Chat': '000000000000000@lid',
            'Sender': '000000000000000@lid',
            'SenderAlt': '62800000000@s.whatsapp.net',
            'IsFromMe': False,
            'IsGroup': False,
            'Type': 'text',
        }
    },
}

REST_INBOUND_MESSAGE_2 = {
    'id': 'false_000000000000000@lid_2A2D894F686E8CB5370F',
    'from': '000000000000000@lid',
    'fromMe': False,
    'body': 'Apa kabar',
    'timestamp': 1790142650,
    '_data': {
        'Info': {
            'ID': '2A2D894F686E8CB5370F',
            'Chat': '000000000000000@lid',
            'Sender': '000000000000000@lid',
            'SenderAlt': '62800000000@s.whatsapp.net',
            'IsFromMe': False,
            'IsGroup': False,
            'Type': 'text',
        }
    },
}

REST_OUTBOUND_MESSAGE_SAME_CHAT = {
    'id': 'true_000000000000000@lid_A588F68CE9231B4DDE50896B0A4EC41A',
    'from': '000000000000000@lid',
    'fromMe': True,
    'body': 'Tes',
    'timestamp': 1790142700,
    '_data': {
        'Info': {
            'ID': 'A588F68CE9231B4DDE50896B0A4EC41A',
            'Chat': '000000000000000@lid',
            'Sender': '62800000001@s.whatsapp.net',
            'SenderAlt': '',
            'IsFromMe': True,
            'IsGroup': False,
            'Type': 'text',
        }
    },
}

# A different chat identity for the same underlying phone number — the
# confirmed identity-fragmentation example (docs/12-WAHA-REFERENCE.md,
# "known limitation"). Used only to prove reconciliation does not attempt
# to merge it with the @lid chat above.
REST_OUTBOUND_MESSAGE_OTHER_CHAT = {
    'id': 'true_62800000000@c.us_3EB0B21AB186B9D17204AA',
    'from': '62800000000@c.us',
    'fromMe': True,
    'body': 'Hi there!',
    'timestamp': 1790142800,
    '_data': {
        'Info': {
            'ID': '3EB0B21AB186B9D17204AA',
            'Chat': '62800000000@s.whatsapp.net',
            'Sender': '62800000001:1@s.whatsapp.net',
            'IsFromMe': True,
            'IsGroup': False,
            'Type': 'text',
        }
    },
}


def make_message(seq, chat_id='000000000000000@lid', base_timestamp=1790142000, fromMe=False):
    """Synthetic message for pagination tests — ordering/count matters,
    not real content. `seq` controls recency: higher seq = newer message
    (larger timestamp), matching the confirmed newest-first ordering."""
    return {
        'id': f'synthetic-msg-{seq:04d}',
        'from': chat_id,
        'fromMe': fromMe,
        'body': f'message {seq}',
        'timestamp': base_timestamp + seq,
        '_data': {
            'Info': {
                'ID': f'INFOID{seq:04d}',
                'Chat': chat_id,
                'Sender': chat_id,
                'SenderAlt': '62800000000@s.whatsapp.net',
                'IsFromMe': fromMe,
                'IsGroup': False,
                'Type': 'text',
            }
        },
    }
