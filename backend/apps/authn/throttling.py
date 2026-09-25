"""Login-specific rate throttle — Phase 12 (Security hardening) MUST-FIX #5
(docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md Section
3.5). `LoginView` is public (`authentication_classes = []`), so every
caller is always anonymous from DRF's point of view — this subclasses
`AnonRateThrottle` (keyed by client IP, the same mechanism it already
uses) rather than `UserRateThrottle`, since there is no authenticated user
to key on at this endpoint by construction.

Deliberately IP-keyed, not username-keyed: the `username` field in a login
POST body is attacker-controlled and unverified at throttle time (that is
the whole point of the credential check this endpoint performs) — keying
by a claimed username would let an attacker trivially bypass the limit by
rotating usernames on each attempt. IP is the correct anchor for a
credential-guessing control.

Set as `LoginView.throttle_classes = [LoginRateThrottle]`, which REPLACES
(not adds to) the project-wide `DEFAULT_THROTTLE_CLASSES`
(AnonRateThrottle/UserRateThrottle, settings.py REST_FRAMEWORK) for this
one view — the login-specific 'login' scope rate (5/minute, stricter than
the general 'anon' 60/minute) is the only limit that should apply here;
stacking the general anon throttle on top would add no additional
protection (the stricter one always binds first) and would only make the
two limits' interaction harder to reason about.
"""

from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    scope = 'login'
