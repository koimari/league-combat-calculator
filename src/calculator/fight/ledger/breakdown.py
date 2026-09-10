"""Which breakdown keys belong to the auto-attack stream."""


def _is_auto_stream_key(key: str) -> bool:
    """Whether a breakdown key belongs to the auto-attack damage stream.
    The stream and champion riders on it (Corki's true-damage instance) share
    the ``auto_attacks`` prefix; on-hit, spellblade and Fiendhunter rows ride
    the swings too."""
    return (
        key.startswith(("auto_attacks", "on_hit_", "spellblade_"))
        or key == "fiendhunter_true_damage"
    )
