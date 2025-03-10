# Smutscrape: Just a Scraper for Smut, Folks! 🍆💦

A Python-based tool to scrape and download adult content from various websites straight to your preferred data store. Whether it’s videos, tags, or search results, `smutscrape` has you covered—discreetly and efficiently. 😈

---

## Requirements 🧰
- Python 3.10+ 🐍
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloads
- Optional: [Selenium](https://pypi.org/project/selenium/) + Chromedriver for JS-heavy sites (e.g., Motherless) 🧑🏼‍💻
- Optional: Conda for environment management 🐼

All Python dependencies are in `requirements.txt`.

---

## Installation 🛠️

1. **Clone the Repo 📂**
   ```bash
   git clone https://github.com/io-flux/smutscrape.git
   cd smutscrape
   ```

2. **Install Dependencies 🚀**
   - **With Conda (Recommended):**
     ```bash
     conda create -n smutscrape python=3.10.13
     conda activate smutscrape
     pip install -r requirements.txt
     ```
   - **With pip:**
     ```bash
     pip3 install -r requirements.txt
     ```

   For JS-heavy sites, run a Selenium Chrome container:
   ```bash
   docker run -d -p 4444:4444 --shm-size=2g --name selenium-chrome selenium/standalone-chrome
   ```

3. **Configure `config.yaml` ⚙️**
   ```bash
   cp example-config.yaml config.yaml
   nano config.yaml
   ```
   Key sections to tweak:
   - `download_destinations` 💾 (e.g., local, SMB, WebDAV)
   - `ignored` 🚫 (terms to skip)
   - `vpn` 🤫 (for privacy)
   - `chromedriver` ⚙️ (if using Selenium)

4. **Make Executable 🚀**
   ```bash
   chmod +x scrape.py
   ```

5. **Optional: Add Symlink 🔗**
   Run `scrape` from anywhere:
   ```bash
   sudo ln -s $(realpath ./scrape.py) /usr/local/bin/scrape
   ```

---

## Usage 🚀

### Basic Commands
Run with `./scrape.py` or just `scrape` if symlinked.

- **Pornhub: Massy Sweet’s Pornstar Page 🦉🙋🏼‍♀️**
  ```bash
  scrape ph pornstar "Massy Sweet"
  # OR
  scrape https://www.pornhub.com/pornstar/Massy-Sweet
  ```

- **Incestflix: Lily LaBeau + PrimalFetish Videos 👩‍❤️‍💋‍👨🤫**
  ```bash
  scrape if search "Lily Labeau & PrimalFetish"
  # OR
  scrape https://www.incestflix.com/tag/Lily-Labeau/and/PrimalFetish
  ```

- **Lonefun: "Real Incest" Tag Results 🧬❣️**
  ```bash
  scrape lf tag "real incest"
  # OR
  scrape https://lonefun.com/@real+incest
  ```

- **Motherless: Specific Video 🙊🙈**
  ```bash
  scrape https://motherless.com/2ABC9F3
  ```

### Fallback Mode 😅
For unsupported sites, `yt-dlp` kicks in as a fallback:
```bash
scrape https://someUnsupportedSite.com/video/12345
```

---

## Supported Sites & Modes 🌐

| Site Code | Site             | Modes Available                  |
|-----------|------------------|----------------------------------|
| `9v`      | 9vids.com        | `search`, `tag`                  |
| `if`      | incestflix.com   | `search` (use `&` for multi-term) |
| `lf`      | lonefun.com      | `search`, `tag`                  |
| `ml`      | motherless.com   | `search`, `category`, `user`, `group` |
| `ph`      | pornhub.com      | `search`, `category`, `channel`, `model`, `pornstar` |
| `sb`      | spankbang.com    | `search`, `model`, `tag`         |

---

## Advanced Configuration ⚙️

### Filtering Content 🚫
Skip unwanted videos by adding terms to `ignored` in `config.yaml`:
```yaml
ignored:
  - "JOI"
  - "Femdom"
  - "Virtual Sex"
  - "Scat"
```

### VPN Support 🔒
Stay anonymous with VPN integration (e.g., ProtonVPN):
```yaml
vpn:
  enabled: true
  vpn_bin: "/usr/bin/protonvpn-cli"
  start_cmd: "{vpn_bin} connect"
  stop_cmd: "{vpn_bin} disconnect"
  new_node_cmd: "{vpn_bin} connect --random"
  new_node_time: 300  # Reconnect every 5 minutes
```
Set `enabled: false` to disable.

### Download Destinations 📁
Prioritize storage options:
```yaml
download_destinations:
  - type: smb
    server: "192.168.50.5"
    share: "Media"
    username: "user"
    password: "pass"
  - type: local
    path: "~/.xxx"
```
The first working destination is used. Remove unused types to avoid errors.

### Overwriting Files
By default, existing files won’t be overwritten unless `no_overwrite: false` is set in the site’s `.yaml` config.

---

## Disclaimer ⚠️
You’re on your own with this one. Scrape responsibly! 🧠💭
