# Smutscrape: Just a Scraper for Smut, Folks! 🍆💦

A Python-based tool to scrape and download adult content from various websites straight to your preferred data store. Whether it’s videos, tags, or search results, `smutscrape` has you covered—discreetly and efficiently. Supports multiple download methods and advanced scraping with Selenium for tricky sites. 😈

---

## Requirements 🧰
- Python 3.10+ 🐍
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloads
- [wget](https://www.gnu.org/software/wget/) or [curl](https://curl.se/) for alternative downloads
- [ffmpeg](https://ffmpeg.org/) for M3U8 stream downloads
- Optional: [Selenium](https://pypi.org/project/selenium/) + [Chromedriver](https://chromedriver.chromium.org/) for JS-heavy sites, iframe piercing, and M3U8 URL extraction 🧑🏼‍💻
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

   Install additional tools:
   ```bash
   # On Ubuntu/Debian
   sudo apt-get install yt-dlp wget curl ffmpeg
   # On macOS with Homebrew
   brew install yt-dlp wget curl ffmpeg
   ```

   For Selenium (optional):
   - Install Chromedriver manually or via `webdriver_manager` (included in `requirements.txt`).
   - Or run a Selenium Chrome container:
     ```bash
     docker run -d -p 4444:4444 --shm-size=2g --name selenium-chrome selenium/standalone-chrome
     ```

3. **Configure `config.yaml` ⚙️**
   ```bash
   cp example-config.yaml config.yaml
   nano config.yaml
   ```
   Key sections to tweak:
   - `download_destinations` 💾 (e.g., local, SMB)
   - `ignored` 🚫 (terms to skip)
   - `vpn` 🤫 (for privacy)
   - `selenium.chromedriver_path` ⚙️ (if using Selenium)

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
  scrape https://www.pornhub.com/pornstar/massy-sweet
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

- **TopRealIncestVideos: Search "Sister" 👧**
  ```bash
  scrape triv search "sister"
  # OR
  scrape https://toprealincestvideos.com/en/search/?search=sister
  ```

### Fallback Mode 😅
For unsupported sites, `yt-dlp` kicks in as a fallback:
```bash
scrape https://someUnsupportedSite.com/video/12345
```

---

## Supported Sites & Modes 🌐

| Site Code | Site                     | Modes Available                              |
|-----------|--------------------------|----------------------------------------------|
| `9v`      | 9vids.com                | `video`, `search`, `tag`                     |
| `fs`      | family-sex.me            | `video`, `tag`, `search`                     |
| `fphd`    | familypornhd.com         | `video`, `tag`                               |
| `if`      | incestflix.com           | `video`, `search` (use `&` for multi-term)   |
| `lf`      | lonefun.com              | `video`, `search`, `tag`                     |
| `ml`      | motherless.com           | `video`, `search`, `category`, `user`, `group` |
| `ph`      | pornhub.com              | `video`, `model`, `category`, `category_alt`, `channel`, `search`, `pornstar` |
| `sb`      | spankbang.com            | `video`, `model`, `search`, `tag`            |
| `triv`    | toprealincestvideos.com  | `video`, `search`                            |

---

## Advanced Configuration ⚙️

### Download Methods 📥
Choose your download tool in each site’s `.yaml`:
- `yt-dlp`: Default, robust for most sites.
- `wget`: Lightweight, good for direct URLs.
- `curl`: Alternative for direct downloads.
- `ffmpeg`: Ideal for M3U8 streams (e.g., `familypornhd.com`).

Example:
```yaml
download:
  method: "ffmpeg"
```

### Selenium & Chromedriver 🕵️‍♂️
For JS-heavy sites or M3U8 streams:
- Enable with `use_selenium: true` in the site’s `.yaml`.
- Used to:
  - **Pierce Iframes**: Extracts URLs from iframe `src` (e.g., `familypornhd.com`).
  - **Gather M3U8 URLs**: Captures `.m3u8` streams via network logs (requires `m3u8_mode: true`).
- Configure in `config.yaml`:
  ```yaml
  selenium:
    chromedriver_path: "/usr/local/bin/chromedriver"
    mode: "local"  # or "remote" for Docker
    chrome_binary: "/path/to/chrome"  # Optional
  ```

### Filtering Content 🚫
Skip unwanted videos by adding terms to `ignored` in `config.yaml`:
```yaml
ignored:
  - "JOI"
  - "Femdom"
  - "Virtual Sex"
  - "Scat"
```

### Pagination 📄
- **URL-Based**: Define `url_pattern_pages` in a mode (e.g., `/s/{search}/{page}/?o=all/` for SpankBang).
- **Selector-Based**: Use `list_scraper.pagination.next_page` (e.g., `li.page_next a` for Pornhub).
- Prioritizes `url_pattern_pages` if both are present.

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
The first working destination is used.

### Overwriting Files
Add `--overwrite_files` to the command or set `no_overwrite: false` in the site’s `.yaml` to overwrite existing files.

---

## Disclaimer ⚠️
You’re on your own with this one. Scrape responsibly! 🧠💭
```

