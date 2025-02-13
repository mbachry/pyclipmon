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
