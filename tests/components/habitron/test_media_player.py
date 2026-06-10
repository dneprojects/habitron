"""Tests for the Habitron media_player platform."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.media_player import (
    HbtnMediaPlayer,
    QueueItem,
    async_setup_entry,
)

from .conftest import class_attr


async def test_media_player_setup(setup_integration: MockConfigEntry) -> None:
    """The media_player platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_key() -> None:
    """HbtnMediaPlayer uses the icon-translation key."""
    assert class_attr(HbtnMediaPlayer, "_attr_translation_key") == "habitron_speaker"


# ---------- Helpers ----------


def _make_touch_module(uid: str = "MOD-T") -> MagicMock:
    """A SmartController-Touch-like mock for media-player wiring."""
    from custom_components.habitron.module import SmartController  # noqa: PLC0415

    mod = MagicMock(spec=SmartController)
    mod.uid = uid
    mod.name = "Touch 1"
    mod.mod_type = "Smart Controller Touch"
    mod.raddr = 5
    return mod


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.async_send_json_message = AsyncMock()
    provider.register_media_player = MagicMock()
    return provider


def _make_player(hass: object = None) -> HbtnMediaPlayer:
    """Construct a HbtnMediaPlayer with all dependencies stubbed.

    The HA Entity base class exposes ``self.hass`` separately from the
    constructor-supplied ``self._hass``; only the former is what the
    helper methods read. We assign it directly so tests can drive the
    entity outside an actual HA setup.
    """
    mod = _make_touch_module()
    provider = _make_provider()
    fake_hass = hass if hass is not None else MagicMock()
    player = HbtnMediaPlayer(mod, provider, fake_hass)
    player.hass = fake_hass
    # ``entity_id`` is None by default outside HA; some helpers log it.
    player.entity_id = "media_player.test"
    return player


def test_queue_item_holds_passed_values() -> None:
    """QueueItem is a tiny data class — it stores everything it gets."""
    item = QueueItem("id", "type", "url", {"k": "v"})
    assert item.media_id == "id"
    assert item.media_type == "type"
    assert item.media_url == "url"
    assert item.metadata == {"k": "v"}


def test_player_init_seeds_stream_name_and_state() -> None:
    """The constructor wires up unique id, device info and the initial state."""
    player = _make_player()
    assert player.unique_id == "Mod_MOD-T_mediaplayer"
    assert player._stream_name == "touch_1_5"
    assert player.stream_name == "touch_1_5"
    assert ("habitron", "MOD-T") in player._attr_device_info["identifiers"]


def test_supported_features_includes_skip_in_multi_mode() -> None:
    """``supported_features`` adds NEXT/PREVIOUS_TRACK when in multi-track mode."""
    from homeassistant.components.media_player import (  # noqa: PLC0415
        MediaPlayerEntityFeature,
    )

    player = _make_player()
    base = int(player.supported_features)
    player._track_mode = "multi"
    multi = int(player.supported_features)
    assert multi & int(MediaPlayerEntityFeature.NEXT_TRACK)
    assert multi & int(MediaPlayerEntityFeature.PREVIOUS_TRACK)
    assert multi != base


async def test_async_added_to_hass_restores_state() -> None:
    """async_added_to_hass restores volume / mute from the last state."""
    player = _make_player()
    last_state = MagicMock()
    last_state.attributes = {"volume_level": 0.7, "is_volume_muted": True}
    player.async_get_last_state = AsyncMock(return_value=last_state)
    with patch(
        "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await player.async_added_to_hass()
    assert player._attr_volume_level == 0.7
    assert player._attr_is_volume_muted is True
    player._provider.register_media_player.assert_called_with(player)


async def test_async_added_to_hass_no_last_state_keeps_defaults() -> None:
    """Without a previous state, defaults are kept."""
    player = _make_player()
    player.async_get_last_state = AsyncMock(return_value=None)
    with patch(
        "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await player.async_added_to_hass()
    assert player._attr_volume_level == 0.3  # default


async def test_get_token_seeds_internal_auth_token() -> None:
    """get_token populates the internal auth token from hass.auth."""
    player = _make_player()
    owner = MagicMock()
    player.hass.auth.async_get_owner = AsyncMock(return_value=owner)
    refresh = MagicMock()
    player.hass.auth.async_create_refresh_token = AsyncMock(return_value=refresh)
    player.hass.auth.async_create_access_token = MagicMock(return_value="TOK")
    await player.get_token()
    assert player._internal_auth_token == "TOK"


async def test_get_token_logs_error_when_owner_missing() -> None:
    """When no owner is found, ``get_token`` logs an error and returns."""
    player = _make_player()
    player.hass.auth.async_get_owner = AsyncMock(return_value=None)
    await player.get_token()


async def test_async_resolve_tts_url_returns_path_on_success() -> None:
    """A 200 response returns the resolved TTS path."""
    player = _make_player()
    player._internal_auth_token = "tok"
    session = MagicMock()
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value={"path": "/api/tts/foo"})
    session.post.return_value.__aenter__ = AsyncMock(return_value=response)
    session.post.return_value.__aexit__ = AsyncMock()
    out = await player._async_resolve_tts_url(session, "http://x", {})
    assert out == "/api/tts/foo"


async def test_async_resolve_tts_url_returns_status_on_error() -> None:
    """A non-200 response returns the status code."""
    player = _make_player()
    player._internal_auth_token = "tok"
    session = MagicMock()
    response = MagicMock()
    response.status = 401
    session.post.return_value.__aenter__ = AsyncMock(return_value=response)
    session.post.return_value.__aexit__ = AsyncMock()
    out = await player._async_resolve_tts_url(session, "http://x", {})
    assert out == 401


# ---------- async_play_media + queue management ----------


def _enable_play_media(player: HbtnMediaPlayer) -> None:
    """Patch the helpers the play_media flow calls into."""
    player._process_media_id = AsyncMock(return_value="http://media/track.mp3")
    player._extract_metadata = AsyncMock(return_value={"title": "T", "artist": "A"})
    player._send_item_to_client = AsyncMock()
    player.async_write_ha_state = MagicMock()


async def test_async_play_media_replace_mode_clears_queue_and_plays() -> None:
    """REPLACE clears the queue and triggers immediate playback."""
    from homeassistant.components.media_player import (
        MediaPlayerEnqueue,  # noqa: PLC0415
    )

    player = _make_player()
    _enable_play_media(player)
    await player.async_play_media(
        "music", "media-source://library/song", enqueue=MediaPlayerEnqueue.REPLACE
    )
    player._send_item_to_client.assert_awaited()
    assert player._track_mode == "single"


async def test_async_play_media_replace_mode_moves_current_to_history() -> None:
    """REPLACE with a current item pushes it to history before playback."""
    from homeassistant.components.media_player import (  # noqa: PLC0415
        MediaPlayerEnqueue,
        MediaPlayerState,
    )

    player = _make_player()
    _enable_play_media(player)
    player._attr_state = MediaPlayerState.PLAYING
    existing = QueueItem("old", "music", "u-old", {})
    player._current_item = existing
    await player.async_play_media(
        "music", "media-source://library/song", enqueue=MediaPlayerEnqueue.REPLACE
    )
    # The previous current was moved to history and the new item is now playing.
    assert any(it is existing for it in player._history)
    assert player._current_item is not existing
    player._send_item_to_client.assert_awaited()


async def test_async_play_media_add_mode_appends_to_queue() -> None:
    """ADD appends to the queue without forcing playback."""
    from homeassistant.components.media_player import (  # noqa: PLC0415
        MediaPlayerEnqueue,
        MediaPlayerState,
    )

    player = _make_player()
    _enable_play_media(player)
    player._attr_state = MediaPlayerState.PLAYING
    await player.async_play_media(
        "music", "media-source://library/song", enqueue=MediaPlayerEnqueue.ADD
    )
    assert len(player._queue) == 1
    assert player._track_mode == "multi"


async def test_async_play_media_next_mode_inserts_at_top() -> None:
    """NEXT inserts the item at position 0 of the queue."""
    from homeassistant.components.media_player import (  # noqa: PLC0415
        MediaPlayerEnqueue,
        MediaPlayerState,
    )

    player = _make_player()
    _enable_play_media(player)
    player._attr_state = MediaPlayerState.PLAYING
    player._queue.append(QueueItem("A", "music", "u-A", {}))
    await player.async_play_media(
        "music", "media-source://library/song", enqueue=MediaPlayerEnqueue.NEXT
    )
    assert player._queue[0].media_id != "A"


async def test_async_play_media_play_mode_inserts_and_forces_play() -> None:
    """PLAY inserts at top + always plays now."""
    from homeassistant.components.media_player import (  # noqa: PLC0415
        MediaPlayerEnqueue,
        MediaPlayerState,
    )

    player = _make_player()
    _enable_play_media(player)
    player._attr_state = MediaPlayerState.PLAYING
    player._current_item = QueueItem("old", "music", "u-old", {})
    await player.async_play_media(
        "music", "media-source://library/song", enqueue=MediaPlayerEnqueue.PLAY
    )
    # Old current moved to history; new item now playing
    assert any(it.media_id == "old" for it in player._history)
    player._send_item_to_client.assert_awaited()


async def test_async_play_media_unresolvable_id_logs_and_returns() -> None:
    """A blank resolved URL aborts the play_media flow."""
    from homeassistant.components.media_player import (
        MediaPlayerEnqueue,  # noqa: PLC0415
    )

    player = _make_player()
    player._process_media_id = AsyncMock(return_value="")
    player._extract_metadata = AsyncMock()
    player.async_write_ha_state = MagicMock()
    await player.async_play_media("music", "bad-id", enqueue=MediaPlayerEnqueue.REPLACE)
    # No queue items were added
    assert player._queue == []


async def test_async_play_media_resolver_exception_propagates() -> None:
    """An exception during resolution propagates so HA can report it."""
    from homeassistant.components.media_player import (
        MediaPlayerEnqueue,  # noqa: PLC0415
    )

    player = _make_player()
    player._process_media_id = AsyncMock(side_effect=RuntimeError("boom"))
    player.async_write_ha_state = MagicMock()
    with pytest.raises(RuntimeError, match="boom"):
        await player.async_play_media(
            "music", "bad-id", enqueue=MediaPlayerEnqueue.REPLACE
        )


# ---------- Internal queue flow + metadata polling ----------


async def test_play_next_item_drains_queue() -> None:
    """``_play_next_item_in_queue`` pops + sends the next item."""
    player = _make_player()
    player._send_item_to_client = AsyncMock()
    item = QueueItem("id", "music", "url", {"title": "X"})
    player._queue.append(item)
    await player._play_next_item_in_queue()
    assert player._current_item is item
    player._send_item_to_client.assert_awaited()


async def test_play_next_item_empty_queue_sets_idle() -> None:
    """Empty queue → state goes IDLE and current_item is cleared."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player._current_item = QueueItem("id", "music", "url", {})
    player.async_write_ha_state = MagicMock()
    await player._play_next_item_in_queue()
    assert player._attr_state == MediaPlayerState.IDLE
    assert player._current_item is None
    # Previous current moved to history
    assert len(player._history) == 1


async def test_send_item_to_client_writes_payload() -> None:
    """_send_item_to_client emits the habitron/play_media WS payload."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player.async_write_ha_state = MagicMock()
    item = QueueItem(
        "id",
        "music",
        "url",
        {"title": "T", "artist": "A", "entity_picture": "pic"},
    )
    await player._send_item_to_client(item)
    player._provider.async_send_json_message.assert_awaited()
    assert player._attr_state == MediaPlayerState.BUFFERING
    assert player._attr_media_title == "T"


async def test_poll_ma_metadata_stops_when_not_playing() -> None:
    """When state is not PLAYING the polling helper unregisters and returns."""
    player = _make_player()
    player._stop_proxy_polling = AsyncMock()
    await player._poll_ma_metadata(None)
    player._stop_proxy_polling.assert_awaited()


async def test_poll_ma_metadata_skips_when_no_proxy() -> None:
    """A missing MA proxy short-circuits the polling helper."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player._attr_state = MediaPlayerState.PLAYING
    player._get_mass_proxy_entity_id = MagicMock(return_value=None)
    await player._poll_ma_metadata(None)
    player._provider.async_send_json_message.assert_not_awaited()


async def test_poll_ma_metadata_skips_when_state_missing() -> None:
    """A proxy whose hass.states.get returns None short-circuits."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player._attr_state = MediaPlayerState.PLAYING
    player._get_mass_proxy_entity_id = MagicMock(return_value="media_player.ma")
    player.hass.states.get = MagicMock(return_value=None)
    await player._poll_ma_metadata(None)


async def test_poll_ma_metadata_sends_update_payload() -> None:
    """When a proxy state is present the metadata payload is sent."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player._attr_state = MediaPlayerState.PLAYING
    player._get_mass_proxy_entity_id = MagicMock(return_value="media_player.ma")
    state = MagicMock()
    state.attributes = {
        "media_title": "Song",
        "media_artist": "Band",
        "entity_picture": "art",
    }
    player.hass.states.get = MagicMock(return_value=state)
    await player._poll_ma_metadata(None)
    player._provider.async_send_json_message.assert_awaited()


async def test_stop_proxy_polling_removes_listener() -> None:
    """_stop_proxy_polling deregisters the registered listener if any."""
    player = _make_player()
    remove = MagicMock()
    player._poll_remove = remove
    await player._stop_proxy_polling()
    remove.assert_called()
    assert player._poll_remove is None


async def test_stop_proxy_polling_noop_when_not_polling() -> None:
    """When no listener is registered, the helper is a no-op."""
    player = _make_player()
    player._poll_remove = None
    await player._stop_proxy_polling()  # no raise


# ---------- _extract_metadata branches ----------


async def test_extract_metadata_from_kwargs() -> None:
    """Metadata from kwargs is preferred over browse-media lookups."""
    player = _make_player()
    kwargs = {"extra": {"metadata": {"title": "T", "artist": "A", "imageUrl": "pic"}}}
    out = await player._extract_metadata("http://x", kwargs)
    assert out == {"title": "T", "artist": "A", "entity_picture": "pic"}


async def test_extract_metadata_browse_media_radio_title() -> None:
    """A media-source URI without artist runs the browse-media fallback."""
    player = _make_player()
    browse = MagicMock()
    browse.title = "Radio Browser"
    browse.thumbnail = None
    with patch(
        "custom_components.habitron.media_player.media_source.async_browse_media",
        new=AsyncMock(return_value=browse),
    ):
        out = await player._extract_metadata("media-source://radio/x", {})
    assert out["title"] == "Internet Radio"
    assert out["artist"] == "Home Assistant"


async def test_extract_metadata_browse_media_dash_split() -> None:
    """A `Artist - Title` browse title is split into the two fields."""
    player = _make_player()
    browse = MagicMock()
    browse.title = "Some Artist - Some Song"
    browse.thumbnail = "art-url"
    with patch(
        "custom_components.habitron.media_player.media_source.async_browse_media",
        new=AsyncMock(return_value=browse),
    ):
        out = await player._extract_metadata("media-source://library/x", {})
    assert out["artist"] == "Some Artist"
    assert out["title"] == "Some Song"
    assert out["entity_picture"] == "art-url"


async def test_extract_metadata_browse_media_slash_split() -> None:
    """A `Title / Artist` browse title is split into the two fields."""
    player = _make_player()
    browse = MagicMock()
    browse.title = "Song/Band"
    browse.thumbnail = None
    with patch(
        "custom_components.habitron.media_player.media_source.async_browse_media",
        new=AsyncMock(return_value=browse),
    ):
        out = await player._extract_metadata("media-source://library/x", {})
    assert out["title"] == "Song"
    assert out["artist"] == "Band"


async def test_extract_metadata_browse_exception_logged_and_continued() -> None:
    """A browse-media exception is caught and the call still returns metadata."""
    player = _make_player()
    with patch(
        "custom_components.habitron.media_player.media_source.async_browse_media",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        out = await player._extract_metadata("media-source://library/x", {})
    assert out["title"] == "Unknown Title"


async def test_extract_metadata_relative_artwork_becomes_absolute() -> None:
    """A leading-slash artwork URL is prefixed with ``hass.config.internal_url``."""
    player = _make_player()
    player.hass.config.internal_url = "http://ha.local"
    kwargs = {
        "extra": {"metadata": {"title": "T", "artist": "A", "imageUrl": "/art.png"}}
    }
    out = await player._extract_metadata("http://x", kwargs)
    assert out["entity_picture"] == "http://ha.local/art.png"


# ---------- async_browse_media + _process_media_id ----------


async def test_async_browse_media_filters_audio() -> None:
    """async_browse_media filters down to audio content types."""
    player = _make_player()
    browse = MagicMock()
    with patch(
        "custom_components.habitron.media_player.media_source.async_browse_media",
        new=AsyncMock(return_value=browse),
    ):
        out = await player.async_browse_media("music", "media-source://x")
    assert out is browse


async def test_process_media_id_resolves_media_source() -> None:
    """A media-source URI is resolved + absolutised."""
    player = _make_player()
    player.hass.config.internal_url = "http://ha.local"
    resolved = MagicMock()
    resolved.url = "/api/tts_proxy/abc"
    with patch(
        "custom_components.habitron.media_player.media_source.async_resolve_media",
        new=AsyncMock(return_value=resolved),
    ):
        out = await player._process_media_id("media-source://tts/abc")
    assert out == "http://ha.local/api/tts_proxy/abc"


async def test_process_media_id_absolute_resolved_url_passes_through() -> None:
    """An already-absolute resolved URL is returned as-is."""
    player = _make_player()
    resolved = MagicMock()
    resolved.url = "http://radio/stream.mp3"
    with patch(
        "custom_components.habitron.media_player.media_source.async_resolve_media",
        new=AsyncMock(return_value=resolved),
    ):
        out = await player._process_media_id("media-source://radio/x")
    assert out == "http://radio/stream.mp3"


async def test_process_media_id_resolution_failure_returns_empty() -> None:
    """An exception during resolution returns an empty string."""
    player = _make_player()
    with patch(
        "custom_components.habitron.media_player.media_source.async_resolve_media",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        out = await player._process_media_id("media-source://x")
    assert out == ""


async def test_process_media_id_passthrough_for_direct_url() -> None:
    """A direct http URL is returned unchanged."""
    player = _make_player()
    out = await player._process_media_id("http://radio/stream.mp3")
    assert out == "http://radio/stream.mp3"


async def test_process_media_id_proxy_method() -> None:
    """The public ``process_media_id`` is a thin proxy to the private one."""
    player = _make_player()
    player._process_media_id = AsyncMock(return_value="X")
    out = await player.process_media_id("any-id")
    assert out == "X"


# ---------- Transport commands ----------


async def test_async_media_play_sends_play_message() -> None:
    """async_media_play emits habitron/play + flips state to PLAYING."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player.async_write_ha_state = MagicMock()
    await player.async_media_play()
    player._provider.async_send_json_message.assert_awaited()
    assert player._attr_state == MediaPlayerState.PLAYING


async def test_async_media_pause_sends_pause_message() -> None:
    """async_media_pause emits habitron/pause + flips state to PAUSED."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player.async_write_ha_state = MagicMock()
    await player.async_media_pause()
    assert player._attr_state == MediaPlayerState.PAUSED


async def test_async_media_stop_clears_queue_and_goes_idle() -> None:
    """async_media_stop clears state and goes IDLE (unless force_client_stop)."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player.async_write_ha_state = MagicMock()
    player._queue.append(QueueItem("a", "music", "u", {}))
    await player.async_media_stop()
    assert player._queue == []
    assert player._attr_state == MediaPlayerState.IDLE


async def test_async_media_stop_force_keeps_state() -> None:
    """``force_client_stop=True`` keeps the current state unchanged."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player._attr_state = MediaPlayerState.PLAYING
    await player.async_media_stop(force_client_stop=True)
    assert player._attr_state == MediaPlayerState.PLAYING


async def test_async_clear_playlist_resets_queue() -> None:
    """async_clear_playlist resets queue + history without stopping playback."""
    player = _make_player()
    player._queue.append(QueueItem("a", "music", "u", {}))
    player._history.append(QueueItem("b", "music", "u", {}))
    player.async_write_ha_state = MagicMock()
    await player.async_clear_playlist()
    assert player._queue == []
    assert player._history == []


def test_get_mass_proxy_entity_id_finds_proxy() -> None:
    """_get_mass_proxy_entity_id returns the matching MA proxy."""
    player = _make_player()
    other = MagicMock()
    other.attributes = {"mass_player_type": "player", "active_queue": player.entity_id}
    other.entity_id = "media_player.ma"
    player.hass.states.async_all = MagicMock(return_value=[other])
    out = player._get_mass_proxy_entity_id()
    assert out == "media_player.ma"


def test_get_mass_proxy_entity_id_no_match_returns_none() -> None:
    """Without a matching proxy player, the helper returns None."""
    player = _make_player()
    player.hass.states.async_all = MagicMock(return_value=[])
    assert player._get_mass_proxy_entity_id() is None


async def test_async_media_next_track_single_mode_is_noop() -> None:
    """In single-track mode, next_track is silently ignored."""
    player = _make_player()
    player._track_mode = "single"
    player._play_next_item_in_queue = AsyncMock()
    await player.async_media_next_track()
    player._play_next_item_in_queue.assert_not_called()


async def test_async_media_next_track_plays_from_internal_queue() -> None:
    """Multi-track mode + non-empty queue plays the next item."""
    player = _make_player()
    player._track_mode = "multi"
    player._queue.append(QueueItem("a", "music", "u", {}))
    player._play_next_item_in_queue = AsyncMock()
    await player.async_media_next_track()
    player._play_next_item_in_queue.assert_awaited()


async def test_async_media_next_track_delegates_to_ma_when_empty() -> None:
    """Multi-track mode + empty queue delegates to MA via services.async_call."""
    player = _make_player()
    player._track_mode = "multi"
    player._get_mass_proxy_entity_id = MagicMock(return_value="media_player.ma")
    player.hass.services.async_call = AsyncMock()
    await player.async_media_next_track()
    player.hass.services.async_call.assert_awaited()


async def test_async_media_next_track_falls_back_to_idle_when_no_proxy() -> None:
    """Multi-track + empty queue + no proxy falls back to ``_play_next_item_in_queue``."""
    player = _make_player()
    player._track_mode = "multi"
    player._get_mass_proxy_entity_id = MagicMock(return_value=None)
    player._play_next_item_in_queue = AsyncMock()
    await player.async_media_next_track()
    player._play_next_item_in_queue.assert_awaited()


async def test_async_media_previous_track_single_mode_is_noop() -> None:
    """Single-track mode ignores previous_track."""
    player = _make_player()
    player._track_mode = "single"
    player._send_item_to_client = AsyncMock()
    await player.async_media_previous_track()
    player._send_item_to_client.assert_not_called()


async def test_async_media_previous_track_plays_from_history() -> None:
    """Multi-track + non-empty history pops the last item back as current."""
    player = _make_player()
    player._track_mode = "multi"
    prev = QueueItem("prev", "music", "u", {})
    player._history.append(prev)
    player._send_item_to_client = AsyncMock()
    await player.async_media_previous_track()
    assert player._current_item is prev
    player._send_item_to_client.assert_awaited()


async def test_async_media_previous_track_inserts_current_back_into_queue() -> None:
    """Multi-track + history pushes any current item back to the queue first."""
    player = _make_player()
    player._track_mode = "multi"
    player._history.append(QueueItem("prev", "music", "u", {}))
    cur = QueueItem("cur", "music", "u", {})
    player._current_item = cur
    player._send_item_to_client = AsyncMock()
    await player.async_media_previous_track()
    assert player._queue[0] is cur


async def test_async_media_previous_track_delegates_to_ma_when_history_empty() -> None:
    """Multi-track + empty history delegates to MA."""
    player = _make_player()
    player._track_mode = "multi"
    player._get_mass_proxy_entity_id = MagicMock(return_value="media_player.ma")
    player.hass.services.async_call = AsyncMock()
    await player.async_media_previous_track()
    player.hass.services.async_call.assert_awaited()


async def test_async_media_previous_track_no_proxy_returns_silently() -> None:
    """Multi-track + empty history + no proxy logs and returns."""
    player = _make_player()
    player._track_mode = "multi"
    player._get_mass_proxy_entity_id = MagicMock(return_value=None)
    await player.async_media_previous_track()


# ---------- Volume / Power ----------


async def test_async_set_volume_level_sends_payload_and_caches() -> None:
    """set_volume sends habitron/set_volume + caches value."""
    player = _make_player()
    player.async_write_ha_state = MagicMock()
    await player.async_set_volume_level(0.6)
    assert player._attr_volume_level == 0.6
    player._provider.async_send_json_message.assert_awaited()


async def test_async_mute_volume_records_pre_mute_and_zeroes() -> None:
    """Mute saves pre-mute and lowers the volume."""
    player = _make_player()
    player._attr_volume_level = 0.5
    player.async_write_ha_state = MagicMock()
    await player.async_mute_volume(True)
    assert player._pre_mute_volume == 0.5
    assert player._attr_is_volume_muted is True


async def test_async_mute_volume_unmute_restores_pre_mute() -> None:
    """Unmute restores the previously stored level."""
    player = _make_player()
    player._pre_mute_volume = 0.4
    player.async_write_ha_state = MagicMock()
    await player.async_mute_volume(False)
    assert player._attr_volume_level == 0.4
    assert player._attr_is_volume_muted is False


async def test_async_turn_on_changes_state_from_off_to_idle() -> None:
    """Turn on switches state to IDLE when previously OFF."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player.async_write_ha_state = MagicMock()
    await player.async_turn_on()
    assert player._attr_state == MediaPlayerState.IDLE


async def test_async_turn_on_keeps_state_when_already_on() -> None:
    """When the player is already on (e.g., PLAYING), turn_on keeps the state."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player._attr_state = MediaPlayerState.PLAYING
    player.async_write_ha_state = MagicMock()
    await player.async_turn_on()
    assert player._attr_state == MediaPlayerState.PLAYING


async def test_async_turn_off_clears_queue_and_state() -> None:
    """Turn off clears queue/history and switches state to OFF."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player._queue.append(QueueItem("a", "music", "u", {}))
    player.async_write_ha_state = MagicMock()
    await player.async_turn_off()
    assert player._queue == []
    assert player._attr_state == MediaPlayerState.OFF


# ---------- Image fetching ----------


async def test_async_fetch_image_returns_bytes() -> None:
    """A 200 response returns the image bytes + content-type tuple."""
    player = _make_player()
    response = MagicMock()
    response.status = 200
    response.read = AsyncMock(return_value=b"img")
    response.content_type = "image/png"
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock()
    with patch(
        "custom_components.habitron.media_player.async_get_clientsession",
        return_value=session,
    ):
        out = await player._async_fetch_image("http://art.png")
    assert out == (b"img", "image/png")


async def test_async_fetch_image_non_200_returns_none() -> None:
    """A non-200 response returns (None, None)."""
    player = _make_player()
    response = MagicMock()
    response.status = 404
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock()
    with patch(
        "custom_components.habitron.media_player.async_get_clientsession",
        return_value=session,
    ):
        out = await player._async_fetch_image("http://art.png")
    assert out == (None, None)


async def test_async_fetch_image_client_error_returns_none() -> None:
    """A ClientError during fetch returns (None, None)."""
    from aiohttp import ClientError  # noqa: PLC0415

    player = _make_player()
    session = MagicMock()
    session.get.side_effect = ClientError("boom")
    with patch(
        "custom_components.habitron.media_player.async_get_clientsession",
        return_value=session,
    ):
        out = await player._async_fetch_image("http://art.png")
    assert out == (None, None)


async def test_async_get_browse_image_returns_none_without_url() -> None:
    """Without a media_image_url, async_get_browse_image returns (None, None)."""
    player = _make_player()
    player._attr_media_image_url = None
    out = await player.async_get_browse_image("music", "id")
    assert out == (None, None)


async def test_async_get_browse_image_delegates_to_fetch_image() -> None:
    """A populated image_url delegates to ``_async_fetch_image``."""
    player = _make_player()
    player._attr_media_image_url = "http://art.png"
    player._async_fetch_image = AsyncMock(return_value=(b"img", "image/png"))
    out = await player.async_get_browse_image("music", "id")
    assert out == (b"img", "image/png")


# ---------- update_from_client state machine ----------


def test_update_from_client_known_state() -> None:
    """A valid lowercase state string maps to the matching MediaPlayerState."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player.async_write_ha_state = MagicMock()
    player.update_from_client("playing", {})
    assert player._attr_state == MediaPlayerState.PLAYING


def test_update_from_client_error_state_maps_to_idle() -> None:
    """A client ``error`` state degrades to IDLE."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player.async_write_ha_state = MagicMock()
    player.update_from_client("error", {})
    assert player._attr_state == MediaPlayerState.IDLE


def test_update_from_client_unknown_state_maps_to_idle() -> None:
    """An unknown state string also degrades to IDLE."""
    from homeassistant.components.media_player import MediaPlayerState  # noqa: PLC0415

    player = _make_player()
    player.async_write_ha_state = MagicMock()
    player.update_from_client("wat", {})
    assert player._attr_state == MediaPlayerState.IDLE


def test_update_from_client_syncs_attributes() -> None:
    """Volume + mute attributes are mirrored from the client payload."""
    player = _make_player()
    player.async_write_ha_state = MagicMock()
    attrs = {
        "volume_level": 0.4,
        "is_volume_muted": True,
        "media_title": "Title",
        "media_artist": "Artist",
        "entity_picture": "pic",
    }
    player.update_from_client("paused", attrs)
    assert player._attr_volume_level == 0.4
    assert player._attr_is_volume_muted is True
    assert player._attr_media_title == "Title"


def test_update_from_client_handles_attribute_exception() -> None:
    """A broken attribute dict is logged but not re-raised."""
    player = _make_player()
    player.async_write_ha_state = MagicMock()

    class BadAttrs:
        def __contains__(self, _key):
            raise RuntimeError("bad")

    player.update_from_client("idle", BadAttrs())


# ---------- async_setup_entry ----------


async def test_async_setup_entry_adds_player_for_touch_module(
    hass: HomeAssistant,
) -> None:
    """async_setup_entry adds one HbtnMediaPlayer per Smart Controller Touch."""
    touch = _make_touch_module()
    other = MagicMock()
    other.mod_type = "Smart Controller"
    smhub = MagicMock()
    smhub.router.modules = [touch, other]
    smhub.ws_provider = _make_provider()

    entry = MagicMock()
    entry.runtime_data = smhub

    added: list = []
    await async_setup_entry(hass, entry, added.extend)
    assert len(added) == 1
    assert isinstance(added[0], HbtnMediaPlayer)
    assert touch.media_player is added[0]


async def test_async_setup_entry_short_circuits_without_provider(
    hass: HomeAssistant,
) -> None:
    """Without a WS provider, async_setup_entry logs and returns."""
    touch = _make_touch_module()
    smhub = MagicMock()
    smhub.router.modules = [touch]
    smhub.ws_provider = None
    entry = MagicMock()
    entry.runtime_data = smhub

    added: list = []
    await async_setup_entry(hass, entry, added.extend)
    assert added == []
