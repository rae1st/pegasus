# flake8: noqa

__title__ = "Pegasus"
__author__ = "raeist"
__license__ = "MIT"
__copyright__ = "Copyright 2025-present raeist"
__version__ = "0.0.1"

from typing import Type

from .core.abc import *
from .core.common import *
from .core.dataio import *

from .client.client import *
from .client.node import *
from .client.nodemanager import *
from .client.filters import *

from .player.player import *
from .player.playermanager import *
from .player.events import *

from .errors.errors import *

from .utils.helpers import *


def listener(*events: Type[Event]):
    """
    Marks this function as an event listener for Pegasus.
    This **must** be used on class methods, and you must ensure that you register
    decorated methods by using :func:`Client.add_event_hooks`.

    Example:

        .. code:: python

            @listener()
            async def on_pegasus_event(self, event):  # Event can be ANY Pegasus event
                ...

            @listener(TrackStartEvent)
            async def on_track_start(self, event: TrackStartEvent):
                ...

    Note
    ----
    Track event dispatch order is not guaranteed!
    For example, this means you could receive a :class:`TrackStartEvent` before you receive a
    :class:`TrackEndEvent` when executing operations such as ``skip()``.

    Parameters
    ----------
    events: :class:`Event`
        The events to listen for. Leave this empty to listen for all events.
    """

    def wrapper(func):
        setattr(func, "_pegasus_events", events)
        return func

    return wrapper
