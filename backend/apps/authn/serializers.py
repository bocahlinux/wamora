from rest_framework import serializers

# Phase 12 (Security hardening) MUST-FIX #4 —
# docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md Section
# 3.7: previously unbounded, on the one endpoint that is both public and
# (pre-MUST-FIX-#5) unprotected by any rate limit. 150 matches Django's own
# `AbstractUser.username` field (`django.contrib.auth.models.AbstractUser`),
# the actual schema backing this project's `User` model — not an arbitrary
# number. 128 for password is a common, generous upper bound (well beyond
# any real passphrase) that blocks abuse without rejecting legitimate
# long passwords.
USERNAME_MAX_LENGTH = 150
PASSWORD_MAX_LENGTH = 128


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=USERNAME_MAX_LENGTH)
    password = serializers.CharField(max_length=PASSWORD_MAX_LENGTH, trim_whitespace=False)
