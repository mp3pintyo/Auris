"""Small request coalescer for interactive TTS generation.

The browser asks for several look-ahead segments concurrently.  Flask serves
those requests on separate threads, so without coordination every request
would call the model with batch=1.  This class briefly collects the requests
and hands them to the engine's existing generate_many() implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Callable


@dataclass
class _PendingCall:
    key: object
    item: dict
    priority: bool = False
    event: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    error: Exception | None = None


class InteractiveTTSBatcher:
    """Combine concurrent per-segment requests into real model batches."""

    def __init__(
        self,
        generate_many: Callable,
        *,
        collect_ms: int = 75,
        blocked: Callable[[], bool] | None = None,
    ):
        self._generate_many = generate_many
        self._collect_sec = max(0, int(collect_ms)) / 1000.0
        self._blocked = blocked
        self._lock = threading.Lock()
        self._queue: list[_PendingCall] = []
        self._by_key: dict[object, _PendingCall] = {}
        self._worker_running = False

    def submit(self, key: object, item: dict, *, priority: bool = False) -> dict:
        """Queue one item and wait for its individual batch result.

        Identical in-flight keys share the same result, preventing duplicate
        synthesis when the playback and look-ahead paths request one segment.
        """
        with self._lock:
            call = self._by_key.get(key)
            if call is None:
                call = _PendingCall(key=key, item=dict(item), priority=bool(priority))
                self._by_key[key] = call
                self._queue.append(call)
            elif priority:
                # A playback request can arrive after the same segment was
                # queued by look-ahead. Promote it before the worker drains.
                call.priority = True
            if not self._worker_running:
                self._worker_running = True
                threading.Thread(target=self._drain, daemon=True).start()

        call.event.wait()
        if call.error is not None:
            raise call.error
        if call.result is None:
            raise RuntimeError("Interactive TTS batch returned no result.")
        return call.result

    def _finish(
        self,
        call: _PendingCall,
        *,
        result: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        # An on_item callback can race with batch-level cleanup.  The first
        # concrete outcome wins.
        if call.event.is_set():
            return
        call.result = result
        call.error = error
        call.event.set()

    def _drain(self) -> None:
        if self._collect_sec:
            time.sleep(self._collect_sec)

        while True:
            with self._lock:
                batch = self._queue
                self._queue = []
                if not batch:
                    self._worker_running = False
                    return

            if self._blocked is not None and self._blocked():
                error = RuntimeError(
                    "Export in progress — interactive TTS is paused until export finishes."
                )
                for call in batch:
                    self._finish(call, error=error)
            else:
                # Playback-critical calls must not wait behind a large
                # look-ahead pack: the model returns a batch only after every
                # sentence is synthesized. Run priority calls individually,
                # then retain batching throughput for look-ahead requests.
                priority_calls = [call for call in batch if call.priority]
                lookahead_calls = [call for call in batch if not call.priority]
                if not priority_calls:
                    # Preserve the original latency behavior for callers that
                    # do not yet provide an explicit priority marker.
                    priority_calls = batch[:1]
                    lookahead_calls = batch[1:]
                priority_batches = [[call] for call in priority_calls]
                if lookahead_calls:
                    priority_batches.append(lookahead_calls)
                for work_batch in priority_batches:
                    returned: list[dict] | None = None

                    def on_item(index: int, result: dict) -> None:
                        if 0 <= index < len(work_batch):
                            self._finish(work_batch[index], result=result)

                    try:
                        returned = self._generate_many(
                            [call.item for call in work_batch],
                            on_item=on_item,
                        )
                        # Engines are expected to invoke on_item, but accepting
                        # the returned list keeps the coordinator compatible
                        # with simpler engines and test doubles.
                        for index, call in enumerate(work_batch):
                            if (
                                not call.event.is_set()
                                and returned is not None
                                and index < len(returned)
                            ):
                                self._finish(call, result=returned[index])
                    except Exception as exc:
                        for call in work_batch:
                            self._finish(call, error=exc)

                    for call in work_batch:
                        if not call.event.is_set():
                            self._finish(
                                call,
                                error=RuntimeError(
                                    "Interactive TTS batch did not complete this segment."
                                ),
                            )

            with self._lock:
                for call in batch:
                    if self._by_key.get(call.key) is call:
                        self._by_key.pop(call.key, None)
