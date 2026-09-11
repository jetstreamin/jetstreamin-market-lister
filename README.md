# Jetstreamin Market Lister

Created by **Jetstreamin**. A Termux-native, local-first catalog, listing exporter, and manual Facebook auction manager.

## Install on Android

Install Termux and the separate Termux:API Android app from the same trusted source (normally F-Droid), copy this folder into Termux, then run:

```bash
chmod +x install-termux.sh
./install-termux.sh
./jet
```

The app opens at `http://127.0.0.1:8787`. Add it to the Android home screen for an app-like launch.

## What it does

- Takes a photo through `termux-camera-photo`.
- Stores catalog records, photos, auctions, and bids locally in SQLite.
- Optionally calls an Ollama vision model on the phone, desktop, or LAN.
- Produces conservative eBay draft JSON, Whatnot draft JSON, and copy-ready Facebook auction posts.
- Tracks manual Facebook bids, validates the minimum increment, and shows the current winner.

Exports are drafts, not claims of official bulk-import compatibility. Direct eBay/Whatnot/Meta adapters can be added without changing the catalog.

## Local AI

Open Settings in the app and enter an Ollama base URL reachable from the phone, such as `http://192.168.1.50:11434`, plus a vision-capable model such as `qwen3-vl:8b`. Ollama must listen on the LAN and the firewall must allow only your private network.

## CLI

```bash
python app.py new --title "New stamp" --price 3 --camera
python app.py export ITEM_ID ebay
python app.py export ITEM_ID whatnot
python app.py export ITEM_ID facebook
```

All durable data stays in `data/`. Back up that directory.
