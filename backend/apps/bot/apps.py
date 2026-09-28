from django.apps import AppConfig


class BotAppConfig(AppConfig):
    # Named BotAppConfig, not BotConfig, to avoid colliding with the
    # `BotConfig` model in this same app (bot enable/fallback/root-menu
    # settings) — two different things that happen to share a name.
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.bot'
