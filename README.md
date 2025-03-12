# Smutscrape: Just a Scraper for Smut, Folks! 🍆💦

A Python-based tool to scrape and download adult content from various websites straight to your preferred data store. Whether it’s videos, tags, or search results, `smutscrape` has you covered—discreetly and efficiently. Supports multiple download methods and advanced scraping with Selenium for tricky sites. 😈

---

## Requirements 🧰
- Python 3.10+ 🐍
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloads
- [wget](https://www.gnu.org/software/wget/) or [curl](https://curl.se/) for alternative downloads
- [ffmpeg](https://ffmpeg.org/) for M3U8 stream downloads
- Optional: [Selenium](https://pypi.org/project/selenium/) + [Chromedriver](https://chromedriver.chromium.org/) for JS-heavy sites
- Optional: [webdriver-manager](https://pypi.org/project/webdriver-manager/) for automatic ChromeDriver management (in `requirements.txt`)
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
   sudo apt-get install yt-dlp wget curl ffmpeg chromium
   # On macOS with Homebrew
   brew install yt-dlp wget curl ffmpeg google-chrome
   ```

   For Selenium (optional):
   - `webdriver-manager` auto-downloads ChromeDriver by default.
   - Or install manually (e.g., `brew install chromedriver`) and set `chromedriver_path` in `config.yaml`.

3. **Configure `config.yaml` ⚙️**
   ```bash
   cp example-config.yaml config.yaml
   nano config.yaml
   ```
   Tweak `download_destinations`, `ignored`, `vpn`, or `selenium.chromedriver_path`.

4. **Make Executable 🚀**
   ```bash
   chmod +x scrape.py
   ```

5. **Optional: Add Symlink 🔗**
   ```bash
   sudo ln -s $(realpath ./scrape.py) /usr/local/bin/scrape
   ```

---

## Usage 🚀

### Basic Commands
Run with `./scrape.py` or `scrape` if symlinked.

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

- **FamilySexVideos: Search "Teen" 👩‍🏫**
  ```bash
  scrape fsv search "teen"
  # OR
  scrape https://familysexvideos.org/en/search/?search=teen
  ```

- **XVideos: Tag "Amateur" 🎥**
  ```bash
  scrape xv tags "amateur"
  # OR
  scrape https://www.xvideos.com/tags/amateur
  ```

- **XNXX: Channel "Naughty America" 📺**
  ```bash
  scrape xnxx channel "naughty-america"
  # OR
  scrape https://www.xnxx.com/channels/naughty-america
  ```

### Fallback Mode 😅
For unsupported sites, `yt-dlp` kicks in:
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
| `fsv`     | familysexvideos.org      | `video`, `search`                            |
| `if`      | incestflix.com           | `video`, `search`, `tag`                     |
| `lf`      | lonefun.com              | `video`, `search`, `tag`                     |
| `ml`      | motherless.com           | `video`, `search`, `category`, `user`, `group` |
| `ph`      | pornhub.com              | `video`, `model`, `category`, `category_alt`, `channel`, `search`, `pornstar` |
| `sb`      | spankbang.com            | `video`, `model`, `search`, `tag`            |
| `triv`    | toprealincestvideos.com  | `video`, `search`                            |
| `xnxx`    | xnxx.com                 | `video`, `search`, `channel`, `pornstar`, `tag` |
| `xv`      | xvideos.com              | `video`, `search`, `channels`, `models`, `tags` |

---

## Advanced Configuration ⚙️

### Download Methods 📥
Set in each site’s `.yaml`: `yt-dlp` (default), `wget`, `curl`, or `ffmpeg` (for M3U8 streams).

### Selenium & Chromedriver 🕵️‍♂️
For JS-heavy sites or M3U8 streams:
- Enable with `use_selenium: true` in site config.
- Used for iframe piercing or M3U8 URL extraction (`m3u8_mode: true`).
- In `config.yaml`, set `selenium.chromedriver_path` or rely on `webdriver-manager`.

### Filtering Content 🚫
Skip terms in `config.yaml`:
```yaml
ignored:
  - "JOI"
  - "Femdom"
```

### Pagination 📄
Pagination is automatic. For modes with `url_pattern_pages` (e.g., `xnxx`’s `search`), resume from a specific page:
```bash
scrape if tag "ms" --start_on_page 69
```

### VPN Support 🔒
Enable in `config.yaml`:
```yaml
vpn:
  enabled: true
  vpn_bin: "/usr/bin/protonvpn-cli"
  start_cmd: "{vpn_bin} connect"
  new_node_time: 300
```

### Download Destinations 📁
Set in `config.yaml`:
```yaml
download_destinations:
  - type: "local"
    path: "~/.xxx"
```

### Overwriting Files
Use `--overwrite_files` or set `no_overwrite: false` in site config.

---

## Disclaimer ⚠️
Scrape responsibly! You’re on your own. 🧠💭
