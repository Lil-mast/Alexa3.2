"""Per-user privacy and verbosity settings, enforced on the server.

The four privacy fields are the ones in BUILD_PLAN.md section 6. `concise_mode`
is the presentation preference from section 5; it lives here because the server,
not the client, decides whether a response carries `detail`.

Settings are per subject and in memory for the demo. Changing them goes through
the `privacy_set` tool, so every change passes the router and writes an audit
row. `personalization` is not decorative: when it is off, the concise preference
falls back to its default and the server stops keeping action details for
`tell_me_more`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

RetentionDays = Literal[0, 7, 30, 90]
MicrophoneMode = Literal["wake_word", "continuous"]


class PrivacySettings(BaseModel):
    """One user's settings. Frozen so a read cannot mutate stored state."""

    model_config = ConfigDict(frozen=True)

    # 0 keeps no history beyond the in-flight action.
    retention_days: RetentionDays = 30
    personalization: bool = True
    microphone_mode: MicrophoneMode = "wake_word"
    # When off, tools marked `external` return PRIVACY_BLOCKED.
    third_party_sharing: bool = True
    # When on, responses omit `detail` and set `detail_available` instead.
    concise_mode: bool = True


DEFAULTS = PrivacySettings()


class PrivacyStore:
    """Subject to settings map. A missing subject reads the defaults."""

    def __init__(self) -> None:
        self._settings: dict[str, PrivacySettings] = {}

    def get(self, subject: str) -> PrivacySettings:
        return self._settings.get(subject, DEFAULTS)

    def update(self, subject: str, changes: dict[str, object]) -> tuple[PrivacySettings, PrivacySettings]:
        """Apply validated changes and return (previous, current)."""
        previous = self.get(subject)
        current = previous.model_copy(update=changes)
        self._settings[subject] = current
        return previous, current

    def concise(self, subject: str) -> bool:
        """Whether `detail` should be withheld.

        With personalization off, the stored presentation preference is ignored
        and the default (on) applies. Privacy toggles themselves are always
        honoured: turning personalization off cannot silently re-enable sharing.
        """
        settings = self.get(subject)
        if not settings.personalization:
            return DEFAULTS.concise_mode
        return settings.concise_mode


__all__ = ["DEFAULTS", "MicrophoneMode", "PrivacySettings", "PrivacyStore", "RetentionDays"]
