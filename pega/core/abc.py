"""
MIT License

Copyright (c) 2025-present raeist

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import logging
from abc import ABC, abstractmethod
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Final,
    Generic,
    Optional,
    Sequence,
    TypeVar,
    Union,
    cast,
)

from pega.core.common import MISSING, VoiceServerUpdateData, VoiceStateUpdateData
from pega.errors.errors import InvalidTrack, LoadError
from pega.player.events import Event, TrackLoadFailedEvent
from pega.core.server import AudioTrack, RawPlayer, RawPlayerState

if TYPE_CHECKING:
    from pega.client.client import Client
    from pega.client.node import Node
    from pega.core.server import LoadResult

__all__ = (
    "BasePlayer",
    "DeferredAudioTrack",
    "Source",
    "Filter",
)

_log = logging.getLogger(__name__)

FilterValueT = TypeVar(
    "FilterValueT",
    Dict[str, Any],
    Sequence[float],
    Sequence[int],
    float,
)


class BasePlayer(ABC):
    """
    Represents the BasePlayer all players must be inherited from.

    Attributes
    ----------
    client: :class:`Client`
        The Pegasus client instance.
    guild_id: :class:`int`
        The guild id of the player.
    node: :class:`Node`
        The node that the player is connected to.
    channel_id: Optional[:class:`int`]
        The ID of the voice channel the player is connected to.
        This could be ``None`` if the player isn't connected.
    current: Optional[:class:`AudioTrack`]
        The currently playing track.
    """

    __slots__ = (
        "client",
        "guild_id",
        "node",
        "channel_id",
        "current",
        "_next",
        "_internal_id",
        "_original_node",
        "_voice_state",
    )

    def __init__(self, guild_id: int, node: "Node"):
        self.client: Final["Client"] = node.manager.client
        self.guild_id: Final[int] = guild_id
        self.node: "Node" = node
        self.channel_id: Optional[int] = None
        self.current: Optional[AudioTrack] = None

        self._next: Optional[AudioTrack] = None
        self._internal_id: Final[str] = str(guild_id)
        self._original_node: Optional["Node"] = None
        self._voice_state = {}

    @abstractmethod
    async def handle_event(self, event: Event):
        """|coro|

        Handles an :class:`Event` received directly from the websocket.

        Parameters
        ----------
        event: :class:`Event`
            The event that will be handled.
        """
        raise NotImplementedError

    @abstractmethod
    async def update_state(self, state: RawPlayerState):
        """|coro|

        .. _state object: https://lavalink.dev/api/websocket#player-state

        Updates this player's state with the `state object`_ received from the server.

        Parameters
        ----------
        state: Dict[:class:`str`, Any]
            The player state.
        """
        raise NotImplementedError

    async def play_track(
        self,
        track: Union[AudioTrack, "DeferredAudioTrack"],
        start_time: int = MISSING,
        end_time: int = MISSING,
        no_replace: bool = MISSING,
        volume: int = MISSING,
        pause: bool = MISSING,
        **kwargs,
    ) -> Optional[RawPlayer]:
        """|coro|

        .. _player object: https://lavalink.dev/api/rest.html#Player

        Plays the given track.

        Warning
        -------
        Multiple calls to this method within a short timeframe could cause issues with the player's
        internal state, which can cause errors when processing a :class:`TrackStartEvent`.

        Parameters
        ----------
        track: Union[:class:`AudioTrack`, :class:`DeferredAudioTrack`]
            The track to play.
        start_time: :class:`int`
            The number of milliseconds to offset the track by.
        end_time: :class:`int`
            The position at which the track should stop playing.
        no_replace: :class:`bool`
            If set to true, operation will be ignored if a track is already playing or paused.
        volume: :class:`int`
            The initial volume to set.
        pause: :class:`bool`
            Whether to immediately pause the track after loading it.
        **kwargs: Any
            Extra parameters for plugins.

        Returns
        -------
        Optional[:class:`RawPlayer`]
            The updated `player object`_, or ``None`` if no request was made.
        """
        if track is MISSING or not isinstance(track, AudioTrack):
            raise ValueError("track must be an instance of an AudioTrack!")

        options = kwargs

        if start_time is not MISSING:
            if not isinstance(start_time, int) or 0 > start_time:
                raise ValueError(
                    "start_time must be an int with a value equal to, or greater than 0"
                )
            options["position"] = start_time

        if end_time is not MISSING:
            if not isinstance(end_time, int) or 1 > end_time:
                raise ValueError(
                    "end_time must be an int with a value equal to, or greater than 1"
                )
            options["end_time"] = end_time

        if no_replace is not MISSING:
            if not isinstance(no_replace, bool):
                raise TypeError("no_replace must be a bool")
            options["no_replace"] = no_replace

        if volume is not MISSING:
            if not isinstance(volume, int):
                raise TypeError("volume must be an int")
            options["volume"] = max(min(volume, 1000), 0)

        if pause is not MISSING:
            if not isinstance(pause, bool):
                raise TypeError("pause must be a bool")
            options["paused"] = pause

        playable_track = track.track

        if playable_track is None:
            if not isinstance(track, DeferredAudioTrack):
                raise InvalidTrack(
                    "Cannot play the AudioTrack as 'track' is None, and it is not a DeferredAudioTrack!"
                )

            try:
                playable_track = await track.load(self.client)
            except LoadError as load_error:
                self.client._dispatch_event(
                    TrackLoadFailedEvent(self, track, load_error)
                )
                return

        if playable_track is None:
            self.client._dispatch_event(
                TrackLoadFailedEvent(self, track, None)  # type: ignore
            )
            return

        self._next = track

        if "user_data" not in options and track.user_data:
            options["user_data"] = track.user_data

        response = await self.node.update_player(
            guild_id=self._internal_id, encoded_track=playable_track, **options
        )
        return cast(RawPlayer, response)

    def cleanup(self):
        pass

    async def destroy(self):
        """|coro|

        Destroys the current player instance.
        """
        await self.client.player_manager.destroy(self.guild_id)

    async def _voice_server_update(self, data: VoiceServerUpdateData):
        self._voice_state.update(endpoint=data["endpoint"], token=data["token"])

        if "sessionId" not in self._voice_state:
            _log.warning(
                "[Player:%s] Missing sessionId, is the client User ID correct?",
                self.guild_id,
            )

        await self._dispatch_voice_update()

    async def _voice_state_update(self, data: VoiceStateUpdateData):
        raw_channel_id = data["channel_id"]
        self.channel_id = int(raw_channel_id) if raw_channel_id else None

        if not self.channel_id:
            self._voice_state.clear()
            return

        if data["session_id"] != self._voice_state.get("sessionId"):
            self._voice_state.update(sessionId=data["session_id"])
            await self._dispatch_voice_update()

    async def _dispatch_voice_update(self):
        if {"sessionId", "endpoint", "token"} == self._voice_state.keys():
            await self.node.update_player(
                guild_id=self._internal_id, voice_state=self._voice_state  # type: ignore
            )

    @abstractmethod
    async def node_unavailable(self):
        """|coro|

        Called when a player's node becomes unavailable.
        """
        raise NotImplementedError

    @abstractmethod
    async def change_node(self, node: "Node"):
        """|coro|

        Called when a node change is requested for the current player instance.
        """
        raise NotImplementedError


class DeferredAudioTrack(ABC, AudioTrack):
    """
    Similar to an :class:`AudioTrack`, however this track only stores metadata up until it's
    played, at which time :func:`load` is called.
    """

    __slots__ = ()

    @abstractmethod
    async def load(self, client: "Client") -> Optional[str]:
        """|coro|

        Retrieves a base64 string that's playable by Pegasus.
        """
        raise NotImplementedError


class Source(ABC):
    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name: str = name

    def __eq__(self, other):
        if self.__class__ is other.__class__:
            return self.name == other.name
        return False

    def __hash__(self):
        return hash(self.name)

    @abstractmethod
    async def load_item(self, client: "Client", query: str) -> Optional["LoadResult"]:
        """|coro|

        Loads a track with the given query.
        """
        raise NotImplementedError

    def __repr__(self):
        return f"<Source name={self.name}>"


class Filter(ABC, Generic[FilterValueT]):
    """
    A class representing a Pegasus audio filter.
    """

    __slots__ = ("values", "plugin_filter")

    def __init__(self, values: FilterValueT, plugin_filter: bool = False):
        self.values: FilterValueT = values
        self.plugin_filter: Final[bool] = plugin_filter

    @abstractmethod
    def update(self, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def serialize(self) -> Dict[str, FilterValueT]:
        raise NotImplementedError
