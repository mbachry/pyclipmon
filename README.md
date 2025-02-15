# pyclipmon

Wayland clipboard store daemon

Python reimplementation of [clipmon](https://git.sr.ht/~whynothugo/clipmon):

* doesn't maintain internal state and doesn't suffer on bad state bugs

* supports timeouts and doesn't get stuck on large clipboards

* implements enough nasty hacks to make Emacs clipboard work reliably

## Install

Install with pipx:

```
pipx install https://github.com/mbachry/pyclipmon
```

Add user systemd unit file:

```
[Unit]
Description=Clipboard monitor for Wayland

[Service]
ExecStart=%h/.local/bin/pyclipmon

[Install]
WantedBy=graphical-session.target
```

## Clipboard history

In addition to saving current clipboard `pyclipmon` stores history in
a sqlite3 file. You can retrieve the history and pass it to
[`fuzzel`](https://codeberg.org/dnkl/fuzzel) with the provided
`pyclipmon-pick` tool.

Install `meson`, `sqlite3` development package (`sqlite-devel` on
Fedora), `fuzzel` and `wl-clipboard`. Build with:

```
meson setup build
ninja -C build
```

Example sway config:

```
bindsym $mod+v exec ~/.local/bin/pyclipmon-pick
```
