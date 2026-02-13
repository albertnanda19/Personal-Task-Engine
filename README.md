# Personal-Task-Engine

## Run Discord Bot

```bash
python3 main.py run-bot
```

## Auto Start on Linux

### Option A: Crontab (@reboot)

1. Find your python path:

```bash
which python3
```

2. Edit crontab:

```bash
crontab -e
```

3. Add (use absolute paths):

```bash
@reboot /usr/bin/python3 /absolute/path/to/main.py run-bot >> /absolute/path/to/logs/startup.log 2>&1
```

### Option B: systemd (recommended)

Create:

`/etc/systemd/system/taskbot.service`

```ini
[Unit]
Description=Personal Task Bot
After=network.target

[Service]
ExecStart=/usr/bin/python3 /absolute/path/to/main.py run-bot
WorkingDirectory=/absolute/path/to/project
Restart=always
User=YOUR_USERNAME

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable taskbot
sudo systemctl start taskbot
```

Check status:

```bash
systemctl status taskbot --no-pager
```

View logs:

```bash
journalctl -u taskbot -f
```
