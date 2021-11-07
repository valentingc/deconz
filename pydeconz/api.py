"""API base classes."""
from __future__ import annotations

from asyncio import CancelledError, Task, create_task, sleep
import logging
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    ItemsView,
    KeysView,
    Optional,
    Union,
    ValuesView,
)

from .errors import BridgeBusy

LOGGER = logging.getLogger(__name__)

DataDictType = Dict[str, Union[bool, float, int, str, dict, tuple, None]]
JsonDictType = Dict[str, Union[bool, int, str, DataDictType]]
JsonBlobType = Dict[str, JsonDictType]


class APIItems:
    """Base class for a map of API Items."""

    def __init__(
        self,
        raw: JsonBlobType,
        request: Callable[..., Awaitable[Dict[str, Any]]],
        path: str,
        item_cls: Any,
    ) -> None:
        """Initialize API items."""
        self._request = request
        self._path = path
        self._item_cls = item_cls
        self._items: dict = {}
        self.process_raw(raw)

    async def update(self) -> None:
        """Refresh data."""
        raw: JsonBlobType = await self._request("get", self._path)
        self.process_raw(raw)

    def process_raw(self, raw: JsonBlobType) -> None:
        """Process data."""
        for id, raw_item in raw.items():

            if (obj := self._items.get(id)) is not None:
                obj.update(raw_item)

            else:
                self._items[id] = self._item_cls(id, raw_item, self._request)

    def items(self) -> ItemsView[str, Any]:
        """Return items."""
        return self._items.items()

    def keys(self) -> KeysView[Any]:
        """Return item keys."""
        return self._items.keys()

    def values(self) -> ValuesView[Any]:
        """Return item values."""
        return self._items.values()

    def __getitem__(self, obj_id: str) -> Any:
        """Get item value based on key."""
        return self._items[obj_id]

    def __iter__(self) -> Any:
        """Allow iterate over items."""
        return iter(self._items)


class APIItem:
    """Base class for an API item."""

    def __init__(
        self,
        resource_id: str,
        raw: JsonDictType,
        request: Callable[..., Awaitable[Dict[str, Any]]],
    ) -> None:
        """Initialize API item."""
        self._resource_id = resource_id
        self._raw = raw
        self._request = request

        self._callbacks: list = []
        self._sleep_task: Optional[Task] = None
        self._changed_keys: set = set()

    @property
    def resource_id(self) -> str:
        """Read only resource ID."""
        return self._resource_id

    @property
    def raw(self) -> dict:
        # def raw(self) -> JsonDictType:
        """Read only raw data."""
        return self._raw

    @property
    def changed_keys(self) -> set:
        """Read only changed keys data."""
        return self._changed_keys

    def register_callback(self, callback: Callable[..., None]) -> None:
        """Register callback for signalling."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[..., None]) -> None:
        """Remove callback previously registered."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def update(self, raw: JsonDictType) -> None:
        """Update input attr in self.

        Store a set of keys with changed values.
        """
        changed_keys = set()

        for k, v in raw.items():
            changed_keys.add(k)

            if (raw_value := self._raw.get(k)) is None:
                continue

            if isinstance(raw_value, dict) and isinstance(v, dict):
                changed_keys.update(set(v.keys()))
                raw_value.update(v)

            else:
                self._raw[k] = v

        self._changed_keys = changed_keys

        for signal_update_callback in self._callbacks:
            signal_update_callback()

    async def request(self, field: str, data: dict, tries: int = 0) -> dict:
        """Set state of device."""
        if self._sleep_task is not None:
            self._sleep_task.cancel()
            self._sleep_task = None

        try:
            return await self._request("put", path=field, json=data)

        except BridgeBusy:
            LOGGER.debug("Bridge is busy, schedule retry %s %s", field, str(data))

            if (tries := tries + 1) < 3:
                self._sleep_task = create_task(sleep(2 ** (tries)))

                try:
                    await self._sleep_task
                except CancelledError:
                    return {}

                return await self.request(field, data, tries)

            self._sleep_task = None
            raise BridgeBusy
