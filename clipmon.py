import argparse
import contextlib
import logging
import os
import select
import sys
import time

import psutil
from pywayland.client import Display
from pywayland.protocol.wayland import WlRegistry, WlSeat

from zwlr_data_control import zwlr_data_control_manager_v1

SENTINEL = '__PYCLIPMON__'
RECEIVE_TIMEOUT_S = 2

display = None
manager_proxy = None
seat_proxy = None
offers = {}
emacs_running_at_start = False


class Selection:
    def __init__(self, name, set_selection_func, primary_selection=None):
        self.name = name
        self.set_selection_func = set_selection_func
        self.data = {}
        self.primary_selection = primary_selection
        self.post_selection_cb = None
        self.emacs_hack_active = False
        self.log = logging.getLogger(name)

    def handle_selection(self, _, offer_proxy):
        assert display is not None

        if offer_proxy is None:
            self.log.debug(f'lost selection {offer_proxy}')
            return

        mime_types = offers.pop(offer_proxy)

        if SENTINEL in mime_types:
            self.log.debug('skipping our own offer')
            return

        self.emacs_hack_active = False
        if 'OWNER_OS' in mime_types and self.primary_selection:
            # Emacs hack:
            # 1. Read only primary selection pipes, but send offers
            #    for clipboard too
            # 2. Use primary selection data to handle clipboard offers
            # 3. pyclipmon must be started after emacs for some reason
            if not emacs_running_at_start and is_emacs_running():
                self.log.info('emacs detected, restarting')
                # Re-exec. Unfortunately an attempt to reconnect to
                # pywayland display in the same process ends with a
                # segfault.
                os.execv(sys.executable, [sys.executable] + sys.argv)
            self.log.debug('emacs hack: skipping clipboard')
            self.emacs_hack_active = True
            self.data = {m: b'' for m in mime_types}
            self.primary_selection.post_selection_cb = self._send_offers
            return

        self.data.clear()
        for mime_type in mime_types:
            rd, wr = os.pipe2(os.O_NONBLOCK)
            offer_proxy.receive(mime_type, wr)
            display.roundtrip()
            os.close(wr)
            try:
                self.data[mime_type] = read_from_pipe(rd)
            except TimeoutError:
                self.log.warning(f'timed out after {RECEIVE_TIMEOUT_S} seconds!')
                break
            finally:
                os.close(rd)

        self.log.debug('done saving')
        self._send_offers()

    def _send_offers(self):
        assert manager_proxy is not None
        source_proxy = manager_proxy.create_data_source()
        source_proxy.dispatcher['send'] = self.handle_send
        source_proxy.dispatcher['cancelled'] = self.handle_cancelled

        for mime_type, payload in self.data.items():
            source_proxy.offer(mime_type)
            preview = payload.decode('utf8', errors='ignore')[:20]
            self.log.debug(f'offered {mime_type} {len(payload)} "{preview}"')

        source_proxy.offer(SENTINEL)

        self.set_selection_func(source_proxy)
        self.log.debug(f'took selection, n_offers={len(offers)}')

        if self.post_selection_cb:
            self.post_selection_cb()
            self.post_selection_cb = None

    def handle_send(self, _, mime_type, fd):
        self.log.debug(f'send {mime_type} {len(self.data[mime_type])}')
        if mime_type == SENTINEL:
            payload = b''
        elif mime_type not in self.data:
            self.log.warning(f"requested mime type we haven't offered: {mime_type=}")
            payload = b''
        elif self.emacs_hack_active:
            assert self.primary_selection
            self.log.debug(f'send {mime_type}: emacs hack routing to primary')
            payload = self.primary_selection.data.get(mime_type, b'')
            if not payload and mime_type == 'text/plain;charset=utf-8':
                payload = self.primary_selection.data.get('text/plain', b'')
        else:
            payload = self.data[mime_type]
        with os.fdopen(fd, 'wb') as fp:
            fp.write(payload)

    def handle_cancelled(self, source_proxy):
        source_proxy.destroy()
        self.log.debug('cancelled')


def read_from_pipe(fd):
    assert display is not None
    buf = b''
    start_time = time.monotonic()
    while True:
        try:
            r = os.read(fd, 4096)
            if not r:
                break
            buf += r
        except BlockingIOError:
            pass
        display.roundtrip()
        if time.monotonic() - start_time > RECEIVE_TIMEOUT_S:
            raise TimeoutError('timed out')
    return buf


def handle_offer(offer_proxy, mime_type):
    offers[offer_proxy].add(mime_type)


def handle_data_offer(_, offer_proxy):
    offers[offer_proxy] = set()
    offer_proxy.dispatcher['offer'] = handle_offer


def handle_registry_global(registry: WlRegistry, id_num: int, interface: str, version: int) -> None:
    global manager_proxy, seat_proxy

    if interface == 'zwlr_data_control_manager_v1':
        manager_proxy = registry.bind(id_num, zwlr_data_control_manager_v1.ZwlrDataControlManagerV1, version)
    elif interface == 'wl_seat':
        seat_proxy = registry.bind(id_num, WlSeat, version)


def is_emacs_running():
    return 'emacs' in (p.info['name'] for p in psutil.process_iter(['name']))


@contextlib.contextmanager
def setup_wayland():
    with Display() as display:
        registry = display.get_registry()
        registry.dispatcher["global"] = handle_registry_global

        display.dispatch(block=True)
        display.roundtrip()

        if not manager_proxy:
            sys.exit('zwlr_data_control_manager_v1 not supported by compositor')
        assert seat_proxy

        device_proxy = manager_proxy.get_data_device(seat_proxy)
        primary = Selection('primary', device_proxy.set_primary_selection)
        clipboard = Selection('clipboard', device_proxy.set_selection, primary_selection=primary)
        device_proxy.dispatcher['data_offer'] = handle_data_offer
        device_proxy.dispatcher['selection'] = clipboard.handle_selection
        device_proxy.dispatcher['primary_selection'] = primary.handle_selection

        yield display


def main():
    global display, emacs_running_at_start

    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=level)

    emacs_running_at_start = is_emacs_running()
    logging.debug(f'{emacs_running_at_start=}')

    with setup_wayland() as display:
        fd = display.get_fd()
        while True:
            display.flush()
            select.select([fd], [], [fd])
            display.roundtrip()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
